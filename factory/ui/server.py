"""`factory ui`: the dashboard over `.factory/runs`. Standard library only.

Reads are open. The two writes, answering a question and resuming a run, need
an `X-Factory` header, which a page on another site cannot send without a CORS
preflight that this server never approves.
"""

import json
import subprocess
import sys
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from pydantic_core import to_json

from factory.inbox import Inbox
from factory.run import STEPS, Run, Status, runs_dir

STATIC = Path(__file__).parent / "static"
PAGES = ("control", "board")
CONTENT_TYPES = {".html": "text/html", ".js": "text/javascript", ".css": "text/css"}
STUCK = (Status.ESCALATED, Status.FAILED)


def needs(run: Run) -> list[dict]:
    """Everything this run is waiting on a human for: open questions, then an escalation."""
    waiting = [question.model_dump(mode="json", exclude={"answer"}) for question in Inbox(run.dir).waiting()]
    if stuck := next((step for step in run.steps if step.status in STUCK), None):
        waiting.append(
            {
                "id": "escalation",
                "kind": "escalation",
                "step": stuck.name,
                "text": stuck.note,
                "asked_at": stuck.finished_at,
            }
        )
    return waiting


def summary(run: Run) -> dict:
    return {
        "id": run.id,
        "title": run.task.title,
        "source": run.task.source,
        "url": run.task.url,
        "status": run.status,
        "step": run.next_step,
        "kind": run.spec and run.spec.kind,
        "size": run.spec and run.spec.size,
        "branch": run.branch,
        "workspace": run.workspace,
        "pr_url": run.pr_url,
        "created_at": run.created_at,
        "steps": run.steps,
        "needs": needs(run),
    }


def detail(run: Run) -> dict:
    artifacts = {path.name: path.read_text() for path in sorted(run.dir.glob("*.md"))}
    return summary(run) | {"events": run.events(), "artifacts": artifacts}


def resume(run: Run, step: str, guidance: str | None) -> None:
    """Continue the run in the background, answering through the inbox."""
    command = [sys.executable, "-m", "factory", "resume", run.id, "--repo", str(run.repo), "--from", step, "--inbox"]
    if guidance:
        command += ["--guidance", guidance]
    with (run.dir / "resume.log").open("a") as log:
        subprocess.Popen(command, stdout=log, stderr=subprocess.STDOUT, start_new_session=True)
    run.log(f"resume requested from the dashboard at {step}", step=step)


def serve(repo: Path, host: str = "127.0.0.1", port: int = 8765) -> ThreadingHTTPServer:
    def runs() -> list[Run]:
        ids = [path.parent.name for path in runs_dir(repo).glob("*/run.json")]
        return sorted((Run.load(repo, run_id) for run_id in ids), key=lambda run: run.created_at, reverse=True)

    def known(run_id: str) -> bool:
        return (runs_dir(repo) / run_id / "run.json").is_file()

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:
            match self._route():
                case [""]:
                    self._file(STATIC / "index.html")
                case [page] if page in PAGES:
                    self._file(STATIC / f"{page}.html")
                case ["static", name] if (STATIC / name).is_file():
                    self._file(STATIC / name)
                case ["api", "runs"]:
                    self._json([summary(run) for run in runs()])
                case ["api", "runs", run_id] if known(run_id):
                    self._json(detail(Run.load(repo, run_id)))
                case _:
                    self.send_error(HTTPStatus.NOT_FOUND)

        def do_POST(self) -> None:
            if not self.headers.get("X-Factory"):
                return self.send_error(HTTPStatus.FORBIDDEN, "missing X-Factory header")
            body = json.loads(self.rfile.read(int(self.headers.get("Content-Length", 0))) or b"{}")
            match self._route():
                case ["api", "runs", run_id, "answer"] if known(run_id):
                    run = Run.load(repo, run_id)
                    try:
                        question = Inbox(run.dir).answer(body["question"], body.get("answer"))
                    except (KeyError, ValueError) as error:
                        return self.send_error(HTTPStatus.CONFLICT, str(error))
                    self._json(question, HTTPStatus.OK)
                case ["api", "runs", run_id, "resume"] if known(run_id):
                    run = Run.load(repo, run_id)
                    if run.status is Status.RUNNING:
                        return self.send_error(HTTPStatus.CONFLICT, "run is already running")
                    step = body.get("step") if body.get("step") in STEPS else run.next_step
                    resume(run, step, body.get("guidance"))
                    self._json({"resumed": run.id, "from": step}, HTTPStatus.ACCEPTED)
                case _:
                    self.send_error(HTTPStatus.NOT_FOUND)

        def _route(self) -> list[str]:
            return self.path.split("?")[0].strip("/").split("/")

        def _file(self, path: Path) -> None:
            self._send(path.read_bytes(), CONTENT_TYPES.get(path.suffix, "text/plain"))

        def _json(self, data: object, status: HTTPStatus = HTTPStatus.OK) -> None:
            self._send(to_json(data), "application/json", status)

        def _send(self, body: bytes, content_type: str, status: HTTPStatus = HTTPStatus.OK) -> None:
            self.send_response(status)
            self.send_header("Content-Type", f"{content_type}; charset=utf-8")
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *args: object) -> None:
            pass

    return ThreadingHTTPServer((host, port), Handler)
