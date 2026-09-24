"""Simulated end to end: a Jira ticket, a Linear ticket and a markdown task go in over HTTP
and each comes out as a committed branch. Everything is real except the crew, which is
scripted so no tokens are spent, and the local lane, which runs in this process."""

import itertools
import json
import subprocess
import threading
from pathlib import Path

import pytest
from test_dispatch import FakeSQS, jira_event, linear_event, post
from test_pipeline import FakeCrew

from factory import dispatch
from factory.config import Config
from factory.contracts import Source, Spec
from factory.pipeline import Pipeline
from factory.run import Run, Status
from factory.ui.server import serve


def scripted(run: Run, config: Config, spec: Spec) -> Pipeline:
    """A pipeline whose crew writes `calc.py` into the run's worktree once it exists."""
    crew = FakeCrew(spec)
    pipeline = Pipeline(run, config, crew=crew)
    prepare = pipeline.prepare

    def prepare_then_hand_over() -> str:
        note = prepare()
        crew.workspace = run.workspace
        return note

    pipeline.prepare = prepare_then_hand_over
    return pipeline


@pytest.fixture
def factory(repo: Path, spec: Spec, monkeypatch: pytest.MonkeyPatch):
    (repo / "factory.toml").write_text(
        "pull_request = false\n"
        f"checks = {json.dumps(spec.acceptance)}\n"
        "[dispatch]\n"
        'queue_url = "https://sqs.local/factory"\n'
        "[dispatch.labels]\n"
        '"factory:queue" = "sqs"\n'
    )
    monkeypatch.setenv("FACTORY_TOKEN", "s3cret")
    sqs = FakeSQS()
    monkeypatch.setattr(dispatch, "_sqs", lambda: sqs)
    monkeypatch.setattr(dispatch, "launch", lambda run: scripted(run, Config.load(repo), spec).execute())
    monkeypatch.setattr(dispatch, "Pipeline", lambda run, config: scripted(run, config, spec))

    httpd = serve(repo, port=0)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{httpd.server_address[1]}", repo, sqs
    httpd.shutdown()


def shipped(repo: Path, run_id: str) -> Run:
    run = Run.load(repo, run_id)
    assert run.status is Status.DONE, [(step.name, step.status, step.note) for step in run.steps]
    log = subprocess.run(["git", "log", "--oneline", run.branch], cwd=repo, capture_output=True, text=True)
    assert "Add subtract" in log.stdout
    return run


def test_jira_ticket_runs_locally(factory):
    base, repo, _ = factory
    reply = post(f"{base}/api/hooks/jira?token=s3cret", jira_event("jira:issue_created", ["factory"]))

    assert reply["lane"] == "local"
    run = shipped(repo, reply["id"])
    assert (run.task.source, run.task.url) == (Source.JIRA, "https://acme.atlassian.net/browse/OPS-3")


def test_linear_ticket_goes_through_the_queue_to_a_worker(factory, monkeypatch: pytest.MonkeyPatch):
    base, repo, sqs = factory
    event = linear_event("create")
    event["data"]["labels"].append({"id": "L2", "name": "factory:queue"})

    reply = post(f"{base}/api/hooks/linear?token=s3cret", event)
    assert (reply["lane"], len(sqs.messages)) == ("sqs", 1)

    receive = dispatch.receive
    monkeypatch.setattr(dispatch, "receive", lambda url: itertools.islice(receive(url), 1))  # one task, then stop
    dispatch.work(repo, Config.load(repo))

    assert sqs.messages == []
    [run_json] = (repo / ".factory" / "runs").glob("*/run.json")
    run = shipped(repo, run_json.parent.name)
    assert (run.task.source, run.task.labels) == (Source.LINEAR, ["factory", "factory:queue"])


def test_markdown_task_runs_locally(factory):
    base, repo, _ = factory
    task = "# Add subtract\n\nA `subtract(a, b)` in calc.py."
    reply = post(f"{base}/api/tasks", {"task": task, "labels": ["math"]}, {"X-Factory": "1"})

    run = shipped(repo, reply["id"])
    assert (run.task.source, run.task.title, run.task.labels) == (Source.TEXT, "Add subtract", ["math"])
