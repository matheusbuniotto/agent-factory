---
id: factory.crew
title: The agents
version: 1
depends_on: [factory.contracts, factory.config, factory.run]
provides: [Crew]
generated_artifact: [factory/crew.py, factory/claude_crew.py]
status: accepted
---

# Crew: planner, implementer, reviewer, scribe

## Purpose

This module owns every LLM call. Each agent has one job, its own model, and
only the capabilities that job needs.

## Agents

| Agent       | Steps | Output   | Capabilities |
|-------------|-------|----------|--------------|
| planner     | 1-3   | `Spec`   | read-only `FileSystem(workspace)`, `WebSearch(max_uses=limits.searches)` (only if > 0), `ask_human` tool (only if `human.grill`) |
| implementer | 4     | `str` summary | `Coder(workspace)`, `Skills(config.skills)`, `SummarizingCompaction(max_tokens=limits.compact_at)` |
| reviewer    | 6     | `Review` | `Coder(workspace)` (small fixes only), `Skills(config.skills)` |
| scribe      | 9     | `str` markdown | none |

## Runtimes

`hire(config, workspace, ask)` returns the crew for `config.runtime`. Both
behave the same; only the engine differs.

| Runtime       | Class          | Engine | Billing |
|---------------|----------------|--------|---------|
| `pydantic-ai` | `PydanticCrew` | Pydantic AI + harness capabilities (above) | API keys |
| `claude`      | `ClaudeCrew`   | Claude Agent SDK (Claude Code) | Claude subscription login (`ANTHROPIC_API_KEY` is blanked), or AWS for `bedrock:` models (`CLAUDE_CODE_USE_BEDROCK=1`) |

`ClaudeCrew` maps each capability to Claude Code:

- read-only `FileSystem` → tools `Read`, `Glob`, `Grep`; `Coder` → plus `Write`, `Edit`, `Bash`.
- `WebSearch(max_uses)` → `WebSearch` with a `PreToolUse` hook that denies it past the limit.
- `ask_human` → an in-process MCP tool `mcp__factory__ask_human`.
- `Skills` → a temporary local plugin linking every `<root>/<name>/SKILL.md` folder, plus the `Skill` tool.
- `SummarizingCompaction` → Claude Code's own auto-compaction.
- typed output → `output_format` JSON schema, validated with the Pydantic model.
- message history → session `resume`.
- `UsageLimits(request_limit)` → `max_turns`.

Every agent runs with `permission_mode="dontAsk"` and `setting_sources=[]`:
only its listed tools, and none of the user's or repo's Claude Code settings.

## Public interface

```python
class Crew(Protocol):
    def plan(self, task: Task, feedback: str | None = None) -> Spec: ...
    def implement(self, spec: Spec, feedback: str | None = None) -> str: ...
    def review(self, spec: Spec, diff: str) -> Review: ...
    def explain(self, task: Task, spec: Spec, diff: str, review: Review | None) -> str: ...
```

## Semantic contract

- `plan` classifies the task (`kind`, `size`) and writes BDD scenarios and
  a design doc in the shape of `design-framework.md`. In autonomous mode it
  records its guesses in `assumptions` instead of asking. With `feedback`
  (spec gaps or human notes) it revises the previous spec in the same
  conversation.
- `implement` keeps its message history across calls on the same `Crew`, so
  check feedback lands like a review on the same PR.
- `review` compares the diff against the spec's intent, scenarios,
  acceptance, and must-not-infer list, plus language best practice. It
  returns `request_changes` only for defects, not style preferences.
- `explain` writes an ELI5 "what was done and why" for onboarding in
  under 300 words.

## Telemetry

Both crews take `report(agent, tools, usage)` and call it after every model
turn with one-line tool labels (`Read src/app.py`) and `Usage(context, output)`
tokens. The pipeline logs each turn as a `debug` event with `agent`, `tools`
and `usage`; the dashboard draws context and cumulative tokens per agent from
them, and `/api/runs` sums them per agent in `usage`.

## Must not infer

- The implementer must not read `.factory/`, push, or open PRs. `ship` does that.
- The reviewer must not rewrite the implementation. Its edits stay under about 20 lines.
- No agent may weaken or delete tests to pass checks.
