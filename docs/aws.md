# Running the factory on AWS

Jira in, reviewed pull request out, inside a closed VPC. Cheap when idle,
and safe even if an agent is prompt-injected by a ticket.

Everything here is built in [`infra/`](../infra): a Terraform module, the two
Lambdas, and a local copy of the whole stack on [floci](https://floci.io).
See [Deploy](#deploy), or the [quick guide](../infra/README.md).

```text
Jira ticket (label "factory" or status "Ready for agent")
  → poller Lambda (every 1–2 min, JQL search)
  → ECS Fargate Spot task per ticket: `factory-ticket` (clone, then `factory run <ticket JSON>`)
      → plan → implement → review → push branch → open PR "PROJ-123 …"
      → the outcome goes to an SQS results queue
  → notify Lambda: Jira comment (PR link, learning.md), move to "In Review"
  → a human reviews the PR in GitHub
```

GitHub is only used for the branch and the PR. There are no GitHub issues.

## Models

Use Claude on Amazon Bedrock. Access is controlled by IAM, there are no API keys
to leak, and billing goes to the AWS account.

Do not use the `claude` subscription runtime here. A subscription is meant for
one person working interactively, not for an unattended team bot; check
Anthropic's current terms. Keep it for local use.

Both runtimes take `bedrock:` models. The worker's IAM role is the only credential.

- `pydantic-ai` runtime (the default in `infra/`): `bedrock:us.anthropic.claude-sonnet-4-5-20250929-v1:0`.
- `claude` runtime: the same names; the crew sets `CLAUDE_CODE_USE_BEDROCK=1` for them.

The models live in Terraform's `settings` variable, a `factory.toml` layered
over every repo's own (`factory run --config`), so repos can't pick their own
models or raise limits.

## Trigger: poll, don't listen

Jira Cloud cannot call into a closed VPC. Instead, EventBridge Scheduler runs a
small poller Lambda inside the VPC every 1–2 minutes. It:

1. searches Jira: `labels = factory AND status = "Ready for agent" AND project in (...)`
2. moves each ticket to "In Progress" (so it is picked up once)
3. turns the ticket (summary, description, comments) into a task and creates a
   one-hour GitHub token limited to the ticket's repo (`projects` maps Jira projects to repos)
4. starts one ECS task per ticket with the task, the repo and that token, and
   `startedBy` = the Jira key

If the worker can't start, the ticket gets a comment saying why.

No public endpoint, and about $0 a month. The worker gets only the ticket
contents, so a forged or edited request cannot inject a task.

## Closed VPC: what must be reachable

| Needs | How, without internet |
|---|---|
| Bedrock | VPC interface endpoint `bedrock-runtime` |
| Secrets, logs, images, queue | Endpoints `secretsmanager`, `logs`, `ecr.api`, `ecr.dkr`, `sts`, `ecs`, `sqs`; S3 gateway endpoint (free) |
| `make ui` (SSM port forwarding) | Endpoint `ssmmessages` |
| pip / npm for hydration and checks | CodeArtifact mirrors + `codeartifact.api` / `codeartifact.repositories` endpoints |
| Shared run storage | EFS mount targets |
| GitHub.com, Jira Cloud | The only internet traffic: corporate egress proxy (`HTTPS_PROXY`) or NAT with a domain allow-list |

- Each interface endpoint costs about $7 a month per availability zone. The 9 in `infra/` cost roughly $65 a month in one zone; one zone is fine for the factory. Leave out the ones your VPC already has (`endpoints` variable).
- CodeArtifact is not in `infra/` yet: add its endpoints and a pip/npm mirror if your repos' `hydrate` commands install packages.
- With GitHub Enterprise Server and Jira Data Center inside the network, no internet access is needed at all.

## Secrets

| Secret | Held by | Scope |
|---|---|---|
| Jira service account: `JIRA_EMAIL` + `JIRA_API_TOKEN` (Cloud) or a personal access token (Data Center) | Poller and completion Lambdas | Allowed projects only: browse, comment, transition |
| GitHub App: App ID, installation ID, private key (PEM) | Poller Lambda | Permissions: contents read/write, pull requests read/write, metadata read |
| GitHub installation token (1 hour, one repo) | Worker, as `GH_TOKEN` | Created per run by the poller |
| LLM access | None: the worker's IAM role | `bedrock:InvokeModel` on the chosen models only |
| Packages | None: the worker's IAM role | CodeArtifact read only |

Store them in Secrets Manager.

**The worker never holds long-lived secrets.** The agent runs shell commands
and sees every environment variable, so a prompt-injected ticket could read and
leak them. That is why the Lambdas, not the worker, hold the Jira token and the
GitHub App key. The worker sends its outcome to the SQS results queue and exits 0;
the notify Lambda writes it to Jira. If a worker exits any other way (crash,
timeout, Spot reclaim), the ECS "task stopped" event triggers the same Lambda,
which comments on the ticket named in `startedBy`.

In the worst case, a hijacked run can push a branch to one repo for one hour,
and a human still has to approve the PR.

Skip Logfire and the Slack webhook, or send them through the proxy. Use CloudWatch for logs and tracing.

## UI

The existing dashboard runs as a small private container. It reads a shared
folder that every worker writes to.

```text
   workers (Fargate Spot, one per ticket)
        │  write run.json, events.jsonl, inbox/
        ▼
   EFS  /factory/runs/<run-id>/        ← shared storage ($FACTORY_HOME)
        ▲
        │  read; answers are written back to inbox/
   UI service (Fargate, 0.25 vCPU, always on, no public IP)
        ▲
   `make ui` over SSM, or an internal load balancer + login through your identity provider
        ▲
   you, over VPN or the corporate network
```

### What works once storage is shared

- **Live view:** the dashboard polls run files every 2 seconds, so it shows every worker live.
- **Questions and approvals:** a waiting worker polls its `inbox/` folder. An answer from the UI lands there, so this works across containers unchanged. A waiting worker costs about $0.015 an hour on Fargate Spot.
- **Telemetry:** tool calls, tokens per agent and the fleet view come along for free.

### Access

| Option | Monthly cost | Best for |
|---|---|---|
| `make ui`: SSM port forwarding to the UI task (the default) | about $10 (the container only) | You alone, or a few engineers with AWS access |
| The `alb` variable: internal load balancer with OIDC login, over VPN | about $30 | A team, and people without AWS access |
| `ui = false`; Jira comments only | $0 | If people should never leave Jira |

**Never expose the UI publicly.** It has no login of its own. Its approve and
resume buttons are only protected against other websites calling them. The load
balancer's login is what keeps it safe.

### Jira and the UI together

- **Jira:** where the ticket starts and ends, plus a comment with links to the run and the PR.
- **UI:** live progress, token spend, escalations.

Set `ui_url` and every Jira comment links straight to its run:
`https://factory.internal/control?run=<id>`.

## Cost

| Item | Cost |
|---|---|
| Worker (Fargate Spot, 1 vCPU, 2 GB) | about $0.015 per hour, a few cents per run |
| Poller + completion Lambdas | about $0 |
| UI | $10–30 a month |
| VPC endpoints | about $60 a month (one zone) |
| EFS | about $0.30 per GB-month |
| SQS, Secrets Manager (2 secrets), CloudWatch Logs | about $1 a month |
| **Bedrock tokens** | **the main cost**: 1–7M tokens per run (see the Tokens view) |

Keep costs down:

- Keep prompt caching on.
- Use cheaper models for the implementer and scribe.
- Keep `limits.requests`, `check_retries` and `review_rounds` low.
- Set a task timeout (`worker.timeout`, 3 hours by default).
- Set AWS Budgets (`budget` variable).

## Safety checklist

- [ ] Worker IAM role: Bedrock invoke on the chosen models, CodeArtifact read, its own S3/EFS path. Nothing else, and no production access.
- [ ] Worker security group: outbound HTTPS (443) only, to the VPC endpoints and the proxy.
- [ ] GitHub App token: one hour, one repo, no admin permissions.
- [ ] Branch protection on the default branch: a human review is required. The factory only opens PRs.
- [ ] Only one Jira group can apply the trigger label, and only allow-listed projects and repos run.
- [ ] Every ticket is treated as untrusted input.
- [ ] The UI is reachable only from the internal network, behind login.

## Deploy

```text
infra/
  Makefile              make local | deploy | secrets | ui | destroy
  modules/factory/      the Terraform module: network, storage, ecs, iam, lambdas, ui
  aws/                  your account: main.tf + terraform.tfvars.example
  local/                floci: a VPC to stand in for yours, plus fake.py (Jira and GitHub)
  lambdas/              poll.py, notify.py and their Jira and GitHub clients
  ticket.sh             the worker's entrypoint in the image (factory-ticket)
```

You need Terraform, Docker, the AWS CLI, `uv` and, for `make ui`, the
Session Manager plugin.

### Try it on floci first

```sh
cd infra
make local              # floci start, build the image and Lambdas, terraform apply
python local/fake.py    # another terminal: fake Jira (ticket PROJ-1) and GitHub
make poll               # run the poller now instead of waiting 2 minutes
```

This runs the real Lambdas, ECS task, SQS queue and shared volume:

1. The poller moves PROJ-1 to In Progress and starts a worker.
2. The worker clones the fake repo and runs the factory.
3. The outcome lands on the results queue, and `notify` comments on PROJ-1.

floci's Bedrock returns canned replies, so the run fails at plan. Everything
before and after the models is exercised. `make local-down` stops it all.

### Then on AWS

1. Enable the Claude models in the Bedrock console for your region.
2. Create a GitHub App (contents and pull requests: read and write; metadata:
   read), install it on the repos, and download its private key.
3. Create a Jira service account that can browse, comment on and transition the
   allowed projects, and an API token for it.
4. Fill in `infra/aws/terraform.tfvars` from the `.example` next to it.
5. Deploy and store the secrets:

   ```sh
   cd infra
   make deploy                                    # terraform apply, then build and push the image
   make secrets JIRA=jira.json GITHUB=github.json # JSON shapes are in the secrets' descriptions
   make ui                                        # the dashboard on http://localhost:8765
   ```

6. Label a ticket `factory` and move it to "Ready for agent".

`make deploy` builds the image for `linux/amd64`, which is what the worker's
`X86_64` platform expects. Keep Terraform state in S3 (see the commented
backend in `aws/main.tf`) once more than one person deploys.

## Code changes

Done:

1. **Jira intake:** the poller turns a ticket into task JSON, and `factory run` accepts task JSON.
2. **Jira write-back:** `factory run --report <queue>` sends the outcome; the notify Lambda comments and transitions.
3. **Key in names:** `PROJ-123` stays uppercase in the run id, the branch and the PR title.
4. **Bedrock in the `claude` runtime.**
5. **`FACTORY_HOME`:** every run folder under one shared root (EFS), so one dashboard shows every worker.
6. **Operator settings:** `factory run --config` layers a `factory.toml` over the repo's.
7. **Infrastructure:** `infra/`.

Still to do:

1. **Cloud resume:** the dashboard's resume starts a local process, which the UI container can't do. Add an `ecs` mode that starts a Fargate task.
2. **User attribution:** verify the load balancer's signed user header and record who answered or approved.
3. **Jira as the human channel (optional):** questions become Jira comments, and the next reply is the answer.
4. **A repo filter** in the dashboard, now that it shows every repo's runs.

## Open questions

1. Jira Cloud or Jira Data Center? Both work: a secret without `email` signs in to Data Center with a personal access token.
2. GitHub.com or GitHub Enterprise Server? Both work: set `github_host` and `github_api`.
3. Is there an egress proxy or NAT with an allow-list already? Set `https_proxy`, or leave it empty for NAT.
4. Human channel: dashboard, Jira comments, or both?
