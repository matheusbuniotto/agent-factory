"""`factory run | resume | show | inbox | answer | ui`: the human entry points."""

import logging
from pathlib import Path
from typing import Annotated, Literal

import typer

from factory.config import Config
from factory.inbox import Inbox
from factory.intake import intake
from factory.pipeline import Pipeline
from factory.run import STEPS, Run, Status, runs_dir

app = typer.Typer(no_args_is_help=True, add_completion=False)
Repo = Annotated[Path, typer.Option(help="Git repository to work on.")]
Runtime = Annotated[
    Literal["pydantic-ai", "claude"] | None,
    typer.Option(envvar="FACTORY_RUNTIME", help="Agent runtime: pydantic-ai (API keys) or claude (subscription)."),
]
UseInbox = Annotated[bool, typer.Option("--inbox", help="Wait for answers in the dashboard or `factory answer`.")]


@app.command()
def run(
    source: Annotated[str, typer.Argument(help="Task text, a markdown file, #issue or an issue url.")],
    repo: Repo = Path(),
    grill: Annotated[bool, typer.Option(help="Let the planner ask you questions.")] = False,
    review_spec: Annotated[bool, typer.Option(help="Approve the spec before implementation.")] = False,
    review_code: Annotated[bool, typer.Option(help="Approve the changes before shipping.")] = False,
    inbox: UseInbox = False,
    runtime: Runtime = None,
) -> None:
    """Take a task from intake to a branch or pull request."""
    repo = repo.resolve()
    config = _config(repo, inbox, runtime)
    config.human.grill |= grill
    config.human.spec |= review_spec
    config.human.code |= review_code
    _execute(Run.start(intake(source, cwd=repo), repo), config)


@app.command()
def resume(
    run_id: str,
    repo: Repo = Path(),
    step: Annotated[str | None, typer.Option("--from", help=f"Rewind to one of: {', '.join(STEPS)}.")] = None,
    guidance: Annotated[str | None, typer.Option(help="Advice for the agent on the step it resumes.")] = None,
    inbox: UseInbox = False,
    runtime: Runtime = None,
) -> None:
    """Continue a stopped run, optionally rewinding to a step and giving guidance."""
    repo = repo.resolve()
    run = _load(repo, run_id)
    if step:
        run.rewind(step)
    run.guidance = guidance
    _execute(run, _config(repo, inbox, runtime))


@app.command("inbox")
def list_inbox(repo: Repo = Path()) -> None:
    """Questions and approvals waiting for a human."""
    for path in sorted(runs_dir(repo.resolve()).glob("*/run.json")):
        for question in Inbox(path.parent).waiting():
            typer.echo(f"{path.parent.name}  {question.id}  [{question.kind}] {question.text}")


@app.command()
def answer(
    run_id: str,
    question_id: str,
    text: Annotated[str | None, typer.Argument(help="Leave out to approve or let the agent decide.")] = None,
    repo: Repo = Path(),
) -> None:
    """Answer a waiting question. The run picks it up within a second."""
    run = _load(repo.resolve(), run_id)
    try:
        Inbox(run.dir).answer(question_id, text)
    except (KeyError, ValueError) as error:
        raise typer.BadParameter(str(error)) from None
    typer.echo("answered")


@app.command()
def show(run_id: Annotated[str | None, typer.Argument()] = None, repo: Repo = Path()) -> None:
    """List runs, or show one run's timeline and artifacts."""
    repo = repo.resolve()
    if run_id is None:
        for path in sorted(runs_dir(repo).glob("*/run.json")):
            typer.echo(f"{Run.load(repo, path.parent.name).status:<10} {path.parent.name}")
        return
    run = _load(repo, run_id)
    typer.echo(f"{run.task.title}\n")
    for step in run.steps:
        typer.echo(f"  {step.name:<10} {step.status:<10} {step.note}")
    typer.echo(f"\nArtifacts in {run.dir}:")
    for artifact in sorted(run.dir.glob("*.md")):
        typer.echo(f"  {artifact.name}")


@app.command()
def ui(
    repo: Repo = Path(),
    host: Annotated[str, typer.Option(help="Use 0.0.0.0 inside a container.")] = "127.0.0.1",
    port: int = 8765,
) -> None:
    """Serve the dashboard: watch runs, answer questions, resume escalations."""
    from factory.ui.server import PAGES, serve

    server = serve(repo.resolve(), host, port)
    typer.echo("Dashboard (add ?demo for sample data):")
    for page in PAGES:
        typer.echo(f"  http://{host}:{port}/{page}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        server.shutdown()


def _config(repo: Path, inbox: bool, runtime: Literal["pydantic-ai", "claude"] | None = None) -> Config:
    config = Config.load(repo)
    if runtime:
        config.runtime = runtime
    if inbox:
        config.human.channel = "inbox"
    return config


def _load(repo: Path, run_id: str) -> Run:
    try:
        return Run.load(repo, run_id)
    except FileNotFoundError:
        raise typer.BadParameter(f"no run {run_id!r} in {repo}; see `factory show`") from None


def _execute(run: Run, config: Config) -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s  %(message)s", datefmt="%H:%M:%S")
    _instrument()
    typer.echo(f"run {run.id}")
    run = Pipeline(run, config).execute()
    typer.echo(f"\n{run.status}: factory show {run.id}")
    if run.status is not Status.DONE:
        raise typer.Exit(1)


def _instrument() -> None:
    """Trace every agent call in Logfire when it is installed and configured."""
    try:
        import logfire
    except ImportError:
        return
    logfire.configure(send_to_logfire="if-token-present", console=False)
    logfire.instrument_pydantic_ai()


def main() -> None:
    app()
