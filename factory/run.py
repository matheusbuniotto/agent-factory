"""A run: one task on its way through the factory, saved after every step."""

import re
import secrets
from datetime import UTC, datetime
from enum import StrEnum
from pathlib import Path

from pydantic import BaseModel, Field

from factory.contracts import Review, Spec, Task

STEPS = ("prepare", "plan", "implement", "review", "ship", "learn")


class Status(StrEnum):
    PENDING = "pending"
    RUNNING = "running"
    DONE = "done"
    FAILED = "failed"
    ESCALATED = "escalated"


class Event(BaseModel):
    """One line of a run's activity log (`events.jsonl`)."""

    at: datetime = Field(default_factory=lambda: _now())
    step: str | None = None
    level: str = "info"
    message: str


class Step(BaseModel):
    name: str
    status: Status = Status.PENDING
    started_at: datetime | None = None
    finished_at: datetime | None = None
    note: str = ""

    def start(self) -> None:
        self.status = Status.RUNNING
        self.started_at = _now()
        self.finished_at = None
        self.note = ""

    def finish(self, status: Status = Status.DONE, note: str = "") -> None:
        self.status = status
        self.finished_at = _now()
        self.note = note


class Run(BaseModel):
    id: str
    task: Task
    repo: Path
    workspace: Path | None = None
    branch: str | None = None
    base: str | None = None
    spec: Spec | None = None
    review: Review | None = None
    pr_url: str | None = None
    guidance: str | None = None
    created_at: datetime = Field(default_factory=lambda: _now())
    steps: list[Step] = Field(default_factory=lambda: [Step(name=name) for name in STEPS])

    @classmethod
    def start(cls, task: Task, repo: Path) -> "Run":
        slug = re.sub(r"[^a-z0-9]+", "-", task.title.lower()).strip("-")[:40].strip("-")
        run_id = f"{_now():%Y%m%d-%H%M%S}-{slug or 'task'}-{secrets.token_hex(2)}"  # unique even for parallel runs
        run = cls(id=run_id, task=task, repo=repo.resolve())
        run.write("task.md", task.to_markdown())
        return run

    @classmethod
    def load(cls, repo: Path, run_id: str) -> "Run":
        return cls.model_validate_json((runs_dir(repo) / run_id / "run.json").read_text())

    @property
    def dir(self) -> Path:
        return runs_dir(self.repo) / self.id

    @property
    def running(self) -> str | None:
        """The step in progress, if any."""
        return next((step.name for step in self.steps if step.status is Status.RUNNING), None)

    @property
    def next_step(self) -> str | None:
        """The first step that is not done: where a resume starts."""
        return next((step.name for step in self.steps if step.status is not Status.DONE), None)

    @property
    def status(self) -> Status:
        return next((step.status for step in self.steps if step.status is not Status.DONE), Status.DONE)

    def step(self, name: str) -> Step:
        return next(step for step in self.steps if step.name == name)

    def rewind(self, name: str) -> None:
        start = STEPS.index(name)
        self.steps[start:] = [Step(name=step) for step in STEPS[start:]]

    def write(self, name: str, text: str) -> Path:
        path = self.dir / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text)
        return path

    def save(self) -> None:
        self.write("run.json", self.model_dump_json(indent=2))

    def log(self, message: str, level: str = "info", step: str | None = None) -> Event:
        """Append to the activity log, tagged with `step` or else the step that is running."""
        event = Event(step=step or self.running, level=level, message=message)
        self.dir.mkdir(parents=True, exist_ok=True)
        with (self.dir / "events.jsonl").open("a") as events:
            events.write(event.model_dump_json() + "\n")
        return event

    def events(self) -> list[Event]:
        path = self.dir / "events.jsonl"
        lines = path.read_text().splitlines() if path.exists() else []
        return [Event.model_validate_json(line) for line in lines]


def runs_dir(repo: Path) -> Path:
    home = repo / ".factory"
    home.mkdir(exist_ok=True)
    (home / ".gitignore").write_text("*\n")
    return home / "runs"


def _now() -> datetime:
    return datetime.now(UTC)
