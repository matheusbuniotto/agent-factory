import subprocess
from pathlib import Path

import pytest

from factory.contracts import Scenario, Spec


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    """A git repo with one commit."""

    def git(*args: str) -> None:
        subprocess.run(["git", *args], cwd=tmp_path, check=True, capture_output=True)

    git("init", "-q", "-b", "main")
    git("config", "user.email", "factory@example.com")
    git("config", "user.name", "Factory")
    (tmp_path / "README.md").write_text("# demo\n")
    git("add", ".")
    git("commit", "-qm", "init")
    return tmp_path


@pytest.fixture
def spec() -> Spec:
    return Spec(
        title="Add subtract",
        kind="software",
        size="simple",
        purpose="Subtract two numbers.",
        scenarios=[Scenario(name="basic", given="2 and 3", when="subtract", then="-1")],
        acceptance=["python -c 'from calc import subtract; assert subtract(2, 3) == -1'"],
    )
