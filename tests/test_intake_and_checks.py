import json
from pathlib import Path

import pytest

from factory import checks, intake
from factory.contracts import Source


def test_text_task():
    task = intake.intake("Add a subtract function\nwith tests")
    assert (task.title, task.source) == ("Add a subtract function", Source.TEXT)


def test_file_task_uses_first_heading(tmp_path: Path):
    path = tmp_path / "task.md"
    path.write_text("intro\n# Fix login\nIt breaks.\n")
    task = intake.intake(str(path))
    assert (task.title, task.source, task.url) == ("Fix login", Source.FILE, str(path))


def test_issue_task_goes_through_gh(monkeypatch: pytest.MonkeyPatch):
    issue = {"title": "Bug", "body": "Broken", "url": "https://github.com/o/r/issues/42"}
    monkeypatch.setattr(intake, "call", lambda *args, cwd: json.dumps(issue))
    task = intake.intake("#42")
    assert (task.title, task.source, task.url) == ("Bug", Source.ISSUE, issue["url"])


def test_empty_task():
    with pytest.raises(ValueError, match="empty task"):
        intake.intake("  ")


def test_checks_run_all_and_report_only_failures(repo: Path):
    results = checks.run_checks(["true", "echo broken && false"], repo)

    assert not checks.passed(results)
    assert "`echo broken && false`" in checks.feedback(results)
    assert "`true`" not in checks.feedback(results)
    assert "- pass `true`" in checks.report(results)


def test_default_checks_use_pre_commit_when_present(repo: Path):
    assert checks.commands([], repo) == []
    (repo / ".pre-commit-config.yaml").write_text("repos: []\n")
    assert checks.commands([], repo) == ["pre-commit run --all-files"]
    assert checks.commands(["pytest"], repo) == ["pytest"]
