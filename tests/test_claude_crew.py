"""The Claude Agent SDK crew, with Claude Code replaced by a script: no tokens spent."""

import asyncio
from pathlib import Path

import pytest
from claude_agent_sdk import AssistantMessage, ClaudeAgentOptions, ResultMessage, ToolUseBlock

from factory import claude_crew
from factory.claude_crew import ClaudeCrew
from factory.config import Config
from factory.contracts import Spec, Task
from factory.crew import PydanticCrew, hire
from factory.run import Usage


class FakeClaude:
    """Answers each query in turn and remembers what it was asked."""

    def __init__(self, *outputs: str | dict):
        self.outputs = list(outputs)
        self.calls: list[tuple[str, ClaudeAgentOptions]] = []

    async def __call__(self, prompt: str, options: ClaudeAgentOptions, turns: claude_crew._Turns) -> ResultMessage:
        self.calls.append((prompt, options))
        tool = ToolUseBlock(id="t", name="Read", input={"file_path": "calc.py"})
        turns.add(AssistantMessage(content=[tool], model="m", message_id="a", usage={"input_tokens": 10}))
        turns.add(AssistantMessage(content=[tool], model="m", message_id="a", usage={"input_tokens": 12}))
        turns.flush()
        output = self.outputs.pop(0)
        return ResultMessage(
            subtype="success",
            duration_ms=1,
            duration_api_ms=1,
            is_error=False,
            num_turns=1,
            session_id=f"session-{len(self.calls)}",
            result=output if isinstance(output, str) else None,
            structured_output=output if isinstance(output, dict) else None,
        )


def claude(
    repo: Path, monkeypatch: pytest.MonkeyPatch, *outputs: str | dict, **config
) -> tuple[ClaudeCrew, FakeClaude]:
    fake = FakeClaude(*outputs)
    monkeypatch.setattr(claude_crew, "_query", fake)
    return ClaudeCrew(Config.load(repo).model_copy(update=config), repo), fake


def test_claude_crew_produces_typed_outputs(repo: Path, spec: Spec, monkeypatch: pytest.MonkeyPatch):
    review = {"verdict": "approve", "summary": "fine"}
    crew, fake = claude(repo, monkeypatch, spec.model_dump(mode="json"), "done", "done", review, "eli5")
    crew.report = lambda *turn: turns.append(turn)
    turns = []

    planned = crew.plan(Task(title="t", body="b"))
    assert planned == spec
    assert crew.implement(planned) == "done"
    assert crew.implement(planned, feedback="tests fail") == "done"
    assert crew.review(planned, "diff").approved
    assert crew.explain(Task(title="t", body="b"), planned, "diff", None) == "eli5"

    (_, plan), (first, _), (second, again), (_, reviewer), (_, scribe) = fake.calls
    assert plan.model == "claude-opus-5-5" and plan.output_format["schema"] == Spec.model_json_schema()
    assert "Write" not in plan.tools and "Read" in plan.tools
    assert "Add subtract" in first and second == "tests fail" and again.resume == "session-2"
    assert "Edit" in reviewer.tools and reviewer.plugins
    assert scribe.tools == [] and scribe.model == "claude-haiku-4-5"
    assert all(options.env["ANTHROPIC_API_KEY"] == "" for _, options in fake.calls)
    assert [agent for agent, *_ in turns] == ["planner", "implementer", "implementer", "reviewer", "scribe"]
    assert turns[0][1:] == (["Read calc.py", "Read calc.py"], Usage(context=12, output=0))


def test_planner_revises_in_the_same_session(repo: Path, spec: Spec, monkeypatch: pytest.MonkeyPatch):
    output = spec.model_dump(mode="json")
    crew, fake = claude(repo, monkeypatch, output, output)
    crew.plan(Task(title="t", body="b"))
    crew.plan(Task(title="t", body="b"), feedback="missing acceptance")
    prompt, options = fake.calls[1]
    assert prompt == "Revise the spec:\n\nmissing acceptance" and options.resume == "session-1"


def test_grill_gives_the_planner_an_ask_human_tool(repo: Path, spec: Spec, monkeypatch: pytest.MonkeyPatch):
    config = Config.load(repo)
    config.human.grill = True
    crew, fake = claude(repo, monkeypatch, spec.model_dump(mode="json"), human=config.human)
    crew.plan(Task(title="t", body="b"))
    _, options = fake.calls[0]
    assert "factory" in options.mcp_servers and claude_crew.ASK_HUMAN in options.allowed_tools


def test_skills_are_exposed_as_a_plugin(repo: Path, monkeypatch: pytest.MonkeyPatch):
    crew, _ = claude(repo, monkeypatch)
    assert {path.name for path in (crew.plugin / "skills").iterdir()} >= {"software", "data", "ai"}


def test_web_search_stops_at_the_limit():
    hook = claude_crew._at_most(1)
    assert asyncio.run(hook({}, None, None)) == {}
    assert asyncio.run(hook({}, None, None))["hookSpecificOutput"]["permissionDecision"] == "deny"


def test_claude_runtime_refuses_other_providers(repo: Path):
    (repo / "factory.toml").write_text('[models]\nimplementer = "openai:gpt-5"\n')
    with pytest.raises(ValueError, match="only runs Anthropic models"):
        ClaudeCrew(Config.load(repo), repo)


def test_runtime_is_chosen_by_config(repo: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "unused")
    config = Config.load(repo)
    assert isinstance(hire(config, repo), PydanticCrew)
    assert isinstance(hire(config.model_copy(update={"runtime": "claude"}), repo), ClaudeCrew)
