"""Jira and GitHub stand-ins for the floci stack: `python fake.py`, then watch the ticket move.

Serves one ticket, PROJ-1, ready for the factory; the transitions and comments the
Lambdas make; GitHub App tokens; and a git repo to clone, over plain HTTP.
GET /state shows the ticket.
"""

import json
import subprocess
import tempfile
from http import HTTPStatus
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

PORT = 9000
STATUSES = {"11": "In Progress", "21": "In Review"}

ticket = {
    "key": "PROJ-1",
    "status": "Ready for agent",
    "labels": ["factory"],
    "summary": "Add a subtract function",
    "description": "calc.py needs subtract(a, b), with a test.",
    "comments": [],
}


def git_repo() -> Path:
    """A bare repo at <root>/acme/calc.git, cloneable over dumb HTTP."""
    root = Path(tempfile.mkdtemp(prefix="fake-git-"))
    work, bare = root / "work", root / "acme" / "calc.git"
    work.mkdir()
    (work / "calc.py").write_text("def add(a, b):\n    return a + b\n")
    for command in (
        ["git", "init", "-q", "-b", "main"],
        ["git", "add", "."],
        ["git", "-c", "user.name=fake", "-c", "user.email=fake@example.com", "commit", "-qm", "init"],
        ["git", "clone", "-q", "--bare", str(work), str(bare)],
        ["git", "--git-dir", str(bare), "update-server-info"],
    ):
        subprocess.run(command, cwd=work, check=True)
    return root


class Handler(SimpleHTTPRequestHandler):
    def do_GET(self) -> None:
        path = self.path.split("?")[0]
        if path.startswith("/rest/api/2/search"):
            ready = ticket["status"] == "Ready for agent"
            self._json({"issues": [issue()] if ready else []})
        elif path.endswith("/transitions"):
            self._json({"transitions": [{"id": id, "to": {"name": name}} for id, name in STATUSES.items()]})
        elif path == "/state":
            self._json(ticket)
        else:  # the git repo
            super().do_GET()

    def do_POST(self) -> None:
        body = json.loads(self.rfile.read(int(self.headers.get("Content-Length", 0))) or "{}")
        if self.path.endswith("/transitions"):
            ticket["status"] = STATUSES[body["transition"]["id"]]
            print(f"PROJ-1 → {ticket['status']}", flush=True)
            self._json({}, HTTPStatus.NO_CONTENT)
        elif self.path.endswith("/comment"):
            ticket["comments"].append(body["body"])
            print(f"PROJ-1 comment:\n{body['body']}\n", flush=True)
            self._json({"id": str(len(ticket["comments"]))}, HTTPStatus.CREATED)
        elif self.path.endswith("/access_tokens"):
            self._json({"token": "ghs_fake", "expires_at": "2099-01-01T00:00:00Z"}, HTTPStatus.CREATED)
        else:
            self.send_error(HTTPStatus.NOT_FOUND)

    def _json(self, data: dict, status: HTTPStatus = HTTPStatus.OK) -> None:
        body = b"" if status is HTTPStatus.NO_CONTENT else json.dumps(data).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


def issue() -> dict:
    fields = {
        "summary": ticket["summary"],
        "description": ticket["description"],
        "labels": ticket["labels"],
        "comment": {"comments": []},
    }
    return {"key": ticket["key"], "fields": fields}


if __name__ == "__main__":
    root = git_repo()
    server = ThreadingHTTPServer(("0.0.0.0", PORT), lambda *a: Handler(*a, directory=str(root)))
    print(f"fake Jira and GitHub on :{PORT}, repo at http://host.docker.internal:{PORT}/acme/calc.git", flush=True)
    server.serve_forever()
