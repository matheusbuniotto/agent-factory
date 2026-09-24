---
id: factory.dispatch
title: Dispatch, webhooks and the REST intake
version: 1
depends_on: [factory.contracts, factory.config, factory.intake, factory.run]
provides: [dispatch, launch, work, hooks.github, hooks.linear, hooks.jira]
generated_artifact: factory/dispatch.py, factory/hooks.py
status: accepted
---

# Dispatch

## Purpose

Take a task from anywhere (CLI, REST, a GitHub, Linear or Jira webhook) and
start it in a lane: a background process on this machine (`local`) or an SQS
queue that `factory worker` consumes (`sqs`). `factory run` is unchanged: it
still runs in the foreground.

```text
factory submit ─┐
POST /api/tasks ├─► Task(labels) ─► lane ─┬─ local ─► factory resume <id> --inbox (background)
POST /api/hooks ┘                         └─ sqs ───► SQS ─► factory worker ─► Pipeline
```

## Semantic contract

- `Dispatch.lane(labels)`: the first label that is a key of `dispatch.labels`
  picks the lane. Otherwise it's `dispatch.default`.
- `dispatch(task, repo, config) -> (lane, id)`:
  - local: `Run.start`, save, `launch(run)`. The id is the run id.
  - sqs: send `Task` JSON to the queue. The id is the SQS message id.
- `launch(run, step?, guidance?)` runs `factory resume <id> --inbox` in a
  detached process and appends its output to `resume.log`. The dashboard's
  resume uses it as well.
- `work(repo, config)` long-polls the queue and runs one task at a time with
  `human.channel = "inbox"`. A message is deleted as soon as it is received, so
  delivery is at most once. A failed run stays in `.factory/runs` and can be resumed.
- The queue URL is `dispatch.queue_url`, else `$FACTORY_QUEUE_URL`, else
  `ValueError`. Without `boto3` installed, the sqs lane raises `RuntimeError`
  (`pip install 'agent-factory[aws]'`).

## Webhooks (`factory.hooks`)

`PARSERS[provider](payload, trigger) -> Task | None`. A ticket starts a run
when it is **created with the trigger label** or when **the trigger label is
added**. Every other event returns `None`.

Each parser reads the payload into `labels`, `created` and `before` (the labels
before this event, `None` if it didn't change labels). One rule then decides for
all providers, and its properties are proved in [proofs/Factory.lean](../../proofs/Factory.lean):

```python
starts = trigger in labels and (created or (before is not None and trigger not in before))
```

| Provider | `created`                          | `before`                                        | Task.url              |
|----------|------------------------------------|-------------------------------------------------|-----------------------|
| github   | `action=opened`                    | on `labeled`: the labels without `label.name`   | `issue.html_url`      |
| linear   | `action=create` (`type=Issue`)     | the names of `updatedFrom.labelIds`             | `url`                 |
| jira     | `jira:issue_created`               | the `labels` changelog item's `fromString`      | `<site>/browse/<key>` |

Pull requests (`issue.pull_request`) are never tasks.

## REST

| Route                                 | Auth                      | Body                              | Reply |
|---------------------------------------|---------------------------|-----------------------------------|-------|
| `POST /api/tasks`                     | `X-Factory` header        | `{"task": "<text, md, #42>", "labels": [...]}` | 202 `{lane, id, title}`, 400 if invalid |
| `POST /api/hooks/{github,linear,jira}` | `?token=$FACTORY_TOKEN`  | the provider's webhook payload    | 202 `{lane, id, title}` or 200 `{ignored}` |

- Webhooks are off (403) while `FACTORY_TOKEN` is unset. The token is compared in constant time.
- A lane that can't be reached (no queue URL, no boto3) returns 503 with the reason.

## Worked examples

```yaml
- labels: ["bug", "factory:queue"]
  config: {labels: {"factory:queue": sqs}}
  lane: sqs
- in: {provider: github, action: labeled, label: {name: factory}}
  out: Task(source=issue)
- in: {provider: github, action: labeled, label: {name: bug}}
  out: ignored
- in: {provider: linear, action: update, updatedFrom: {title: "old"}}
  out: ignored           # an edit, not a label change
```

## Must not infer

- Don't check payload signatures per provider. The shared token covers all three.
- Don't deduplicate runs. The trigger rules already stop edits from starting a run again.
- Don't clone repositories named in a payload. A worker serves one `--repo`.
