"""The blueprint: deterministic steps and agent steps, run in order and resumable."""

import logging
import shutil

from factory import checks, human, workspace
from factory.config import Config
from factory.contracts import Check, Review, Source, Spec
from factory.crew import Crew, hire
from factory.inbox import Kind
from factory.run import STEPS, Run, Status

log = logging.getLogger("factory")
LEVELS = {Status.DONE: "info", Status.ESCALATED: "warn", Status.FAILED: "error"}


class Escalation(Exception):
    """A limit ran out and a human has to take over."""


class Pipeline:
    def __init__(self, run: Run, config: Config, crew: Crew | None = None):
        self.run = run
        self.config = config
        self.human = human.Channel(config.human, run)
        self._crew = crew

    @property
    def crew(self) -> Crew:
        if self._crew is None:
            self._crew = hire(self.config, self.run.workspace, ask=self.human.ask)
        return self._crew

    @property
    def spec(self) -> Spec:
        return self.run.spec

    def execute(self) -> Run:
        for name in STEPS:
            step = self.run.step(name)
            if step.status is Status.DONE:
                continue
            step.start()
            self.run.save()
            self._log("started")
            try:
                step.finish(note=getattr(self, name)())
            except Escalation as reason:
                step.finish(Status.ESCALATED, str(reason))
                self.human.notify(f"{self.run.task.title}: escalated at {name}: {reason}")
            except Exception as error:
                step.finish(Status.FAILED, repr(error))
                raise
            finally:
                message = f"{step.status}: {step.note}" if step.note else str(step.status)
                self._log(message, LEVELS[step.status], step=name)
                self.run.save()
            if step.status is not Status.DONE:
                break
        return self.run

    # Steps. Each returns a short note for the timeline or raises Escalation.

    def prepare(self) -> str:
        if not self.run.workspace:
            self.run.workspace, self.run.branch, self.run.base = workspace.worktree(self.run.repo, self.run.id)
        hydration = [workspace.sh(command, self.run.workspace) for command in self.config.hydrate]
        self.run.write("prepare.md", checks.report(hydration, title="Hydration"))
        if not checks.passed(hydration):
            raise Escalation("hydration failed, see prepare.md")
        return f"{self.run.branch} at {self.run.workspace}"

    def plan(self) -> str:
        spec = self.crew.plan(self.run.task, feedback=self._guidance())
        if gaps := spec.gaps():
            self._log(f"spec {', '.join(gaps)}; asking for one revision", "warn")
            spec = self.crew.plan(self.run.task, feedback=f"The spec is not buildable yet: {', '.join(gaps)}.")
        self._save_spec(spec)
        if gaps := spec.gaps():
            raise Escalation(f"spec still {', '.join(gaps)}")
        while self.config.human.spec and (feedback := self.human.approve("spec", Kind.SPEC)):
            self._save_spec(self.crew.plan(self.run.task, feedback=feedback))
        return f"{self.spec.kind}, {self.spec.size}"

    def implement(self) -> str:
        return self._until_green(feedback=self._guidance())

    def review(self) -> str:
        if guidance := self._guidance():
            self._until_green(feedback=guidance)
        rounds = self.config.limits.review_rounds
        for attempt in range(rounds + 1):
            review = self._save_review(self.crew.review(self.spec, self._diff()))
            self._log(f"review: {review.verdict}: {review.summary}", "info" if review.approved else "warn")
            if review.approved or attempt == rounds:
                break
            self._until_green(feedback=review.to_markdown())
        if not checks.passed(results := self._check()):  # the reviewer may have edited code
            self._until_green(feedback=checks.feedback(results))
        return review.verdict

    def ship(self) -> str:
        if guidance := self._guidance():
            self._until_green(feedback=guidance)
        while self.config.human.code:
            self.run.write("diff.md", f"# Changes\n\n```diff\n{self._diff()}\n```\n")
            if not (feedback := self.human.approve("changes", Kind.CODE)):
                break
            self._until_green(feedback=feedback)
        if not workspace.commit(self.run.workspace, f"{self.spec.title}\n\nFactory run {self.run.id}"):
            raise Escalation("nothing to ship: the implementation changed no files")
        if self._can_open_pr():
            self._open_pr()
            note = self.run.pr_url
        else:
            note = f"branch {self.run.branch} is ready in {self.run.workspace}"
        self.run.write("ship.md", f"# Shipped\n\n{note}\n")
        return note

    def learn(self) -> str:
        text = self.crew.explain(self.run.task, self.spec, self._diff(), self.run.review)
        return str(self.run.write("learning.md", text))

    # Helpers

    def _until_green(self, feedback: str | None = None) -> str:
        """Implement, then check. Retry with the failures as feedback until checks pass or retries run out."""
        retries = self.config.limits.check_retries
        for attempt in range(retries + 1):
            self._log(f"implementing, attempt {attempt + 1} of {retries + 1}")
            self.run.write("implement.md", self.crew.implement(self.spec, feedback))
            if checks.passed(results := self._check()):
                return f"checks passed on attempt {attempt + 1}"
            self._log(f"{sum(not check.passed for check in results)} of {len(results)} checks failed", "warn")
            feedback = checks.feedback(results)
        raise Escalation(f"checks still failing after {retries} retries, see checks.md")

    def _guidance(self) -> str | None:
        """What a human said when resuming. Used once, by the first step that runs."""
        guidance, self.run.guidance = self.run.guidance, None
        if guidance:
            self._log(f"guidance from a human: {guidance}")
        return guidance

    def _log(self, message: str, level: str = "info", step: str | None = None) -> None:
        event = self.run.log(message, level, step)
        log.info("%-9s %s", event.step, message)

    def _check(self) -> list[Check]:
        results = checks.run_checks(checks.commands(self.config.checks, self.run.workspace), self.run.workspace)
        self.run.write("checks.md", checks.report(results))
        return results

    def _diff(self) -> str:
        return workspace.diff(self.run.workspace, self.run.base)

    def _save_spec(self, spec: Spec) -> None:
        self.run.spec = spec
        self.run.write("spec.md", spec.to_markdown())

    def _save_review(self, review: Review) -> Review:
        self.run.review = review
        self.run.write("review.md", review.to_markdown())
        return review

    def _can_open_pr(self) -> bool:
        return self.config.pull_request and bool(shutil.which("gh")) and bool(workspace.remote_url(self.run.workspace))

    def _open_pr(self) -> None:
        closes = f"\n\nCloses {self.run.task.url}" if self.run.task.source is Source.ISSUE else ""
        workspace.push(self.run.workspace, self.run.branch)
        self.run.pr_url = workspace.open_pr(self.run.workspace, self.spec.title, self.spec.to_markdown() + closes)
        workspace.comment(self.run.workspace, self.run.pr_url, self.run.review.to_markdown())
