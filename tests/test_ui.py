"""The dashboard server: routes, JSON shape and path safety."""

import json
import threading
from pathlib import Path
from urllib.error import HTTPError
from urllib.request import Request, urlopen

import pytest

from factory.contracts import Task
from factory.inbox import Inbox, Kind
from factory.run import Run, Status
from factory.ui import server as ui
from factory.ui.server import PAGES, serve


@pytest.fixture
def server(repo: Path):
    run = Run.start(Task(title="Add subtract", body="..."), repo)
    run.step("prepare").start()
    run.log("started")
    run.save()
    httpd = serve(repo, port=0)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{httpd.server_address[1]}", run
    httpd.shutdown()


def get(url: str) -> bytes:
    with urlopen(url) as response:
        return response.read()


def test_every_design_is_served(server):
    base, _ = server
    for design in ("", *PAGES, "static/common.js"):
        assert get(f"{base}/{design}")


def test_runs_api_summarises_and_details_a_run(server):
    base, run = server
    [summary] = json.loads(get(f"{base}/api/runs"))
    assert (summary["id"], summary["status"], summary["step"]) == (run.id, "running", "prepare")

    detail = json.loads(get(f"{base}/api/runs/{run.id}"))
    assert detail["events"][0] == {
        "at": detail["events"][0]["at"],
        "step": "prepare",
        "level": "info",
        "message": "started",
    }
    assert "task.md" in detail["artifacts"]


@pytest.mark.parametrize("path", ["api/runs/..%2F..%2Fetc", "static/../server.py", "api/runs/nope", "admin"])
def test_unknown_or_escaping_paths_are_404(server, path: str):
    base, _ = server
    with pytest.raises(HTTPError) as error:
        get(f"{base}/{path}")
    assert error.value.code == 404


def post(url: str, body: dict, header: bool = True) -> dict:
    request = Request(url, json.dumps(body).encode(), {"X-Factory": "1"} if header else {}, method="POST")
    with urlopen(request) as response:
        return json.loads(response.read())


def test_answering_a_question_from_the_dashboard(server):
    base, run = server
    question = Inbox(run.dir).ask(Kind.QUESTION, "Ints or floats?", step="plan")
    [summary] = json.loads(get(f"{base}/api/runs"))
    assert [need["text"] for need in summary["needs"]] == ["Ints or floats?"]

    post(f"{base}/api/runs/{run.id}/answer", {"question": question.id, "answer": "ints"})

    assert Inbox(run.dir).get(question.id).answer.text == "ints"
    assert json.loads(get(f"{base}/api/runs"))[0]["needs"] == []


def test_writes_need_the_factory_header(server):
    base, run = server
    with pytest.raises(HTTPError) as error:
        post(f"{base}/api/runs/{run.id}/answer", {"question": "x"}, header=False)
    assert error.value.code == 403


def test_escalations_are_needs_and_resume_in_the_background(server, monkeypatch: pytest.MonkeyPatch):
    base, run = server
    run.step("prepare").finish(Status.ESCALATED, "hydration failed")
    run.save()
    [need] = json.loads(get(f"{base}/api/runs"))[0]["needs"]
    assert (need["kind"], need["step"], need["text"]) == ("escalation", "prepare", "hydration failed")

    started = []
    monkeypatch.setattr(ui.subprocess, "Popen", lambda command, **kwargs: started.append(command))
    assert post(f"{base}/api/runs/{run.id}/resume", {"guidance": "proxy is fixed"}) == {
        "resumed": run.id,
        "from": "prepare",
    }
    assert started[0][-4:] == ["prepare", "--inbox", "--guidance", "proxy is fixed"]


def test_a_running_run_cannot_be_resumed(server):
    base, run = server
    with pytest.raises(HTTPError) as error:
        post(f"{base}/api/runs/{run.id}/resume", {})
    assert error.value.code == 409
