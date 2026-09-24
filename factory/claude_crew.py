"""The same crew on the Claude Agent SDK: Claude Code does the work, billed to your Claude subscription,
or to AWS for `bedrock:` models."""

import asyncio
import shutil
import tempfile
import weakref
from collections.abc import Callable
from pathlib import Path
from typing import Any

from claude_agent_sdk import (
    AssistantMessage,
    ClaudeAgentOptions,
    ClaudeSDKClient,
    HookMatcher,
    ResultMessage,
    ToolUseBlock,
    create_sdk_mcp_server,
    tool,
)
from pydantic import BaseModel

from factory.config import Config
from factory.contracts import Review, Spec, Task
from factory.crew import ASSUME, GRILL, IMPLEMENTER, MAX_DIFF, PLANNER, REVIEWER, SCRIBE, Report, tool_label
from factory.human import terminal
from factory.run import Usage

READ = ["Read", "Glob", "Grep"]
CODE = [*READ, "Write", "Edit", "Bash"]
ASK_HUMAN = "mcp__factory__ask_human"
SUBSCRIPTION = {"ANTHROPIC_API_KEY": "", "ANTHROPIC_AUTH_TOKEN": ""}  # use the subscription login, not API keys
BEDROCK = {"CLAUDE_CODE_USE_BEDROCK": "1"}  # AWS credentials and region come from the environment


class ClaudeCrew:
    def __init__(
        self,
        config: Config,
        workspace: Path,
        ask: Callable[[str], str | None] = terminal,
        report: Report | None = None,
    ):
        self.config = config
        self.workspace = workspace
        self.ask = ask
        self.report = report
        self.models = {role: _claude_model(name) for role, name in config.models}
        self.plugin = _skills_plugin(config.skills)
        weakref.finalize(self, shutil.rmtree, self.plugin, ignore_errors=True)
        self._plan_session: str | None = None
        self._implement_session: str | None = None

    def plan(self, task: Task, feedback: str | None = None) -> Spec:
        if self._plan_session:
            prompt = f"Revise the spec:\n\n{feedback}"
        else:
            prompt = task.to_markdown() + (f"\n\n## Guidance from a human\n\n{feedback}" if feedback else "")
        result = self._run("planner", prompt, self._planner(), resume=self._plan_session)
        self._plan_session = result.session_id
        return _parse(Spec, result)

    def implement(self, spec: Spec, feedback: str | None = None) -> str:
        if self._implement_session:
            prompt = feedback or "Continue."
        else:  # a fresh conversation, e.g. after a resume, must see the spec
            prompt = spec.to_markdown() + (f"\n\n## Feedback\n\n{feedback}" if feedback else "")
        options = self._coder("implementer", IMPLEMENTER)
        result = self._run("implementer", prompt, options, resume=self._implement_session)
        self._implement_session = result.session_id
        return result.result or ""

    def review(self, spec: Spec, diff: str) -> Review:
        prompt = f"{spec.to_markdown()}\n\n# Diff\n\n```diff\n{diff[:MAX_DIFF]}\n```"
        options = self._coder("reviewer", REVIEWER, output_type=Review)
        return _parse(Review, self._run("reviewer", prompt, options))

    def explain(self, task: Task, spec: Spec, diff: str, review: Review | None) -> str:
        notes = review.to_markdown() if review else ""
        prompt = f"{task.to_markdown()}\n{spec.to_markdown()}\n{notes}\n```diff\n{diff[:MAX_DIFF]}\n```"
        return self._run("scribe", prompt, self._options("scribe", SCRIBE, tools=[])).result or ""

    def _planner(self) -> ClaudeAgentOptions:
        grill = self.config.human.grill
        searches = self.config.limits.searches
        options = self._options(
            "planner",
            PLANNER.format(align=GRILL if grill else ASSUME),
            tools=READ + (["WebSearch"] if searches else []),
            output_type=Spec,
        )
        if searches:
            options.hooks = {"PreToolUse": [HookMatcher(matcher="WebSearch", hooks=[_at_most(searches)])]}
        if grill:
            options.mcp_servers = {"factory": create_sdk_mcp_server("factory", tools=[self._ask_human_tool()])}
            options.allowed_tools.append(ASK_HUMAN)
        return options

    def _coder(self, role: str, instructions: str, output_type: type[BaseModel] | None = None) -> ClaudeAgentOptions:
        options = self._options(role, instructions, tools=CODE, output_type=output_type)
        options.tools = [*CODE, "Skill"]
        options.skills = "all"
        options.plugins = [{"type": "local", "path": str(self.plugin)}]
        return options

    def _options(
        self, role: str, instructions: str, tools: list[str], output_type: type[BaseModel] | None = None
    ) -> ClaudeAgentOptions:
        model, env = self.models[role]
        return ClaudeAgentOptions(
            model=model,
            system_prompt=instructions,
            cwd=self.workspace,
            tools=tools,
            allowed_tools=list(tools),
            permission_mode="dontAsk",  # anything not in `tools` is refused, nobody is prompted
            setting_sources=[],  # ignore the user's and the repo's Claude Code settings
            max_turns=self.config.limits.requests,
            output_format={"type": "json_schema", "schema": output_type.model_json_schema()} if output_type else None,
            env=env,
        )

    def _ask_human_tool(self):
        @tool("ask_human", "Ask the human one question about the task and get their answer.", {"question": str})
        async def ask_human(args: dict[str, Any]) -> dict[str, Any]:
            answer = await asyncio.to_thread(self.ask, args["question"])
            text = answer or "No answer. Make the safest reasonable choice and record it in `assumptions`."
            return {"content": [{"type": "text", "text": text}]}

        return ask_human

    def _run(self, agent: str, prompt: str, options: ClaudeAgentOptions, resume: str | None = None) -> ResultMessage:
        options.resume = resume
        turns = _Turns(lambda tools, usage: self.report and self.report(agent, tools, usage))
        return asyncio.run(_query(prompt, options, turns))


