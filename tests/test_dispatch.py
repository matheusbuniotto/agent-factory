"""Webhook parsing, lane routing, the SQS lane and the REST intake."""

import json
import threading
from pathlib import Path
from urllib.error import HTTPError
from urllib.request import Request, urlopen

import pytest

from factory import dispatch, hooks
from factory.config import Config, Dispatch
from factory.contracts import Source, Task
from factory.run import Run
from factory.ui.server import serve

# Webhooks


def github_event(action: str, labels: list[str], added: str | None = None) -> dict:
    issue = {
        "title": "Fix login",
        "body": "It breaks.",
        "html_url": "https://github.com/o/r/issues/7",
        "labels": [{"name": name} for name in labels],
    }
    return {"action": action, "issue": issue} | ({"label": {"name": added}} if added else {})


def test_github_starts_on_open_with_label_or_when_label_is_added():
    task = hooks.github(github_event("opened", ["factory", "bug"]), "factory")
    assert (task.title, task.source, task.labels) == ("Fix login", Source.ISSUE, ["factory", "bug"])
    assert hooks.github(github_event("labeled", ["factory"], added="factory"), "factory")


@pytest.mark.parametrize(
    "event",
    [
        github_event("opened", ["bug"]),
        github_event("labeled", ["factory", "bug"], added="bug"),
        github_event("edited", ["factory"]),
        {"zen": "ping"},
    ],
)
def test_github_ignores_everything_else(event: dict):
    assert hooks.github(event, "factory") is None


def linear_event(action: str, before: list[str] | None = None) -> dict:
    data = {"title": "Add export", "description": "CSV please", "labels": [{"id": "L1", "name": "factory"}]}
    event = {"type": "Issue", "action": action, "data": data, "url": "https://linear.app/t/issue/ENG-1"}
    return event | ({"updatedFrom": {"labelIds": before}} if before is not None else {})


def test_linear_starts_on_create_or_when_label_is_added():
    task = hooks.linear(linear_event("create"), "factory")
    assert (task.title, task.body, task.source, task.url) == (
        "Add export",
        "CSV please",
        Source.LINEAR,
        "https://linear.app/t/issue/ENG-1",
    )
    assert hooks.linear(linear_event("update", before=[]), "factory")
    assert hooks.linear(linear_event("update", before=["L1"]), "factory") is None
    assert hooks.linear(linear_event("update"), "factory") is None  # a title edit, not a label change


def jira_event(event: str, labels: list[str], before: str | None = None) -> dict:
    issue = {
        "key": "OPS-3",
        "self": "https://acme.atlassian.net/rest/api/2/issue/10003",
        "fields": {"summary": "Rotate keys", "description": "Monthly.", "labels": labels},
    }
    changelog = {"items": [{"field": "labels", "fromString": before, "toString": " ".join(labels)}]}
    return {"webhookEvent": event, "issue": issue} | ({"changelog": changelog} if before is not None else {})


def test_jira_starts_on_create_or_when_label_is_added():
    task = hooks.jira(jira_event("jira:issue_created", ["factory"]), "factory")
    assert (task.title, task.source, task.url) == (
        "Rotate keys",
        Source.JIRA,
        "https://acme.atlassian.net/browse/OPS-3",
    )
    assert hooks.jira(jira_event("jira:issue_updated", ["ops", "factory"], before="ops"), "factory")
    assert hooks.jira(jira_event("jira:issue_updated", ["factory", "ops"], before="factory"), "factory") is None
    assert hooks.jira(jira_event("jira:issue_created", ["ops"]), "factory") is None


# Lanes


def test_the_first_known_label_picks_the_lane():
    lanes = Dispatch(labels={"factory:queue": "sqs", "factory:here": "local"})
    assert lanes.lane(["bug", "factory:queue", "factory:here"]) == "sqs"
    assert lanes.lane(["bug"]) == "local"
    assert Dispatch(default="sqs").lane([]) == "sqs"


def test_local_lane_starts_the_run_in_the_background(repo: Path, monkeypatch: pytest.MonkeyPatch):
    started = []
    monkeypatch.setattr(dispatch.subprocess, "Popen", lambda command, **kwargs: started.append(command))

    lane, run_id = dispatch.dispatch(Task(title="Add subtract", body="..."), repo, Config())

    assert lane == "local"
    assert Run.load(repo, run_id).task.title == "Add subtract"
    assert started[0][3:5] == ["resume", run_id]
    assert started[0][-1] == "--inbox"


