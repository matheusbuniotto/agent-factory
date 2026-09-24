"""The few Jira calls the factory needs: find ready tickets, move them, comment on them."""

import base64
import json
from urllib.parse import quote, urlencode

import web

FIELDS = "summary,description,labels,comment"


class Jira:
    def __init__(self, site: str, token: str, email: str | None = None):
        """Jira Cloud signs in with an email and API token, Data Center with a personal access token."""
        self.site = site.rstrip("/")
        self.cloud = bool(email)
        credentials = base64.b64encode(f"{email}:{token}".encode()).decode() if email else None
        self.auth = {"Authorization": f"Basic {credentials}" if email else f"Bearer {token}"}

    @classmethod
    def from_secret(cls, secret: str) -> "Jira":
        """`{"site": "https://acme.atlassian.net", "email": "bot@acme.com", "token": "..."}`, no email on DC."""
        values = json.loads(secret)
        return cls(values["site"], values["token"], values.get("email"))

    def search(self, jql: str, limit: int = 10) -> list[dict]:
        path = "/rest/api/2/search/jql" if self.cloud else "/rest/api/2/search"
        return self._call("GET", f"{path}?{urlencode({'jql': jql, 'fields': FIELDS, 'maxResults': limit})}")["issues"]

    def transition(self, key: str, status: str) -> None:
        """Move the ticket to `status` through whichever transition leads there."""
        transitions = self._call("GET", f"/rest/api/2/issue/{quote(key)}/transitions")["transitions"]
        match = next((t for t in transitions if t["to"]["name"].lower() == status.lower()), None)
        if match is None:
            raise LookupError(f"{key} has no transition to {status!r}")
        self._call("POST", f"/rest/api/2/issue/{quote(key)}/transitions", {"transition": {"id": match["id"]}})

    def comment(self, key: str, text: str) -> None:
        self._call("POST", f"/rest/api/2/issue/{quote(key)}/comment", {"body": text})

    def url(self, key: str) -> str:
        return f"{self.site}/browse/{key}"

    def _call(self, method: str, path: str, body: dict | None = None) -> dict:
        return web.request(method, self.site + path, body, self.auth)
