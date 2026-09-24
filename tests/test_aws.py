"""The AWS deployment: the factory's side of it, and the poll and notify Lambdas with Jira, GitHub and AWS faked."""

import json
import sys
from pathlib import Path

import jwt
import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from typer.testing import CliRunner

from factory import cli, dispatch
from factory.config import Config
from factory.contracts import Source, Task
from factory.intake import intake
from factory.run import Run, Status, runs_dir

sys.path.insert(0, str(Path(__file__).parents[1] / "infra" / "lambdas"))
import github  # noqa: E402
import jira  # noqa: E402
import notify  # noqa: E402
import poll  # noqa: E402

TICKET = Task(title="Fix login", body="It breaks.", source=Source.JIRA, url="https://acme.atlassian.net/browse/PROJ-7")


class FakeSQS:
    def __init__(self):
        self.sent: list[dict] = []

    def send_message(self, QueueUrl: str, MessageBody: str) -> dict:
        self.sent.append(json.loads(MessageBody))
        return {"MessageId": "m1"}


# The factory


def test_a_jira_ticket_arrives_as_json_and_keeps_its_key(repo: Path):
    task = intake(TICKET.model_dump_json())
    assert task == TICKET and task.key == "PROJ-7"
    assert "-PROJ-7-fix-login-" in Run.start(task, repo).id
    assert Task(title="t", body="b").key is None


