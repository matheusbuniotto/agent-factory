"""Webhooks from GitHub, Linear and Jira, turned into a Task.

Each parser reads its provider's payload into the same three facts: the labels
now, whether the ticket was just created, and the labels before this event
(None when the event did not change labels). `starts` then decides, the same
way for every provider. Its properties are proved in `proofs/Factory.lean`.
"""

from collections.abc import Callable

from factory.contracts import Source, Task

Parser = Callable[[dict, str], Task | None]


def starts(trigger: str, labels: list[str], created: bool, before: list[str] | None) -> bool:
    """A ticket created with the trigger label, or one that just gained it."""
    return trigger in labels and (created or (before is not None and trigger not in before))


def github(payload: dict, trigger: str) -> Task | None:
    issue = payload.get("issue")
    if not issue or "pull_request" in issue:
        return None
    labels = [label["name"] for label in issue.get("labels", [])]
    created = payload.get("action") == "opened"
    before = None
    if payload.get("action") == "labeled":
        before = [label for label in labels if label != payload["label"]["name"]]
    if not starts(trigger, labels, created, before):
        return None
    return Task(
        title=issue["title"],
        body=issue.get("body") or "",
        source=Source.ISSUE,
        url=issue["html_url"],
        labels=labels,
    )


def linear(payload: dict, trigger: str) -> Task | None:
    if payload.get("type") != "Issue":
        return None
    issue = payload["data"]
    names = {label["id"]: label["name"] for label in issue.get("labels", [])}
    created = payload.get("action") == "create"
    before = payload.get("updatedFrom", {}).get("labelIds")
    if before is not None:
        before = [name for id, name in names.items() if id in before]
    if not starts(trigger, list(names.values()), created, before):
        return None
    return Task(
        title=issue["title"],
        body=issue.get("description") or "",
        source=Source.LINEAR,
        url=payload.get("url") or issue.get("url"),
        labels=list(names.values()),
    )


def jira(payload: dict, trigger: str) -> Task | None:
    issue = payload.get("issue")
    if not issue:
        return None
    fields = issue["fields"]
    labels = fields.get("labels", [])
    created = payload.get("webhookEvent") == "jira:issue_created"
    changes = payload.get("changelog", {}).get("items", [])
    before = next(((change.get("fromString") or "").split() for change in changes if change["field"] == "labels"), None)
    if not starts(trigger, labels, created, before):
        return None
    site = issue["self"].split("/rest/")[0]
    return Task(
        title=fields["summary"],
        body=fields.get("description") or "",
        source=Source.JIRA,
        url=f"{site}/browse/{issue['key']}",
        labels=labels,
    )


PARSERS: dict[str, Parser] = {"github": github, "linear": linear, "jira": jira}
