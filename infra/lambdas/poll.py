"""Every few minutes: start one ECS task per Jira ticket that is ready for the factory.

Jira can't call into a closed VPC, so this Lambda asks it instead. It holds the Jira
and GitHub App secrets; the worker it starts only gets the ticket and a token for
one repo that expires in an hour.
"""

import json
import logging
import os

import boto3
from aws import secret
from github import App
from jira import Jira

log = logging.getLogger()
log.setLevel(logging.INFO)

MAX_BODY = 6000  # ECS allows 8 KB of overrides per task


def handler(event: dict, context: object) -> dict:
    jira = Jira.from_secret(secret(os.environ["JIRA_SECRET"]))
    github = App.from_secret(secret(os.environ["GITHUB_SECRET"]), os.environ["GITHUB_API"])
    repos = json.loads(os.environ["PROJECTS"])  # {"PROJ": "owner/name"}
    started = []
    for issue in jira.search(jql(repos)):
        key = issue["key"]
        try:
            jira.transition(key, os.environ["STARTED_STATUS"])  # first, so the next poll can't pick it up again
        except Exception:
            log.exception("%s: can't move it to %s, skipped", key, os.environ["STARTED_STATUS"])
            continue
        try:
            repo = repos[key.split("-")[0]]
            start(key, task(issue, jira), repo, github.token(repo))
        except Exception as error:
            log.exception("%s: not started", key)
            jira.comment(key, f"The factory could not start this ticket: {error}")
        else:
            log.info("%s: started on %s", key, repo)
            started.append(key)
    return {"started": started}


def jql(repos: dict[str, str]) -> str:
    projects = ", ".join(f'"{project}"' for project in repos)
    return (
        f'project in ({projects}) AND labels = "{os.environ["TRIGGER"]}" '
        f'AND status = "{os.environ["READY_STATUS"]}" ORDER BY created ASC'
    )


def task(issue: dict, jira: Jira) -> dict:
    """The ticket as a factory Task: summary, description and the discussion so far."""
    fields = issue["fields"]
    body = fields.get("description") or ""
    comments = (fields.get("comment") or {}).get("comments", [])
    if comments:
        body += "\n\n## Comments\n\n" + "\n\n".join(f"{c['author']['displayName']}: {c['body']}" for c in comments)
    if len(body) > MAX_BODY:
        body = body[:MAX_BODY] + f"\n\n(cut short; read the rest at {jira.url(issue['key'])})"
    return {
        "title": fields["summary"],
        "body": body,
        "source": "jira",
        "url": jira.url(issue["key"]),
        "labels": fields.get("labels", []),
    }


def start(key: str, task: dict, repo: str, token: str) -> None:
    environment = {"FACTORY_TASK": json.dumps(task), "FACTORY_REPO": repo, "GH_TOKEN": token}
    reply = boto3.client("ecs").run_task(
        cluster=os.environ["CLUSTER"],
        taskDefinition=os.environ["TASK_DEFINITION"],
        capacityProviderStrategy=[{"capacityProvider": os.environ["CAPACITY"], "weight": 1}],
        networkConfiguration={
            "awsvpcConfiguration": {
                "subnets": os.environ["SUBNETS"].split(","),
                "securityGroups": [os.environ["SECURITY_GROUP"]],
                "assignPublicIp": "DISABLED",
            }
        },
        overrides={
            "containerOverrides": [
                {"name": "worker", "environment": [{"name": k, "value": v} for k, v in environment.items()]}
            ]
        },
        startedBy=key,
    )
    if reply.get("failures"):
        raise RuntimeError(f"ECS refused the task: {reply['failures']}")
