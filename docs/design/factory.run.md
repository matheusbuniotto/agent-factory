---
id: factory.run
title: Run state, checkpoints and artifacts
version: 1
depends_on: [factory.contracts]
provides: [Run, Step, Status, STEPS]
generated_artifact: factory/run.py
status: accepted
---

# Run state

## Purpose

A `Run` is the durable record of one task going through the factory. It
supports resuming and rewinding, and it keeps every step visible as a file.

## Semantic contract

- The run directory is `<repo>/.factory/runs/<id>/`.
- State lives in `run.json`, which `Run.load` reads back unchanged.
- `STEPS = ("prepare", "plan", "implement", "review", "ship", "learn")`.
- Each `Step` has a `status` in `pending | running | done | failed | escalated`
  and optional `started_at`, `finished_at`, and `note`.
- `run.status` is the status of the first step that is not `done`. It is
  `done` when every step is.
- `run.rewind(name)` resets `name` and every later step to `pending`.
- `run.write(name, text)` writes an artifact (`spec.md`, `checks.md`, ...)
  and returns its path.
- `<repo>/.factory/.gitignore` contains `*`, so the factory never dirties
  the target repo.

## Ids

The id is `<YYYYmmdd-HHMMSS>-<slug of task title, ≤ 40 chars>-<4 hex chars>`, for example
`20260923-101500-add-subtract-3f9a`. The random suffix keeps parallel runs of the
same task apart.

## Worked example: rewind

```yaml
before: {prepare: done, plan: done, implement: done, review: failed}
call:   rewind("implement")
after:  {prepare: done, plan: done, implement: pending, review: pending, ship: pending, learn: pending}
```

## Must not infer

- Don't delete artifacts on rewind. They are overwritten when the step runs again.
- Don't store secrets or model message histories in `run.json`.

## Reconciliation anchor

```python
run = Run.start(task, repo=tmp)
run.save()
assert Run.load(tmp, run.id) == run
assert (tmp / ".factory/.gitignore").read_text() == "*\n"
```
