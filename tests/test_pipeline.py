"""The blueprint end to end, on a real git repo, with a scripted crew."""

import subprocess
from pathlib import Path

from factory.config import Config
from factory.contracts import Review, Spec, Task
from factory.pipeline import Pipeline
from factory.run import Run, Status


class FakeCrew:
    def __init__(self, spec: Spec, reviews: list[Review] | None = None):
        self.spec = spec
        self.reviews = reviews or [Review(verdict="approve", summary="good")]
        self.workspace: Path | None = None
        self.calls: list[str] = []

    def plan(self, task, feedback=None):
        self.calls.append("plan")
        return self.spec

    def implement(self, spec, feedback=None):
        self.calls.append("implement")
        (self.workspace / "calc.py").write_text("def subtract(a, b):\n    return a - b\n")
        return "added subtract"

    def review(self, spec, diff):
        self.calls.append("review")
        assert "+def subtract" in diff
        return self.reviews.pop(0)

    def explain(self, task, spec, diff, review):
        self.calls.append("explain")
        return "# What happened\n\nWe taught calc to subtract.\n"


def factory(repo: Path, crew: FakeCrew, **config) -> Pipeline:
    run = Run.start(Task(title="Add subtract", body="..."), repo)
    pipeline = Pipeline(run, Config(pull_request=False, **config), crew=crew)
    original = pipeline.prepare

    def prepare():  # the crew edits the worktree once it exists
        note = original()
        crew.workspace = run.workspace
        return note

    pipeline.prepare = prepare
    return pipeline


def test_happy_path_ships_a_branch(repo: Path, spec: Spec):
    crew = FakeCrew(spec)
    run = factory(repo, crew, checks=spec.acceptance).execute()

    assert run.status is Status.DONE
    assert crew.calls == ["plan", "implement", "review", "explain"]
    log = subprocess.run(["git", "log", "--oneline", run.branch], cwd=repo, capture_output=True, text=True)
    assert "Add subtract" in log.stdout
    assert {"spec.md", "checks.md", "review.md", "ship.md", "learning.md"} <= {p.name for p in run.dir.iterdir()}


def test_checks_that_never_pass_escalate_after_two_retries(repo: Path, spec: Spec):
    crew = FakeCrew(spec)
    run = factory(repo, crew, checks=["false"]).execute()

    assert run.step("implement").status is Status.ESCALATED
    assert run.step("review").status is Status.PENDING
    assert crew.calls.count("implement") == 3


def test_requested_changes_get_one_rework_round(repo: Path, spec: Spec):
    reviews = [Review(verdict="request_changes", summary="missing test"), Review(verdict="approve", summary="ok")]
    crew = FakeCrew(spec, reviews)
    run = factory(repo, crew).execute()

    assert run.status is Status.DONE
    assert crew.calls == ["plan", "implement", "review", "implement", "review", "explain"]


def test_incomplete_spec_is_revised_once_then_escalated(repo: Path, spec: Spec):
    crew = FakeCrew(spec.model_copy(update={"acceptance": []}))
    run = factory(repo, crew).execute()

    assert crew.calls == ["plan", "plan"]
    assert run.step("plan").status is Status.ESCALATED
    assert run.step("plan").note == "spec still missing acceptance"


def test_resume_skips_finished_steps(repo: Path, spec: Spec):
    crew = FakeCrew(spec)
    pipeline = factory(repo, crew, checks=["false"])
    run = pipeline.execute()
    crew.calls.clear()

    pipeline.config.checks = []
    run.rewind("implement")
    pipeline.execute()

    assert crew.calls == ["implement", "review", "explain"]
    assert run.status is Status.DONE


def test_every_step_leaves_a_trail_in_the_event_log(repo: Path, spec: Spec):
    run = factory(repo, FakeCrew(spec), checks=["false"]).execute()

    events = run.events()
    assert events[0].step == "prepare" and events[0].message == "started"
    assert all(event.step for event in events)
    assert [e.level for e in events if e.step == "implement"].count("warn") == 4  # 3 failed checks + escalation


def test_parallel_runs_of_the_same_task_do_not_collide(repo: Path, spec: Spec):
    first, second = (factory(repo, FakeCrew(spec)).execute() for _ in range(2))
    assert first.id != second.id and first.status is second.status is Status.DONE


def test_guidance_reaches_the_implementer_once_on_resume(repo: Path, spec: Spec):
    crew = FakeCrew(spec)
    feedback = []
    implement = crew.implement
    crew.implement = lambda spec, fb=None: feedback.append(fb) or implement(spec, fb)
    pipeline = factory(repo, crew, checks=["false"])
    run = pipeline.execute()

    feedback.clear()
    pipeline.config.checks = []
    run.rewind("implement")
    run.guidance = "the fixture needs a unique order_id"
    pipeline.execute()

    assert feedback == ["the fixture needs a unique order_id"]
    assert run.guidance is None
    assert "guidance from a human: the fixture needs a unique order_id" in [e.message for e in run.events()]