class _Turns:
    """Claude Code streams one message per content block; this joins them back into model turns and reports each."""

    def __init__(self, report: Callable[[list[str], Usage], None]):
        self.report = report
        self.id: str | None = None
        self.tools: list[str] = []
        self.usage: dict[str, Any] | None = None

    def add(self, message: AssistantMessage) -> None:
        if message.message_id is None or message.message_id != self.id:
            self.flush()
            self.id = message.message_id
        self.tools += [
            tool_label(block.name, block.input) for block in message.content if isinstance(block, ToolUseBlock)
        ]
        self.usage = message.usage or self.usage

    def flush(self) -> None:
        if self.usage:
            read = ("input_tokens", "cache_creation_input_tokens", "cache_read_input_tokens")
            context = sum(self.usage.get(key) or 0 for key in read)
            self.report(self.tools, Usage(context=context, output=self.usage.get("output_tokens") or 0))
        self.id, self.tools, self.usage = None, [], None


async def _query(prompt: str, options: ClaudeAgentOptions, turns: _Turns) -> ResultMessage:
    result = None
    async with ClaudeSDKClient(options) as client:
        await client.query(prompt)
        async for message in client.receive_response():
            if isinstance(message, AssistantMessage) and not message.parent_tool_use_id:
                turns.add(message)
            elif isinstance(message, ResultMessage):
                result = message
    turns.flush()
    if result is None or result.is_error:
        raise RuntimeError(f"Claude agent failed: {result and (result.errors or result.result or result.subtype)}")
    return result


def _parse[T: BaseModel](output_type: type[T], result: ResultMessage) -> T:
    if result.structured_output is None:
        raise RuntimeError(f"Claude agent returned no {output_type.__name__}: {result.result}")
    return output_type.model_validate(result.structured_output)


def _claude_model(name: str) -> tuple[str, dict[str, str]]:
    """The model id Claude Code expects, and the environment that picks its provider."""
    provider, _, model = name.partition(":") if ":" in name else ("", "", name)
    match provider:
        case "" | "anthropic":
            return model, SUBSCRIPTION
        case "bedrock":  # Bedrock ids contain colons too: bedrock:us.anthropic.claude-sonnet-4-5-20250929-v1:0
            return model, BEDROCK
    raise ValueError(f"the claude runtime only runs Anthropic models, on the subscription or Bedrock, not {name!r}")


def _at_most(limit: int):
    """A PreToolUse hook that refuses the tool once it has been used `limit` times."""
    uses = 0

    async def hook(input_data: dict[str, Any], tool_use_id: str | None, context: Any) -> dict[str, Any]:
        nonlocal uses
        uses += 1
        if uses <= limit:
            return {}
        return {
            "hookSpecificOutput": {
                "hookEventName": "PreToolUse",
                "permissionDecision": "deny",
                "permissionDecisionReason": f"Search limit of {limit} reached. Work with what you have.",
            }
        }

    return hook


def _skills_plugin(roots: list[Path]) -> Path:
    """A throwaway local plugin whose `skills/` links every skill in the configured skill folders."""
    plugin = Path(tempfile.mkdtemp(prefix="factory-skills-"))
    (plugin / ".claude-plugin").mkdir()
    (plugin / ".claude-plugin" / "plugin.json").write_text('{"name": "factory"}')
    skills = plugin / "skills"
    skills.mkdir()
    found = {path.parent.name: path.parent for root in roots for path in root.glob("*/SKILL.md")}  # later roots win
    for name, skill in found.items():
        (skills / name).symlink_to(skill.resolve(), target_is_directory=True)
    return plugin
