"""`factory run | submit | worker | resume | show | inbox | answer | ui`: the entry points."""

import logging
from pathlib import Path
from typing import Annotated, Literal

import typer

from factory import dispatch
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
Overlay = Annotated[
    Path | None,
    typer.Option("--config", envvar="FACTORY_CONFIG", help="A factory.toml whose settings win over the repo's."),
]
Report = Annotated[
    str | None,
    typer.Option(envvar="FACTORY_REPORT_URL", help="SQS queue told the outcome when the run stops (AWS)."),
]


@app.command()
def run(
    source: Annotated[str, typer.Argument(help="Task text, a markdown file, #issue, an issue url or task JSON.")],
    repo: Repo = Path(),
    grill: Annotated[bool, typer.Option(help="Let the planner ask you questions.")] = False,
    review_spec: Annotated[bool, typer.Option(help="Approve the spec before implementation.")] = False,
    review_code: Annotated[bool, typer.Option(help="Approve the changes before shipping.")] = False,
    inbox: UseInbox = False,
    runtime: Runtime = None,
    config: Overlay = None,
    report: Report = None,
) -> None:
    """Take a task from intake to a branch or pull request."""
    repo = repo.resolve()
    settings = _config(repo, inbox, runtime, config)
    settings.human.grill |= grill
    settings.human.spec |= review_spec
    settings.human.code |= review_code
    _execute(Run.start(intake(source, cwd=repo), repo), settings, report)


@app.command()
def submit(
    source: Annotated[str, typer.Argument(help="Task text, a markdown file, #issue, an issue url or task JSON.")],
    label: Annotated[
        list[str] | None, typer.Option(help="Task label. dispatch.labels in factory.toml maps labels to a lane.")
    ] = None,
    repo: Repo = Path(),
) -> None:
    """Hand a task to its lane, local or sqs, and return straight away."""
    repo = repo.resolve()
    task = intake(source, cwd=repo)
    task.labels += label or []
    lane, ref = dispatch.dispatch(task, repo, Config.load(repo))
    typer.echo(f"{lane}: {ref}")


@app.command()
def worker(repo: Repo = Path(), runtime: Runtime = None, config: Overlay = None) -> None:
    """Run tasks from the SQS queue, one at a time, until stopped."""
    repo = repo.resolve()
    _observe()
    dispatch.work(repo, _config(repo, inbox=True, runtime=runtime, overlay=config))


@app.command()
def resume(
    run_id: str,
    repo: Repo = Path(),
    step: Annotated[str | None, typer.Option("--from", help=f"Rewind to one of: {', '.join(STEPS)}.")] = None,
    guidance: Annotated[str | None, typer.Option(help="Advice for the agent on the step it resumes.")] = None,
    inbox: UseInbox = False,
    runtime: Runtime = None,
    config: Overlay = None,
    report: Report = None,
) -> None:
    """Continue a stopped run, optionally rewinding to a step and giving guidance."""
    repo = repo.resolve()
    run = _load(repo, run_id)
    if step:
        run.rewind(step)
    run.guidance = guidance
    _execute(run, _config(repo, inbox, runtime, config), report)


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
    """Serve the dashboard and the REST intake (POST /api/tasks, /api/hooks/{github,linear,jira})."""
    from factory.ui.server import PAGES, serve

    server = serve(repo.resolve(), host, port)
    typer.echo("Dashboard (add ?demo for sample data):")
    for page in PAGES:
        typer.echo(f"  http://{host}:{port}/{page}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        server.shutdown()


def _config(
    repo: Path, inbox: bool, runtime: Literal["pydantic-ai", "claude"] | None = None, overlay: Path | None = None
) -> Config:
    config = Config.load(repo, overlay)
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


def _execute(run: Run, config: Config, report: str | None = None) -> None:
    _observe()
    typer.echo(f"run {run.id}")
    try:
        run = Pipeline(run, config).execute()
    except Exception:
        if not report:
            raise
        logging.exception("run %s failed", run.id)
    typer.echo(f"\n{run.status}: factory show {run.id}")
    if report:
        dispatch.report(run, report)  # the queue has the outcome; exit 0 so nothing reports it twice
    elif run.status is not Status.DONE:
        raise typer.Exit(1)


def _observe() -> None:
    """Log progress to the terminal, and trace every agent call in Logfire when it is installed and configured."""
    logging.basicConfig(level=logging.INFO, format="%(asctime)s  %(message)s", datefmt="%H:%M:%S")
    try:
        import logfire
    except ImportError:
        return
    logfire.configure(send_to_logfire="if-token-present", console=False)
    logfire.instrument_pydantic_ai()


def main() -> None:
    app()
