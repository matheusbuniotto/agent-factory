"""Run every eval case through the real factory with a cheap model.

Each case is a tiny repo, a task and an `expect` command that must pass in
the shipped worktree. Writes evals/report.json and exits 1 if any case fails.
"""

import json
import subprocess
import sys
import time
from pathlib import Path
from tempfile import TemporaryDirectory

from factory.config import Config
from factory.contracts import Task
from factory.pipeline import Pipeline
from factory.run import Run, Status
from factory.workspace import sh

HERE = Path(__file__).parent
CHEAP = "anthropic:claude-haiku-4-5"
CONFIG = f"""\
pull_request = false
checks = {{checks}}

[models]
planner = "{CHEAP}"
implementer = "{CHEAP}"
reviewer = "{CHEAP}"
scribe = "{CHEAP}"

[limits]
searches = 0
requests = 40
"""


def evaluate(case: dict) -> dict:
    with TemporaryDirectory() as tmp:
        repo = Path(tmp)
        for name, text in case["files"].items():
            (repo / name).write_text(text)
        (repo / "factory.toml").write_text(CONFIG.format(checks=json.dumps(case["checks"])))
        _commit(repo)

        started = time.monotonic()
        run = Run.start(Task(title=case["name"], body=case["task"]), repo)
        run = Pipeline(run, Config.load(repo)).execute()
        expected = run.workspace is not None and sh(case["expect"], run.workspace).passed

        return {
            "name": case["name"],
            "passed": run.status is Status.DONE and expected,
            "status": run.status,
            "steps": {step.name: step.status for step in run.steps},
            "seconds": round(time.monotonic() - started),
        }


def _commit(repo: Path) -> None:
    for args in (
        ["init", "-q", "-b", "main"],
        ["config", "user.name", "evals"],
        ["config", "user.email", "evals@example.com"],
        ["add", "."],
        ["commit", "-qm", "fixture"],
    ):
        subprocess.run(["git", *args], cwd=repo, check=True)


def main() -> None:
    results = [evaluate(case) for case in json.loads((HERE / "cases.json").read_text())]
    (HERE / "report.json").write_text(json.dumps(results, indent=2))
    for result in results:
        verdict = "pass" if result["passed"] else "FAIL"
        print(f"{verdict}  {result['name']:<16} {result['seconds']}s  {result['status']}")
    sys.exit(0 if all(result["passed"] for result in results) else 1)


if __name__ == "__main__":
    main()
