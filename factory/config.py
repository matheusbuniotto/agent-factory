"""How a team tunes the factory, read from `factory.toml`."""

import tomllib
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict

BUNDLED_SKILLS = Path(__file__).parent / "skills"


class Settings(BaseModel):
    model_config = ConfigDict(extra="forbid")


class Endpoint(Settings):
    """An OpenAI-compatible API (vLLM, Ollama, LiteLLM, OpenRouter...). Models use it as `<name>:<model>`."""

    base_url: str
    api_key_env: str | None = None


class Models(Settings):
    planner: str = "anthropic:claude-opus-5-5"
    implementer: str = "anthropic:claude-sonnet-5"
    reviewer: str = "anthropic:claude-opus-5-5"
    scribe: str = "anthropic:claude-haiku-4-5"


class Human(Settings):
    """Where a human steps in. All off means fully autonomous."""

    grill: bool = False
    spec: bool = False
    code: bool = False
    channel: Literal["terminal", "inbox"] = "terminal"  # inbox = answer from the dashboard or `factory answer`
    wait_minutes: int = 30  # then the run carries on as if nobody objected
    webhook: str | None = None  # POSTed {"text", "run"} whenever a human is needed (Slack compatible)


class Limits(Settings):
    check_retries: int = 2
    review_rounds: int = 1
    searches: int = 8
    compact_at: int = 170_000
    requests: int = 200


class Config(Settings):
    checks: list[str] = []
    hydrate: list[str] = []
    skills: list[Path] = []
    pull_request: bool = True
    endpoints: dict[str, Endpoint] = {}
    models: Models = Models()
    human: Human = Human()
    limits: Limits = Limits()

    @classmethod
    def load(cls, repo: Path) -> "Config":
        path = repo / "factory.toml"
        config = cls.model_validate(tomllib.loads(path.read_text()) if path.exists() else {})
        config.skills = [BUNDLED_SKILLS, *(repo / skill for skill in config.skills)]
        return config
