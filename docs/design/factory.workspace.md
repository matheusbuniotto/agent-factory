---
id: factory.workspace
title: Workspace and git
version: 1
depends_on: [factory.contracts]
provides: [sh, call, worktree, diff, commit, remote_url, push, open_pr, comment]
generated_artifact: factory/workspace.py
status: accepted
---

# Workspace (steps 1.1, 7, 8)

## Purpose

This module owns every deterministic git and subprocess operation, so that
agents never have to perform one to finish a run.

## Semantic contract

| Function | Behaviour |
|---|---|
| `sh(command, cwd) -> Check` | runs a shell string, merges stdout and stderr, never raises |
| `call(*args, cwd, input=None) -> str` | runs git or gh without a shell, returns stdout, raises on failure |
| `worktree(repo, run_id) -> (path, branch, base)` | `git worktree add -b factory/<id> .factory/worktrees/<id> HEAD`; `base` = HEAD sha |
| `diff(workspace, base) -> str` | `git add -A` then `git diff --cached <base>`, so new files are included |
| `commit(workspace, message) -> bool` | `git add -A && git commit`; `False` if nothing changed |
| `remote_url(workspace) -> str \| None` | url of `origin`, or `None` |
| `push(workspace, branch)` | `git push -u origin <branch>` |
| `open_pr(workspace, title, body) -> str` | `gh pr create --title --body`, returns the PR url |
| `comment(workspace, pr_url, body)` | `gh pr comment <url> --body-file -` |

Failing git or gh commands raise `RuntimeError` with their output.

## Worked example

```yaml
repo HEAD: abc123
worktree(repo, "20260923-add") ->
  path:   repo/.factory/worktrees/20260923-add
  branch: factory/20260923-add
  base:   abc123
```

## Must not infer

- Don't install git hooks. They would leak into the main repo's `.git/hooks`.
- Don't force-push, rebase, or touch any branch other than `factory/<id>`.
- Don't remove worktrees. Humans do that after review (`git worktree remove`).
