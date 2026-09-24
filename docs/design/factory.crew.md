---
id: factory.crew
title: The agents
version: 1
depends_on: [factory.contracts, factory.config, factory.run]
provides: [Crew]
generated_artifact: factory/crew.py
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

## Public interface

```python
class Crew:
    def __init__(self, config: Config, workspace: Path): ...
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

## Must not infer

- The implementer must not read `.factory/`, push, or open PRs. `ship` does that.
- The reviewer must not rewrite the implementation. Its edits stay under about 20 lines.
- No agent may weaken or delete tests to pass checks.