def test_factory_home_holds_every_repo_s_runs(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("FACTORY_HOME", str(tmp_path / "shared"))
    assert runs_dir(Path("/any/repo")) == tmp_path / "shared" / "runs"


def test_the_operator_overlay_wins_table_by_table(repo: Path, tmp_path: Path):
    (repo / "factory.toml").write_text('checks = ["pytest"]\n[models]\nplanner = "a"\nscribe = "b"\n')
    overlay = tmp_path / "ops.toml"
    overlay.write_text('[models]\nplanner = "bedrock:c"\n[human]\nchannel = "inbox"\n')
    config = Config.load(repo, overlay)
    assert config.checks == ["pytest"]
    assert (config.models.planner, config.models.scribe) == ("bedrock:c", "b")
    assert config.human.channel == "inbox"


def test_a_failed_run_is_reported_and_exits_zero(repo: Path, monkeypatch: pytest.MonkeyPatch):
    sqs = FakeSQS()
    monkeypatch.setattr(dispatch, "_sqs", lambda: sqs)

    class Broken:
        def __init__(self, run: Run, config: Config):
            self.run = run

        def execute(self) -> Run:
            self.run.steps[0].finish(Status.FAILED, "RuntimeError('no git')")
            raise RuntimeError("no git")

    monkeypatch.setattr(cli, "Pipeline", Broken)
    source = TICKET.model_dump_json()
    result = CliRunner().invoke(cli.app, ["run", source, "--repo", str(repo), "--report", "https://sqs/results"])
    assert result.exit_code == 0, result.output
    [outcome] = sqs.sent
    assert outcome["status"] == "failed" and outcome["reason"] == "RuntimeError('no git')"
    assert outcome["task"]["url"] == TICKET.url and outcome["pr_url"] is None


# poll


class FakeJira:
    site = "https://acme.atlassian.net"

    def __init__(self, *issues: dict, stuck: bool = False):
        self.issues = list(issues)
        self.stuck = stuck
        self.calls: list[tuple] = []

    def search(self, jql: str) -> list[dict]:
        self.calls.append(("search", jql))
        return self.issues

    def transition(self, key: str, status: str) -> None:
        if self.stuck:
            raise LookupError(f"{key} has no transition to {status!r}")
        self.calls.append(("transition", key, status))

    def comment(self, key: str, text: str) -> None:
        self.calls.append(("comment", key, text))

    def url(self, key: str) -> str:
        return f"{self.site}/browse/{key}"


class FakeECS:
    def __init__(self, failures: list | None = None):
        self.failures = failures or []
        self.tasks: list[dict] = []

    def run_task(self, **task) -> dict:
        self.tasks.append(task)
        return {"failures": self.failures}


def issue(key: str = "PROJ-7") -> dict:
    comment = {"author": {"displayName": "Ana"}, "body": "Only on Safari."}
    fields = {"summary": "Fix login", "description": "It breaks.", "labels": ["factory"]}
    return {"key": key, "fields": fields | {"comment": {"comments": [comment]}}}


@pytest.fixture
def lambdas(monkeypatch: pytest.MonkeyPatch):
    env = {
        "JIRA_SECRET": "jira",
        "GITHUB_SECRET": "github",
        "GITHUB_API": "https://api.github.com",
        "PROJECTS": '{"PROJ": "acme/api"}',
        "TRIGGER": "factory",
        "READY_STATUS": "Ready for agent",
        "STARTED_STATUS": "In Progress",
        "DONE_STATUS": "In Review",
        "CLUSTER": "factory",
        "TASK_DEFINITION": "factory-worker:3",
        "CAPACITY": "FARGATE_SPOT",
        "SUBNETS": "subnet-a,subnet-b",
        "SECURITY_GROUP": "sg-1",
        "UI_URL": "https://factory.internal",
    }
    for name, value in env.items():
        monkeypatch.setenv(name, value)

    def wire(board: FakeJira, ecs: FakeECS | None = None) -> FakeECS:
        ecs = ecs or FakeECS()
        for module in (poll, notify):
            monkeypatch.setattr(module, "secret", lambda arn: arn)
            monkeypatch.setattr(module.Jira, "from_secret", classmethod(lambda cls, secret: board))
        monkeypatch.setattr(poll.App, "from_secret", classmethod(lambda cls, secret, api: FakeApp()))
        monkeypatch.setattr(poll.boto3, "client", lambda service: ecs)
        return ecs

    return wire


class FakeApp:
    def token(self, repo: str) -> str:
        return f"ghs_{repo}"


def test_poll_moves_the_ticket_then_starts_a_worker(lambdas):
    board = FakeJira(issue())
    ecs = lambdas(board)

    assert poll.handler({}, None) == {"started": ["PROJ-7"]}
    (_, jql), transition = board.calls
    assert jql.startswith('project in ("PROJ") AND labels = "factory" AND status = "Ready for agent"')
    assert transition == ("transition", "PROJ-7", "In Progress")

    [task] = ecs.tasks
    assert task["capacityProviderStrategy"] == [{"capacityProvider": "FARGATE_SPOT", "weight": 1}]
    assert task["networkConfiguration"]["awsvpcConfiguration"]["assignPublicIp"] == "DISABLED"
    env = {v["name"]: v["value"] for v in task["overrides"]["containerOverrides"][0]["environment"]}
    assert env["FACTORY_REPO"] == "acme/api" and env["GH_TOKEN"] == "ghs_acme/api"
    handed = Task.model_validate_json(env["FACTORY_TASK"])
    assert handed.key == "PROJ-7" and "Ana: Only on Safari." in handed.body


def test_poll_comments_when_a_worker_cannot_start(lambdas):
    board = FakeJira(issue())
    lambdas(board, FakeECS(failures=[{"reason": "RESOURCE:MEMORY"}]))
    assert poll.handler({}, None) == {"started": []}
    assert board.calls[-1][:2] == ("comment", "PROJ-7") and "RESOURCE:MEMORY" in board.calls[-1][2]


def test_poll_skips_tickets_it_cannot_move(lambdas):
    board = FakeJira(issue(), stuck=True)
    ecs = lambdas(board)
    assert poll.handler({}, None) == {"started": []}
    assert ecs.tasks == [] and not [call for call in board.calls if call[0] == "comment"]


def test_poll_cuts_long_tickets_to_fit_ecs_overrides():
    long = issue()
    long["fields"]["description"] = "x" * 10_000
    task = poll.task(long, FakeJira())
    assert len(task["body"]) < poll.MAX_BODY + 200 and task["body"].endswith("/browse/PROJ-7)")


# notify


def outcome(status: str, **fields) -> dict:
    base = {"run": "r1", "status": status, "task": TICKET.model_dump(mode="json"), "pr_url": None}
    return {"Records": [{"body": json.dumps(base | {"reason": None, "learning": None} | fields)}]}


def test_a_shipped_run_links_the_pr_and_moves_to_review(lambdas):
    board = FakeJira()
    lambdas(board)
    notify.handler(outcome("done", pr_url="https://github.com/acme/api/pull/9", learning="ELI5"), None)
    (_, key, text), transition = board.calls
    assert key == "PROJ-7" and "pull/9" in text and "ELI5" in text and "control?run=r1" in text
    assert transition == ("transition", "PROJ-7", "In Review")


def test_an_escalated_run_explains_why_and_stays_put(lambdas):
    board = FakeJira()
    lambdas(board)
    notify.handler(outcome("escalated", reason="checks still failing"), None)
    [(_, _, text)] = board.calls
    assert "escalated: checks still failing" in text


def ecs_stopped(code: int | None, started_by: str | None = "PROJ-7") -> dict:
    return {
        "detail": {
            "startedBy": started_by,
            "stoppedReason": "Your Spot Task was interrupted.",
            "containers": [{"name": "worker", "exitCode": code}],
        }
    }


@pytest.mark.parametrize(("code", "comments"), [(0, 0), (1, 1), (124, 1), (None, 1)])
def test_a_worker_that_never_reported_is_reported(lambdas, code: int | None, comments: int):
    board = FakeJira()
    lambdas(board)
    notify.handler(ecs_stopped(code), None)
    assert len(board.calls) == comments
    if comments:
        assert board.calls[0][1] == "PROJ-7" and "Spot Task was interrupted" in board.calls[0][2]


def test_workers_not_started_by_the_poller_are_left_alone(lambdas):
    board = FakeJira()
    lambdas(board)
    notify.handler(ecs_stopped(1, started_by=None), None)
    assert board.calls == []


# Jira and GitHub clients


def test_jira_cloud_and_data_center_sign_in_differently():
    assert jira.Jira("https://acme.atlassian.net/", "t", "bot@acme.com").auth["Authorization"].startswith("Basic ")
    assert jira.Jira("https://jira.acme.internal", "pat").auth == {"Authorization": "Bearer pat"}


def test_github_app_asks_for_one_repo(monkeypatch: pytest.MonkeyPatch):
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    pem = key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption())
    calls = []
    monkeypatch.setattr(github.web, "request", lambda *args: calls.append(args) or {"token": "ghs_1"})

    assert github.App("42", "7", pem.decode()).token("acme/api") == "ghs_1"
    [(method, url, body, headers)] = calls
    assert (method, url) == ("POST", "https://api.github.com/app/installations/7/access_tokens")
    assert body["repositories"] == ["api"]
    claims = jwt.decode(headers["Authorization"].split()[1], key.public_key(), algorithms=["RS256"])
    assert claims["iss"] == "42" and claims["exp"] - claims["iat"] <= 600
