---
id: factory.checks
title: Deterministic checks
version: 1
depends_on: [factory.contracts, factory.workspace]
provides: [commands, run_checks, feedback, report]
generated_artifact: factory/checks.py
status: accepted
---

# Checks (step 5)

## Purpose

Run the team's linters, tests, and pre-commit hooks in the worktree, then
turn failures into feedback written like a GitHub review.

## Semantic contract

- `commands(configured, workspace)` returns the configured commands. If none
  are configured and `.pre-commit-config.yaml` exists, it returns
  `["pre-commit run --all-files"]`. Otherwise it returns `[]`.
- `run_checks(commands, workspace)` stages all files (`git add -A`, so
  pre-commit sees new files) and then runs every command, even after a
  failure. The agent gets all feedback at once.
- `feedback(checks)` returns one markdown message listing only failed
  commands, each with the last 4000 characters of output.
- `report(checks)` returns the markdown artifact `checks.md`.
- No commands means the checks pass.

## Worked example: failure feedback

```markdown
The following checks failed. Fix them without weakening the checks.

### `uv run pytest -q`
```
FAILED tests/test_calc.py::test_subtract - assert 1 == -1
```
```

## Must not infer

- Don't skip, disable, or edit checks to make them pass.
- Don't retry here. The pipeline owns retries.
