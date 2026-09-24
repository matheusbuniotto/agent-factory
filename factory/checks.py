"""Linters, tests and hooks: the deterministic gate after every implementation."""

from pathlib import Path

from factory.contracts import Check
from factory.workspace import call, sh

TAIL = 4000


def commands(configured: list[str], workspace: Path) -> list[str]:
    if configured:
        return configured
    if (workspace / ".pre-commit-config.yaml").exists():
        return ["pre-commit run --all-files"]
    return []


def run_checks(commands: list[str], workspace: Path) -> list[Check]:
    call("git", "add", "-A", cwd=workspace)  # pre-commit only sees tracked files
    return [sh(command, workspace) for command in commands]


def passed(checks: list[Check]) -> bool:
    return all(check.passed for check in checks)


def feedback(checks: list[Check]) -> str:
    failures = "".join(
        f"\n\n### `{check.command}`\n```\n{check.output[-TAIL:]}\n```" for check in checks if not check.passed
    )
    return f"The following checks failed. Fix them without weakening the checks.{failures}"


def report(checks: list[Check], title: str = "Checks") -> str:
    if not checks:
        return f"# {title}\n\nNothing to run.\n"
    rows = "".join(f"\n- {'pass' if check.passed else 'FAIL'} `{check.command}`" for check in checks)
    details = f"\n\n{feedback(checks)}\n" if not passed(checks) else "\n"
    return f"# {title}\n{rows}{details}"
