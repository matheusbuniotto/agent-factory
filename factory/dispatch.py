"""Where a task runs. Two lanes, picked by the task's labels (see `Dispatch` in config):

- local: start the run here, in a background process.
- sqs:   send the task to an SQS queue. `factory worker` takes it from there.

Background runs have nobody at a terminal, so they ask through the inbox.
"""

import logging
import os
import subprocess
import sys
from collections.abc import Iterator
from pathlib import Path

from factory.config import Config, Lane
from factory.contracts import Task
from factory.pipeline import Pipeline
from factory.run import Run

log = logging.getLogger("factory")


def dispatch(task: Task, repo: Path, config: Config) -> tuple[Lane, str]:
    """Start or enqueue the task. Returns the lane and the run id or SQS message id."""
    match lane := config.dispatch.lane(task.labels):
        case "local":
            run = Run.start(task, repo)
            run.save()
            launch(run)
            return lane, run.id
        case "sqs":
            return lane, send(task, queue_url(config))


def launch(run: Run, step: str | None = None, guidance: str | None = None) -> None:
    """Run or resume in a background process that outlives the caller. Output goes to `resume.log`."""
    command = [sys.executable, "-m", "factory", "resume", run.id, "--repo", str(run.repo)]
    if step:
        command += ["--from", step]
    command.append("--inbox")
    if guidance:
        command += ["--guidance", guidance]
    with (run.dir / "resume.log").open("a") as output:
        subprocess.Popen(command, stdout=output, stderr=subprocess.STDOUT, start_new_session=True)


def queue_url(config: Config) -> str:
    if url := config.dispatch.queue_url or os.environ.get("FACTORY_QUEUE_URL"):
        return url
    raise ValueError("the sqs lane needs dispatch.queue_url in factory.toml or FACTORY_QUEUE_URL")


def send(task: Task, url: str) -> str:
    return _sqs().send_message(QueueUrl=url, MessageBody=task.model_dump_json())["MessageId"]


def receive(url: str) -> Iterator[Task]:
    """Tasks from the queue, forever. Each is deleted on receipt, so a crash never runs a task twice;
    a run that fails stays in `.factory/runs` to resume."""
    sqs = _sqs()
    while True:
        reply = sqs.receive_message(QueueUrl=url, MaxNumberOfMessages=1, WaitTimeSeconds=20)
        for message in reply.get("Messages", []):
            sqs.delete_message(QueueUrl=url, ReceiptHandle=message["ReceiptHandle"])
            yield Task.model_validate_json(message["Body"])


def work(repo: Path, config: Config) -> None:
    """Run queued tasks one at a time. Scale out with more workers."""
    config.human.channel = "inbox"
    for task in receive(queue_url(config)):
        run = Run.start(task, repo)
        log.info("run %s: %s", run.id, task.title)
        try:
            Pipeline(run, config).execute()
        except Exception:
            log.exception("run %s failed", run.id)


def _sqs():
    try:
        import boto3
    except ImportError:
        raise RuntimeError("the sqs lane needs boto3: pip install 'agent-factory[aws]'") from None
    return boto3.client("sqs")
