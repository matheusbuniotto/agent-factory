"""Every deterministic git and subprocess operation the factory performs."""

import subprocess
from pathlib import Path

from factory.contracts import Check


def sh(command: str, cwd: Path) -> Check:
    """Run a shell command. Never raises: the result says whether it passed."""
    done = subprocess.run(command, shell=True, cwd=cwd, capture_output=True, text=True)
    return Check(command=command, passed=done.returncode == 0, output=done.stdout + done.stderr)


def call(*args: str, cwd: Path, input: str | None = None) -> str:
    """Run a git or gh command and return its stdout, raising on failure."""
    done = subprocess.run(args, cwd=cwd, capture_output=True, text=True, input=input)
    if done.returncode != 0:
        raise RuntimeError(f"`{' '.join(args)}` failed:\n{done.stdout}{done.stderr}")
    return done.stdout.strip()


def worktree(repo: Path, run_id: str) -> tuple[Path, str, str]:
    """Create an isolated checkout for the run. Returns (path, branch, base sha)."""
    path, branch = repo / ".factory" / "worktrees" / run_id, f"factory/{run_id}"
    base = call("git", "rev-parse", "HEAD", cwd=repo)
    call("git", "worktree", "add", "-b", branch, str(path), base, cwd=repo)
    return path, branch, base


def diff(workspace: Path, base: str) -> str:
    """Everything that changed since `base`, new files included."""
    call("git", "add", "-A", cwd=workspace)
    return call("git", "diff", "--cached", base, cwd=workspace)


def commit(workspace: Path, message: str) -> bool:
    call("git", "add", "-A", cwd=workspace)
    if not call("git", "status", "--porcelain", cwd=workspace):
        return False
    call("git", "commit", "-m", message, cwd=workspace)
    return True


def remote_url(workspace: Path) -> str | None:
    check = sh("git remote get-url origin", workspace)
    return check.output.strip() if check.passed else None


def push(workspace: Path, branch: str) -> None:
    call("git", "push", "-u", "origin", branch, cwd=workspace)


def open_pr(workspace: Path, title: str, body: str) -> str:
    return call("gh", "pr", "create", "--title", title, "--body", body, cwd=workspace)


def comment(workspace: Path, pr_url: str, body: str) -> None:
    call("gh", "pr", "comment", pr_url, "--body-file", "-", cwd=workspace, input=body)