class FakeSQS:
    def __init__(self):
        self.messages: list[dict] = []

    def send_message(self, QueueUrl: str, MessageBody: str) -> dict:
        self.messages.append({"Body": MessageBody, "ReceiptHandle": str(len(self.messages))})
        return {"MessageId": f"m{len(self.messages)}"}

    def receive_message(self, **kwargs) -> dict:
        return {"Messages": self.messages[:1]}

    def delete_message(self, QueueUrl: str, ReceiptHandle: str) -> None:
        self.messages = [m for m in self.messages if m["ReceiptHandle"] != ReceiptHandle]


def test_sqs_lane_round_trips_the_task(monkeypatch: pytest.MonkeyPatch):
    sqs = FakeSQS()
    monkeypatch.setattr(dispatch, "_sqs", lambda: sqs)
    config = Config(dispatch=Dispatch(default="sqs", queue_url="https://sqs/q"))
    task = Task(title="Fix login", body="It breaks.", labels=["factory"])

    assert dispatch.dispatch(task, Path(), config) == ("sqs", "m1")
    assert next(dispatch.receive("https://sqs/q")) == task
    assert sqs.messages == []  # deleted on receipt


def test_sqs_lane_needs_a_queue(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.delenv("FACTORY_QUEUE_URL", raising=False)
    with pytest.raises(ValueError, match="queue_url"):
        dispatch.dispatch(Task(title="x", body="x"), Path(), Config(dispatch=Dispatch(default="sqs")))


# REST intake


@pytest.fixture
def api(repo: Path, monkeypatch: pytest.MonkeyPatch):
    started = []
    monkeypatch.setattr(dispatch.subprocess, "Popen", lambda command, **kwargs: started.append(command))
    monkeypatch.setenv("FACTORY_TOKEN", "s3cret")
    httpd = serve(repo, port=0)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{httpd.server_address[1]}", repo, started
    httpd.shutdown()


def post(url: str, body: dict, headers: dict | None = None) -> dict:
    request = Request(url, json.dumps(body).encode(), headers or {}, method="POST")
    with urlopen(request) as response:
        return json.loads(response.read())


def test_post_a_markdown_task(api):
    base, repo, started = api
    reply = post(f"{base}/api/tasks", {"task": "# Fix login\n\nIt breaks.", "labels": ["bug"]}, {"X-Factory": "1"})

    assert (reply["lane"], reply["title"]) == ("local", "Fix login")
    assert Run.load(repo, reply["id"]).task.labels == ["bug"]
    assert started


def test_webhooks_need_the_token(api):
    base, _, _ = api
    with pytest.raises(HTTPError) as error:
        post(f"{base}/api/hooks/github?token=wrong", github_event("opened", ["factory"]))
    assert error.value.code == 403


def test_webhook_starts_a_run_or_is_ignored(api):
    base, repo, _ = api
    reply = post(f"{base}/api/hooks/github?token=s3cret", github_event("opened", ["factory"]))
    assert Run.load(repo, reply["id"]).task.url == "https://github.com/o/r/issues/7"

    assert "ignored" in post(f"{base}/api/hooks/github?token=s3cret", github_event("opened", ["bug"]))


@pytest.mark.parametrize(
    ("created", "before", "expected"),
    [
        (True, None, True),  # created with the label
        (False, [], True),  # label just added
        (False, ["factory"], False),  # already had it: no second run
        (False, None, False),  # an edit that did not touch labels
    ],
)
def test_starts(created: bool, before: list[str] | None, expected: bool):
    assert hooks.starts("factory", ["factory"], created, before) is expected
    assert hooks.starts("factory", ["bug"], created, before) is False


@pytest.mark.parametrize("body", [{"task": "Fix", "labels": "bug"}, {"task": 42}, {"labels": []}])
def test_bad_submissions_are_rejected(api, body: dict):
    base, _, _ = api
    with pytest.raises(HTTPError) as error:
        post(f"{base}/api/tasks", body, {"X-Factory": "1"})
    assert error.value.code == 400


def test_a_body_that_is_not_json_is_rejected(api):
    base, _, _ = api
    with pytest.raises(HTTPError) as error:
        urlopen(Request(f"{base}/api/tasks", b"{nope", {"X-Factory": "1"}, method="POST"))
    assert error.value.code == 400
