"""Questions the factory asks a human, and their answers.

The run writes `inbox/<id>.json`; whoever answers (dashboard, terminal, a bot)
writes `inbox/<id>.answer.json`. Each side owns its own files, so a running
pipeline and the dashboard never overwrite each other.
"""

import secrets
import time
from datetime import UTC, datetime
from enum import StrEnum
from pathlib import Path

from pydantic import BaseModel, Field


class Kind(StrEnum):
    QUESTION = "question"  # the planner asks while grilling
    SPEC = "spec"  # approve the spec before implementation
    CODE = "code"  # approve the changes before shipping


class Answer(BaseModel):
    """None means "no opinion": approve, or let the agent decide."""

    text: str | None = None
    answered_at: datetime = Field(default_factory=lambda: datetime.now(UTC))


class Question(BaseModel):
    id: str = Field(default_factory=lambda: secrets.token_hex(4))
    kind: Kind
    step: str | None = None
    text: str
    asked_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    answer: Answer | None = None

    @property
    def open(self) -> bool:
        return self.answer is None


class Inbox:
    def __init__(self, run_dir: Path):
        self.dir = run_dir / "inbox"

    def ask(self, kind: Kind, text: str, step: str | None = None) -> Question:
        question = Question(kind=kind, text=text, step=step)
        self.dir.mkdir(parents=True, exist_ok=True)
        (self.dir / f"{question.id}.json").write_text(question.model_dump_json(exclude={"answer"}))
        return question

    def answer(self, question_id: str, text: str | None) -> Question:
        question = self.get(question_id)
        if not question.open:
            raise ValueError(f"question {question_id} is already answered")
        (self.dir / f"{question_id}.answer.json").write_text(Answer(text=text or None).model_dump_json())
        return self.get(question_id)

    def get(self, question_id: str) -> Question:
        path = self.dir / f"{question_id}.json"
        if not path.is_file():
            raise KeyError(question_id)
        answer = self.dir / f"{question_id}.answer.json"
        question = Question.model_validate_json(path.read_text())
        question.answer = Answer.model_validate_json(answer.read_text()) if answer.exists() else None
        return question

    def questions(self) -> list[Question]:
        paths = self.dir.glob("*.json") if self.dir.exists() else []
        ids = [path.stem for path in paths if not path.stem.endswith(".answer")]
        return sorted((self.get(question_id) for question_id in ids), key=lambda q: q.asked_at)

    def waiting(self) -> list[Question]:
        return [question for question in self.questions() if question.open]

    def wait(self, question: Question, timeout: float, poll: float = 1.0) -> Question | None:
        """Block until answered, or return None once `timeout` seconds pass."""
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            if not (current := self.get(question.id)).open:
                return current
            time.sleep(poll)
        return None
