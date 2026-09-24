"""The agents. Every LLM call in the factory goes through here."""

import os
from collections.abc import Callable
from pathlib import Path

from pydantic_ai import Agent, UsageLimits
from pydantic_ai.capabilities import WebSearch
from pydantic_ai.messages import ModelMessage
from pydantic_ai.models import Model
from pydantic_ai.models.openai import OpenAIChatModel
from pydantic_ai.providers.openai import OpenAIProvider
from pydantic_ai_harness import Coder, FileSystem, Skills, SummarizingCompaction

from factory.config import Config, Endpoint
from factory.contracts import Review, Spec, Task
from factory.human import terminal

MAX_DIFF = 100_000

PLANNER = """\
You are the planner of an autonomous coding factory. Turn the task into a spec
that another agent can build from without asking anything.

1. Understand: read the repository to learn its stack, layout and conventions.
2. Classify: `kind` is software, data (dbt, SQL, pipelines) or ai (ML, LLM apps);
   `size` is simple for a small, obvious change, standard otherwise.
3. Align: {align}
4. Research: search the web only when the repo does not answer a question about
   an API, library version or best practice. Cite what you use in `sources`.
5. Specify: write BDD scenarios (Given/When/Then), exact worked examples
   (at least one success and one failure for standard tasks), the public interface,
   invariants, what must not be inferred, and acceptance: exact commands or
   assertions that prove the work is done.

No adjectives without a test behind them. Keep simple specs short."""

GRILL = "ask the human about any decision you cannot safely make, one question at a time."
ASSUME = "no human is available; make the safest reasonable choice and record it in `assumptions`."

IMPLEMENTER = """\
You implement a spec in this repository. The spec is the source of truth: build
exactly what it says, follow its must-not-infer list, and make its acceptance pass.
Load a skill when it matches the task. Follow the repository's conventions.
Write readable, idiomatic code. Add or update tests.
Never weaken or delete checks or tests to make them pass.
Do not commit, push or touch `.factory/`: the factory does that."""

REVIEWER = """\
You review a diff against its spec, like a senior engineer on a pull request.
Check that it meets the intent, the scenarios and the acceptance, respects
must-not-infer, and follows the language's best practices.
You may fix small things yourself (typos, naming, a missed edge case; under ~20
lines). Request changes only for real defects, never for taste; give file:line."""

SCRIBE = """\
Explain what was done and why to a teammate who has never seen this code, as if
they were five. Plain words, short sentences, under 300 words, markdown.
Cover: the problem, what changed, how to try it, and anything to watch out for."""


class Crew:
    def __init__(self, config: Config, workspace: Path, ask: Callable[[str], str | None] = terminal):
        self.config = config
        self.ask = ask
        self.limits = UsageLimits(request_limit=config.limits.requests)
        self.planner = self._planner(workspace)
        self.implementer = self._implementer(workspace)
        self.reviewer = self._reviewer(workspace)
        self.scribe = Agent(self._model(config.models.scribe), instructions=SCRIBE)
        self._plan_history: list[ModelMessage] = []
        self._implement_history: list[ModelMessage] = []

    def plan(self, task: Task, feedback: str | None = None) -> Spec:
        if self._plan_history:
            prompt = f"Revise the spec:\n\n{feedback}"
        else:
            prompt = task.to_markdown() + (f"\n\n## Guidance from a human\n\n{feedback}" if feedback else "")
        result = self.planner.run_sync(prompt, message_history=self._plan_history, usage_limits=self.limits)
        self._plan_history = result.all_messages()
        return result.output

    def implement(self, spec: Spec, feedback: str | None = None) -> str:
        if self._implement_history:
            prompt = feedback or "Continue."
        else:  # a fresh conversation, e.g. after a resume, must see the spec
            prompt = spec.to_markdown() + (f"\n\n## Feedback\n\n{feedback}" if feedback else "")
        result = self.implementer.run_sync(prompt, message_history=self._implement_history, usage_limits=self.limits)
        self._implement_history = result.all_messages()
        return result.output

    def review(self, spec: Spec, diff: str) -> Review:
        prompt = f"{spec.to_markdown()}\n\n# Diff\n\n```diff\n{diff[:MAX_DIFF]}\n```"
        return self.reviewer.run_sync(prompt, usage_limits=self.limits).output

    def explain(self, task: Task, spec: Spec, diff: str, review: Review | None) -> str:
        notes = review.to_markdown() if review else ""
        prompt = f"{task.to_markdown()}\n{spec.to_markdown()}\n{notes}\n```diff\n{diff[:MAX_DIFF]}\n```"
        return self.scribe.run_sync(prompt, usage_limits=self.limits).output

    def _model(self, name: str) -> Model | str:
        endpoint_name, _, model_name = name.partition(":")
        if endpoint := self.config.endpoints.get(endpoint_name):
            return OpenAIChatModel(model_name, provider=_provider(endpoint_name, endpoint))
        return name

    def _planner(self, workspace: Path) -> Agent[None, Spec]:
        grill = self.config.human.grill
        model = self._model(self.config.models.planner)

        def ask_human(question: str) -> str:
            """Ask the human one question about the task and get their answer."""
            return self.ask(question) or "No answer. Make the safest reasonable choice and record it in `assumptions`."

        capabilities = [FileSystem(root_dir=workspace, read_only=True)]
        if self.config.limits.searches and isinstance(model, str):  # custom endpoints have no native search
            capabilities.append(WebSearch(max_uses=self.config.limits.searches))
        return Agent(
            model,
            output_type=Spec,
            instructions=PLANNER.format(align=GRILL if grill else ASSUME),
            tools=[ask_human] if grill else [],
            capabilities=capabilities,
        )

    def _implementer(self, workspace: Path) -> Agent[None, str]:
        return Agent(
            self._model(self.config.models.implementer),
            instructions=IMPLEMENTER,
            capabilities=[
                Coder(workspace),
                Skills(self.config.skills),
                SummarizingCompaction(max_tokens=self.config.limits.compact_at),
            ],
        )

    def _reviewer(self, workspace: Path) -> Agent[None, Review]:
        return Agent(
            self._model(self.config.models.reviewer),
            output_type=Review,
            instructions=REVIEWER,
            capabilities=[Coder(workspace), Skills(self.config.skills)],
        )


def _provider(name: str, endpoint: Endpoint) -> OpenAIProvider:
    if endpoint.api_key_env and endpoint.api_key_env not in os.environ:
        raise ValueError(f"endpoint {name!r} needs ${endpoint.api_key_env}")
    api_key = os.environ[endpoint.api_key_env] if endpoint.api_key_env else None
    return OpenAIProvider(base_url=endpoint.base_url, api_key=api_key)
