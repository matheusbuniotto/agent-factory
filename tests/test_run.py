import re
from pathlib import Path

from factory.config import BUNDLED_SKILLS, Config
from factory.contracts import Task
from factory.run import Run, Status


def test_run_round_trips_and_ignores_itself(repo: Path):
    run = Run.start(Task(title="Add subtract!", body="..."), repo)
    run.save()

    assert re.fullmatch(r"\d{8}-\d{6}-add-subtract-[0-9a-f]{4}", run.id)
    assert Run.load(repo, run.id) == run
    assert (repo / ".factory/.gitignore").read_text() == "*\n"
    assert (run.dir / "task.md").exists()


def test_rewind_resets_the_step_and_everything_after(repo: Path):
    run = Run.start(Task(title="t", body="b"), repo)
    for name in ("prepare", "plan", "implement"):
        run.step(name).finish()
    run.step("review").finish(Status.FAILED, "boom")

    run.rewind("implement")

    assert [step.status for step in run.steps] == ["done", "done", "pending", "pending", "pending", "pending"]
    assert run.status is Status.PENDING


def test_config_defaults_and_toml(repo: Path):
    (repo / "skills").mkdir()
    (repo / "factory.toml").write_text('checks = ["pytest"]\nskills = ["skills"]\n[human]\nspec = true\n')

    config = Config.load(repo)

    assert config.checks == ["pytest"]
    assert config.human.spec and not config.human.grill
    assert config.skills == [BUNDLED_SKILLS, repo / "skills"]
    assert config.limits.check_retries == 2
