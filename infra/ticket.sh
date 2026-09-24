#!/bin/sh
# One Jira ticket in one ECS task. The poller Lambda sets FACTORY_TASK (the task
# as JSON), FACTORY_REPO (owner/name) and GH_TOKEN (that repo only, one hour).
# Terraform sets the rest: FACTORY_SETTINGS, FACTORY_REPORT_URL, FACTORY_HOME.
set -eu

host="${GH_HOST:-github.com}"
cd "$(mktemp -d)"
gh auth setup-git --hostname "$host"
git clone --quiet "${FACTORY_GIT_URL:-https://$host}/${FACTORY_REPO}.git" repo
printf '%s\n' "${FACTORY_SETTINGS:-}" > settings.toml

exec timeout "${FACTORY_TIMEOUT:-3h}" factory run "$FACTORY_TASK" --repo repo --config settings.toml --inbox
