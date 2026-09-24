"""The data that flows between factory steps and agents."""

from enum import StrEnum

from pydantic import BaseModel, Field


class Source(StrEnum):
    TEXT = "text"
    FILE = "file"
    ISSUE = "issue"


class Task(BaseModel):
    """What a human asked for."""

    title: str
    body: str
    source: Source = Source.TEXT
    url: str | None = None

    def to_markdown(self) -> str:
        origin = f"\n\nSource: {self.url}" if self.url else ""
        return f"# {self.title}\n\n{self.body}{origin}\n"


class Kind(StrEnum):
    """Which skill set the task needs."""

    SOFTWARE = "software"
    DATA = "data"
    AI = "ai"


class Size(StrEnum):
    """Simple tasks get a short spec, standard ones a full design doc."""

    SIMPLE = "simple"
    STANDARD = "standard"


class Scenario(BaseModel):
    """A BDD scenario."""

    name: str
    given: str
    when: str
    then: str


class Example(BaseModel):
    """A worked example with an exact input and expected result."""

    name: str
    input: str
    expected: str
    failure: bool = Field(False, description="True if this example shows an error path")


class Spec(BaseModel):
    """The design doc: the implementer builds from this and nothing else."""

    title: str
    kind: Kind
    size: Size
    purpose: str = Field(description="One paragraph: the capability this change owns")
    in_scope: list[str] = []
    out_of_scope: list[str] = []
    scenarios: list[Scenario] = []
    examples: list[Example] = []
    interface: str = Field("", description="Public signatures, endpoints or schemas")
    invariants: list[str] = []
    must_not_infer: list[str] = Field([], description="Decisions the implementer must not make on its own")
    acceptance: list[str] = Field([], description="Exact commands or assertions that prove it works")
    assumptions: list[str] = Field([], description="Guesses made instead of asking the human")
    open_questions: list[str] = []
    sources: list[str] = Field([], description="Links consulted during research")

    def gaps(self) -> list[str]:
        """What keeps this spec from being buildable. Empty means ready."""
        required = {
            "purpose": self.purpose.strip(),
            "scenarios": self.scenarios,
            "acceptance": self.acceptance,
        }
        if self.size is Size.STANDARD:
            required |= {
                "out_of_scope": self.out_of_scope,
                "must_not_infer": self.must_not_infer,
                "success example": [e for e in self.examples if not e.failure],
                "failure example": [e for e in self.examples if e.failure],
            }
        return [f"missing {name}" for name, value in required.items() if not value]

    def to_markdown(self) -> str:
        scenarios = [f"**{s.name}**\n- Given {s.given}\n- When {s.when}\n- Then {s.then}" for s in self.scenarios]
        examples = [
            f"**{e.name}**{' (failure)' if e.failure else ''}\n\nInput:\n```\n{e.input}\n```\n"
            f"Expected:\n```\n{e.expected}\n```"
            for e in self.examples
        ]
        sections = {
            "Purpose": self.purpose,
            "In scope": _bullets(self.in_scope),
            "Out of scope": _bullets(self.out_of_scope),
            "Scenarios": "\n\n".join(scenarios),
            "Worked examples": "\n\n".join(examples),
            "Public interface": f"```\n{self.interface}\n```" if self.interface else "",
            "Invariants": _bullets(self.invariants),
            "Must not infer": _bullets(self.must_not_infer),
            "Acceptance": _bullets(self.acceptance),
            "Assumptions": _bullets(self.assumptions),
            "Open questions": _bullets(self.open_questions),
            "Sources": _bullets(self.sources),
        }
        header = f"# {self.title}\n\n`{self.kind}` · `{self.size}`"
        return _document(header, sections)


class Check(BaseModel):
    """The outcome of one deterministic command."""

    command: str
    passed: bool
    output: str = ""


class Verdict(StrEnum):
    APPROVE = "approve"
    REQUEST_CHANGES = "request_changes"


class Review(BaseModel):
    """What the reviewer thinks of the diff."""

    verdict: Verdict
    summary: str
    comments: list[str] = Field([], description="Concrete defects, each with file:line when possible")

    @property
    def approved(self) -> bool:
        return self.verdict is Verdict.APPROVE

    def to_markdown(self) -> str:
        return _document(f"# Review: {self.verdict}", {"Summary": self.summary, "Comments": _bullets(self.comments)})


def _bullets(items: list[str]) -> str:
    return "\n".join(f"- {item}" for item in items)


def _document(header: str, sections: dict[str, str]) -> str:
    body = "".join(f"\n\n## {title}\n\n{text}" for title, text in sections.items() if text)
    return f"{header}{body}\n"
