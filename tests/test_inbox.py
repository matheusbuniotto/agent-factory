import json
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

import pytest

from factory.config import Human
from factory.contracts import Task
from factory.human import Channel
from factory.inbox import Inbox, Kind
from factory.run import Run


def test_questions_wait_until_answered(tmp_path: Path):
    inbox = Inbox(tmp_path)
    question = inbox.ask(Kind.QUESTION, "Ints or floats?", step="plan")
    assert [q.id for q in inbox.waiting()] == [question.id]

    inbox.answer(question.id, "ints")

    assert inbox.waiting() == []
    assert inbox.get(question.id).answer.text == "ints"
    with pytest.raises(ValueError, match="already answered"):
        inbox.answer(question.id, "floats")


def test_an_empty_answer_means_go_ahead(tmp_path: Path):
    inbox = Inbox(tmp_path)
    question = inbox.ask(Kind.SPEC, "Approve the spec?")
    assert inbox.answer(question.id, "").answer.text is None


def test_the_channel_gets_its_answer_from_another_process(repo: Path):
    run = Run.start(Task(title="t", body="b"), repo)
    channel = Channel(Human(channel="inbox"), run)

    def human():
        while not (waiting := Inbox(run.dir).waiting()):
            pass
        Inbox(run.dir).answer(waiting[0].id, "use ints")

    threading.Thread(target=human, daemon=True).start()
    assert channel.ask("Ints or floats?") == "use ints"
    assert "waiting for a human: Ints or floats?" in [e.message for e in run.events()]


def test_nobody_answering_means_carry_on(repo: Path):
    run = Run.start(Task(title="t", body="b"), repo)
    assert Channel(Human(channel="inbox", wait_minutes=0), run).ask("Anyone?") is None
    assert run.events()[-1].message == "no answer after 0 minutes, carrying on"


def test_webhook_hears_about_every_question(repo: Path):
    received = []

    class Hook(BaseHTTPRequestHandler):
        def do_POST(self):
            received.append(json.loads(self.rfile.read(int(self.headers["Content-Length"]))))
            self.send_response(204)
            self.end_headers()

        def log_message(self, *args):
            pass

    server = HTTPServer(("127.0.0.1", 0), Hook)
    threading.Thread(target=server.handle_request, daemon=True).start()
    run = Run.start(Task(title="Add subtract", body="b"), repo)
    settings = Human(channel="inbox", wait_minutes=0, webhook=f"http://127.0.0.1:{server.server_address[1]}")

    Channel(settings, run).ask("Ints or floats?")

    assert received == [{"text": "Add subtract: Ints or floats?", "run": run.id}]
