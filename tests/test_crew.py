"""The real agents, wired up, driven by TestModel: no tokens spent."""

from pathlib import Path

import pytest
from pydantic_ai.models.openai import OpenAIChatModel
from pydantic_ai.models.test import TestModel

from factory.config import Config, Limits
from factory.contracts import Spec, Task
from factory.crew import PydanticCrew


def test_crew_produces_typed_outputs(repo: Path, spec: Spec, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "unused")
    crew = PydanticCrew(Config.load(repo).model_copy(update={"limits": Limits(searches=0)}), repo)
    planner = TestModel(call_tools=[], custom_output_args=spec.model_dump(mode="json"))
    reviewer = TestModel(call_tools=[], custom_output_args={"verdict": "approve", "summary": "fine"})
    worker = TestModel(call_tools=[], custom_output_text="done")

    with (
        crew.planner.override(model=planner),
        crew.reviewer.override(model=reviewer),
        crew.implementer.override(model=worker),
        crew.scribe.override(model=worker),
    ):
        planned = crew.plan(Task(title="t", body="b"))
        assert planned == spec
        assert crew.implement(planned) == "done"
        assert crew.implement(planned, feedback="tests fail") == "done"
        assert crew.review(planned, "diff").approved
        assert crew.explain(Task(title="t", body="b"), planned, "diff", None) == "done"


def test_models_can_live_on_an_openai_compatible_endpoint(repo: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "unused")
    monkeypatch.setenv("LOCAL_KEY", "secret")
    (repo / "factory.toml").write_text(
        '[endpoints.local]\nbase_url = "http://localhost:8000/v1"\napi_key_env = "LOCAL_KEY"\n'
        '[models]\nimplementer = "local:qwen3-coder"\nplanner = "local:qwen3-coder"\n'
    )

    crew = PydanticCrew(Config.load(repo), repo)

    assert isinstance(crew.implementer.model, OpenAIChatModel)
    assert crew.implementer.model.model_name == "qwen3-coder"
    assert crew.implementer.model.base_url == "http://localhost:8000/v1/"
    assert crew.reviewer.model.model_name == "claude-opus-5-5"


def test_endpoint_without_its_key_fails_loudly(repo: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "unused")
    monkeypatch.delenv("LOCAL_KEY", raising=False)
    (repo / "factory.toml").write_text(
        '[endpoints.local]\nbase_url = "http://localhost:8000/v1"\napi_key_env = "LOCAL_KEY"\n'
        '[models]\nscribe = "local:small"\n'
    )
    with pytest.raises(ValueError, match=r"needs \$LOCAL_KEY"):
        PydanticCrew(Config.load(repo), repo)
