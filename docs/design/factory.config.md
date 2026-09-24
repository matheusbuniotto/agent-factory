---
id: factory.config
title: Team configuration
version: 1
depends_on: []
provides: [Config, Endpoint, Models, Human, Limits, Dispatch]
generated_artifact: factory/config.py
status: accepted
---

# Configuration

## Purpose

This is the one place a team customises the factory: models, checks,
hydration, skills, human-in-the-loop points, and limits. It is read from
`<repo>/factory.toml`. If the file is missing, defaults apply.

## Example `factory.toml`

```toml
checks  = ["uv run ruff check .", "uv run pytest -q"]
hydrate = ["uv sync"]
skills  = ["skills", ".factory/skills"]
pull_request = true
runtime = "pydantic-ai"   # or "claude": Claude Agent SDK on your Claude subscription

# Any OpenAI-compatible API: vLLM, Ollama, LiteLLM, OpenRouter, Azure...
# Models refer to it as "<endpoint>:<model>".
[endpoints.local]
base_url    = "http://localhost:11434/v1"
api_key_env = "LOCAL_API_KEY"   # optional; the name of the env var, never the key

[models]
planner     = "anthropic:claude-opus-5-5"
implementer = "anthropic:claude-sonnet-5"
reviewer    = "anthropic:claude-opus-5-5"
scribe      = "anthropic:claude-haiku-4-5"

[human]          # all off = fully autonomous (default)
grill = false    # planner may ask the human questions
spec  = false    # human approves the spec before implementation
code  = false    # human approves the diff before ship
channel = "terminal"   # or "inbox": answer in the dashboard or with `factory answer`
wait_minutes = 30      # no answer by then: carry on as if approved / let the agent decide
webhook = ""           # optional; POSTed {"text", "run"} on every question and escalation (Slack compatible)

[limits]
check_retries = 2        # process.md step 5
review_rounds = 1        # process.md step 6
searches      = 8        # process.md step 2; 0 disables web search
compact_at    = 170_000  # tokens
requests      = 200      # model requests per agent call, a spend guard

[dispatch]       # where `factory submit`, POST /api/tasks and webhooks run a task
default   = "local"      # or "sqs"
trigger   = "factory"    # webhooks ignore tickets without this label
queue_url = ""           # the sqs lane; or $FACTORY_QUEUE_URL

[dispatch.labels]        # the first task label found here picks the lane
"factory:queue" = "sqs"
"factory:local" = "local"
```

## Semantic contract

- Unknown keys are errors (`extra="forbid"`), because a typo must not silently
  change behaviour.
- Relative `skills` paths resolve against the repo. The bundled `skills/`
  directory of the factory is always included first.
- A model string whose prefix names an endpoint becomes an OpenAI chat model at
  that `base_url`. Any other string goes to Pydantic AI unchanged (`anthropic:...`,
  `openai:...`). An endpoint named `openai` overrides the built-in prefix.
- If `api_key_env` is set but the variable is missing, building the crew raises
  `ValueError("endpoint 'local' needs $LOCAL_API_KEY")`.
- A planner on a custom endpoint gets no web search. Those servers have no native search tool.
- `runtime` picks the crew. `--runtime` or `$FACTORY_RUNTIME` overrides it for
  one run. The `claude` runtime only accepts Anthropic models (`anthropic:` or
  no prefix) and raises `ValueError` otherwise.
- CLI flags `--grill`, `--review-spec`, and `--review-code` switch human
  points on for one run.

## Must not infer

- Don't read environment variables for config. The exceptions are the API key an endpoint names in `api_key_env`
  and `$FACTORY_QUEUE_URL`, read by `factory.dispatch` when `queue_url` is empty.
- Never put API keys in `factory.toml`.
