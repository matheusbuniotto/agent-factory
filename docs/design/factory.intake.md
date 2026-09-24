---
id: factory.intake
title: Intake
version: 1
depends_on: [factory.contracts]
provides: [intake]
generated_artifact: factory/intake.py
status: accepted
---

# Intake (step 0)

## Purpose

Turn whatever the human typed into a `Task`.

## Semantic contract

`intake(source: str) -> Task`. The rules are tried in order:

1. **Issue**: `source` is `#<n>` or matches `https://github.com/<o>/<r>/issues/<n>`.
   → `gh issue view <source> --json title,body,url`, `source=issue`, `url` set.
2. **File**: `Path(source)` is an existing file.
   → body = the file contents, title = the first `# ` heading or the file stem,
   `source=file`, `url` = the path.
3. **Text**: anything else.
   → body = `source`, title = the first line without a leading `# `, cut to 72
   characters, `source=text`.

Tickets from Linear and Jira arrive as webhooks, not through `intake`; see
[factory.dispatch](factory.dispatch.md).

## Worked examples

```yaml
- in: "Add a subtract function\nwith tests"
  out: {title: "Add a subtract function", source: text}
- in: "docs/task.md"            # contains "# Fix login\n..."
  out: {title: "Fix login", source: file, url: "docs/task.md"}
- in: "#42"
  out: {source: issue, title: <from gh>, url: <from gh>}
```

## Errors

- The `gh` command fails → `RuntimeError` with gh's stderr.
- Empty source → `ValueError("empty task")`.

## Must not infer

- Don't fetch links found inside the text. Hydration belongs to the planner's research.
