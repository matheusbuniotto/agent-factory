---
id: factory.pipeline
title: The blueprint
version: 1
depends_on: [factory.contracts, factory.config, factory.run, factory.workspace, factory.checks, factory.crew]
provides: [Pipeline, Escalation]
generated_artifact: factory/pipeline.py
status: accepted
---

# Pipeline

## Purpose

Run the steps in order and interleave deterministic nodes with agent nodes.
Enforce the retry limits and escalate to a human when the limits run out.

## Semantic contract

`Pipeline(run, config, crew=None).execute() -> Run` runs each step in
`STEPS` whose status is not `done`. It marks the step `running`, saves,
runs, then marks it `done` and saves.

| Step | Behaviour | Artifacts |
|---|---|---|
| prepare | create worktree, run `hydrate` commands (any failure → escalate) | `prepare.md` |
| plan | `crew.plan(task)`. If `spec.gaps()`, one revision with the gaps as feedback. Still gaps → escalate. If `human.spec`, the human approves or gives feedback (one revision per round). | `spec.md` |
| implement | `crew.implement(spec)`, then checks. On failure, feedback and retry up to `check_retries` times. Still failing → escalate. | `checks.md`, `implement.md` |
| review | `crew.review(spec, diff)`. If `request_changes` and `review_rounds` remain: implement with the comments as feedback (same check loop), then review again. The last review is kept and shipped even if it still requests changes, so the PR shows it. Checks run once more at the end because the reviewer may have edited code. | `review.md` |
| ship | if `human.code`, the human approves the diff. Commit. If `pull_request` and origin exists: push, open PR, post review as a PR comment. Otherwise note the worktree path. | `ship.md` |
| learn | `crew.explain(...)` | `learning.md` |

`Escalation` sets the step to `escalated` with the reason as its note,
saves, and stops the run. Any other exception sets `failed` and re-raises.

## Worked example: checks never pass

```yaml
check_retries: 2
checks: ["false"]
trace:
  - implement(spec)            # attempt 1
  - checks fail
  - implement(spec, feedback)  # retry 1
  - checks fail
  - implement(spec, feedback)  # retry 2
  - checks fail
result: {implement: escalated, review: pending}
```

## Worked example: resume

```yaml
before: {prepare: done, plan: done, implement: escalated}
execute() -> runs implement, review, ship, learn only
```

## Must not infer

- Never run a step after an escalated or failed one within the same `execute`.
- Never spend more than 1 + `check_retries` implement calls per check loop.
