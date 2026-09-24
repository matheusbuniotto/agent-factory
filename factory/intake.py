"""Step 0: turn text, a markdown file or a GitHub issue into a Task."""

import json
import re
from pathlib import Path

from factory.contracts import Source, Task
from factory.workspace import call

ISSUE = re.compile(r"^(#\d+|https://github\.com/[^/]+/[^/]+/issues/\d+)$")


def intake(source: str, cwd: Path = Path()) -> Task:
    source = source.strip()
    if not source:
        raise ValueError("empty task")
    if ISSUE.match(source):
        return _issue(source, cwd)
    if (path := Path(source)).is_file():
        return _file(path)
    return Task(title=source.splitlines()[0][:72], body=source)


def _issue(ref: str, cwd: Path) -> Task:
    issue = json.loads(call("gh", "issue", "view", ref.lstrip("#"), "--json", "title,body,url", cwd=cwd))
    return Task(title=issue["title"], body=issue["body"], source=Source.ISSUE, url=issue["url"])


def _file(path: Path) -> Task:
    body = path.read_text()
    heading = next((line[2:].strip() for line in body.splitlines() if line.startswith("# ")), path.stem)
    return Task(title=heading, body=body, source=Source.FILE, url=str(path))
