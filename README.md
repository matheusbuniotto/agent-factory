# Agent Factory

Task in, reviewed pull request out. The factory is autonomous by default, and
flags turn on human checkpoints.

```text
intake → prepare → plan → implement ⇄ checks → review → ship → learn
```

Only four steps use an LLM (planner, implementer, reviewer, scribe). Git,
checks, retries, and PRs are plain Python. See [docs/overview.md](docs/overview.md)
for the design and [docs/design/](docs/design) for one spec per module.

## Use

```bash
uv sync
export ANTHROPIC_API_KEY=...

factory run "Add a --json flag to the export command"   # text
factory run docs/task.md                                # markdown file
factory run '#42'                                       # GitHub issue
factory run '#42' --grill --review-spec --review-code   # semi-autonomous

factory show                     # list runs
factory show <run-id>            # timeline + artifacts
factory resume <run-id>          # continue after an escalation
factory resume <run-id> --from implement   # rewind
factory resume <run-id> --guidance "the fixture needs unique ids"

factory run '#42' --review-spec --inbox    # wait for answers in the dashboard
factory inbox                    # questions and approvals waiting on you
factory answer <run-id> <question-id> "only v2"   # or leave the text out to approve
factory ui                       # dashboard at http://127.0.0.1:8765/control
```

### On a Claude subscription

Run the same crew on the Claude Agent SDK instead of Pydantic AI. It uses your
Claude Code login (`claude login`), not an API key:

```bash
factory run "Fix the flaky test" --runtime claude   # one run
export FACTORY_RUNTIME=claude                        # every run
```

Or set `runtime = "claude"` in `factory.toml`. Only Anthropic models work there.

The dashboard's **Runs** view shows each run's waterfall, live activity and
artifacts. **Fleet** shows every run on one clock and where the time goes. The
**Inbox** (`i`) collects every question, approval and escalation. You can answer
there, or resume an escalated run with guidance. Turn on **Alerts** for desktop
notifications, or set `human.webhook` to get them in Slack.

Each run lives in `<repo>/.factory/runs/<id>/` (`run.json`, `task.md`,
`spec.md`, `checks.md`, `review.md`, `learning.md`). The code lives in the
git worktree `<repo>/.factory/worktrees/<id>` on branch `factory/<id>`.
With `pip install '.[logfire]'` and `LOGFIRE_TOKEN` set, every agent call is
traced in the Logfire UI.

## Customise

Add a `factory.toml` to the target repo (see
[docs/design/factory.config.md](docs/design/factory.config.md)) and your own
skills as `skills/<name>/SKILL.md`. The bundled skills are `software`, `data`, and `ai`.

Local or self-hosted models work through any OpenAI-compatible endpoint:

```toml
[endpoints.local]
base_url = "http://localhost:11434/v1"   # Ollama, vLLM, LiteLLM, OpenRouter...
api_key_env = "LOCAL_API_KEY"            # optional

[models]
implementer = "local:qwen3-coder"
```

## Docker (local, ECS, EC2)

```bash
docker build -t agent-factory .
cp .env.example .env   # fill in your keys
docker run --rm --env-file .env -v "$PWD:/work" agent-factory run "Fix the flaky test"
```

On ECS, run the same image as a task. Put the keys in Secrets Manager and
clone the repo as the command (`sh -c "git clone $REPO /work && factory run ..."`).

## Develop

```bash
uv run pytest            # no tokens spent
uv run ruff check .
uv run python evals/run.py   # real models, cheap: see evals/cases.json
```
