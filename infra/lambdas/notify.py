"""Tell Jira how a run ended. Two triggers:

- the results queue: every run that stops sends its outcome there (`factory run --report`);
- an ECS task that stopped without reporting (exit code not 0): crashed, timed out or reclaimed by Spot.
"""

import json
import logging
import os
import re

from aws import secret
from jira import Jira

log = logging.getLogger()
log.setLevel(logging.INFO)

KEY = re.compile(r"^[A-Z][A-Z0-9_]*-\d+$")  # the poller starts each worker with `startedBy` = the Jira key


def handler(event: dict, context: object) -> None:
    jira = Jira.from_secret(secret(os.environ["JIRA_SECRET"]))
    if "Records" in event:
        for record in event["Records"]:
            outcome = json.loads(record["body"])
            if key := jira_key(outcome["task"]):
                reported(jira, key, outcome)
    elif KEY.match(key := event["detail"].get("startedBy") or "") and (code := exit_code(event["detail"])) != 0:
        # `factory run --report` exits 0 once its outcome is on the queue, so this run never reported
        reason = event["detail"].get("stoppedReason")
        jira.comment(key, f"The factory worker stopped before finishing (exit code {code}): {reason}.")


def reported(jira: Jira, key: str, outcome: dict) -> None:
    run = outcome["run"]
    if outcome["status"] == "done":
        lines = [f"The factory opened {outcome['pr_url']}" if outcome["pr_url"] else "The factory finished."]
        lines.append(outcome["learning"] or "")
    else:
        lines = [f"The factory {outcome['status']}: {outcome['reason']}"]
    if ui := os.environ.get("UI_URL"):
        lines.append(f"Run: {ui.rstrip('/')}/control?run={run}")
    jira.comment(key, "\n\n".join(line for line in lines if line))
    if outcome["status"] == "done":
        jira.transition(key, os.environ["DONE_STATUS"])
    log.info("%s: %s, run %s", key, outcome["status"], run)


def jira_key(task: dict | None) -> str | None:
    return task["url"].rsplit("/", 1)[-1] if task and task.get("source") == "jira" else None


def exit_code(detail: dict) -> int | None:
    return next((c.get("exitCode") for c in detail.get("containers", []) if c["name"] == "worker"), None)
