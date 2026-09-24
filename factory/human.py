"""How the factory reaches a person: the terminal or the inbox, plus an optional webhook."""

import json
import logging
import urllib.request

from factory.config import Human
from factory.inbox import Inbox, Kind
from factory.run import Run

log = logging.getLogger("factory")


def terminal(text: str) -> str | None:
    return input(f"\n{text}\n> ").strip() or None


class Channel:
    def __init__(self, settings: Human, run: Run):
        self.settings = settings
        self.run = run

    def ask(self, text: str, kind: Kind = Kind.QUESTION) -> str | None:
        """The human's answer. None when they approve, pass, or don't answer in time."""
        self.notify(f"{self.run.task.title}: {text}")
        if self.settings.channel == "terminal":
            return terminal(text)

        inbox = Inbox(self.run.dir)
        question = inbox.ask(kind, text, step=self.run.running)
        self.run.log(f"waiting for a human: {text}", "warn")
        answered = inbox.wait(question, timeout=self.settings.wait_minutes * 60)
        if answered is None:
            self.run.log(f"no answer after {self.settings.wait_minutes} minutes, carrying on", "warn")
            return None
        self.run.log(f"human answered: {answered.answer.text or 'go ahead'}")
        return answered.answer.text

    def approve(self, what: str, kind: Kind) -> str | None:
        """None when approved, otherwise the changes the human asks for."""
        return self.ask(f"Approve the {what}? Answer with the changes you want, or leave it empty to approve.", kind)

    def notify(self, text: str) -> None:
        if not self.settings.webhook:
            return
        body = json.dumps({"text": text, "run": self.run.id}).encode()
        request = urllib.request.Request(self.settings.webhook, body, {"Content-Type": "application/json"})
        try:
            urllib.request.urlopen(request, timeout=5).close()
        except OSError as error:
            log.warning("webhook failed: %s", error)
