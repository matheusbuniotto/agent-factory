# Deploy quick guide

Jira ticket in, pull request out, inside your closed VPC. The design and its
reasons are in [docs/aws.md](../docs/aws.md); this page is the checklist.

## 0. Tools

```sh
brew install hashicorp/tap/terraform awscli uv
brew install --cask session-manager-plugin   # for `make ui`
# plus Docker
```

## 1. Try it locally (optional, no credentials)

```sh
cd infra
make local              # floci + the whole stack
python local/fake.py    # another terminal: fake Jira and GitHub
make poll               # PROJ-1 moves to In Progress, a worker runs, Jira gets a comment
make local-down
```

The run fails at planning because floci's Bedrock gives canned replies. Everything else is real.

## 2. Credentials

You need four things. None of them go in git, and the worker never sees the
long-lived ones.

### AWS: to deploy

An IAM user or SSO role that can create VPC endpoints, ECS, Lambda, EFS, SQS,
ECR, IAM roles, Secrets Manager, EventBridge and Budgets in the target account.

```sh
aws configure sso          # or: export AWS_PROFILE=...
aws sts get-caller-identity
```

### Bedrock: model access

Bedrock console → **Model access** → enable Claude Opus, Sonnet and Haiku in your
region. Then list the IDs you can call:

```sh
aws bedrock list-inference-profiles --query 'inferenceProfileSummaries[?contains(inferenceProfileId, `anthropic`)].inferenceProfileId'
```

If they differ from the defaults, set them in the module's `settings` variable
(`modules/factory/variables.tf`). No API key: the worker's IAM role is the credential.

### GitHub App: pushes branches, opens PRs

1. GitHub → Settings → Developer settings → **GitHub Apps** → New GitHub App
   (under your organisation).
   - Webhook: off.
   - Repository permissions: **Contents: Read and write**, **Pull requests: Read and write**, Metadata: Read.
   - Where can it be installed: only this account.
2. **Generate a private key** and download the `.pem`.
3. **Install App** on the repos the factory may change, and only those.
4. Note the **App ID** (app page) and the **installation ID** (the number at the end of
   the installation's URL: `.../settings/installations/<id>`).

```sh
python3 - <<'EOF' > github.json
import json
print(json.dumps({
    "app_id": "123456",
    "installation_id": "78901234",
    "private_key": open("factory.private-key.pem").read(),
}))
EOF
```

The poller turns this into a token for one repo that lasts one hour.

### Jira: reads tickets, comments, moves them

Create a service account (e.g. `factory-bot@acme.com`) that can browse, comment
on and transition issues in the allowed projects only.

- **Jira Cloud:** log in as it → https://id.atlassian.com/manage-profile/security/api-tokens → Create API token.

  ```json
  {"site": "https://acme.atlassian.net", "email": "factory-bot@acme.com", "token": "ATATT..."}
  ```

- **Jira Data Center:** profile → Personal Access Tokens → Create. Leave out `email`.

  ```json
  {"site": "https://jira.acme.internal", "token": "NjM..."}
  ```

Save it as `jira.json`. The workflow needs the statuses **Ready for agent**, **In Progress** and
**In Review**, or set your own names in `jira` in the tfvars. Restrict who can add the `factory` label.

## 3. Configure

```sh
cd infra
cp aws/terraform.tfvars.example aws/terraform.tfvars
```

Fill in `region`, `vpc_id`, `subnet_ids`, `route_table_ids`, `https_proxy` (or
empty for NAT) and `projects` (`{ PROJ = "acme/api" }`). Drop endpoints your
VPC already has from `endpoints`.

## 4. Deploy

```sh
make deploy                                     # terraform apply, then build and push the image
make secrets JIRA=jira.json GITHUB=github.json  # once; again whenever you rotate
rm jira.json github.json factory.private-key.pem
```

## 5. Use it

- Label a ticket `factory` and move it to **Ready for agent**. Within 2 minutes it
  goes to In Progress; a PR link and summary are commented when it's done, and the
  ticket moves to In Review.
- `make ui` → http://localhost:8765 for live progress, token spend and questions.
- Logs: CloudWatch `/factory` (workers, UI), `/aws/lambda/factory-poll`, `/aws/lambda/factory-notify`.

## Troubleshooting

| Symptom | Look at |
|---|---|
| Ticket never moves | `/aws/lambda/factory-poll`: Jira reachable through the proxy? Status and label names match? |
| Ticket comment "could not start" | ECS capacity, subnets, or the GitHub App not installed on that repo |
| "worker stopped before finishing" | `/factory` worker logs: clone failed, timeout (exit 124) or Spot reclaim |
| Run fails at plan | Bedrock model access and IDs, `bedrock-runtime` endpoint |

## Rotate or remove

- Rotate: create a new Jira token or App key, then `make secrets` again. Nothing to redeploy.
- Remove: `make destroy`. Secrets are kept 30 days for recovery.
