"""GitHub App installation tokens, so a worker only ever holds one repo for one hour."""

import json
import time

import jwt
import web

PERMISSIONS = {"contents": "write", "pull_requests": "write"}


class App:
    def __init__(self, app_id: str, installation_id: str, private_key: str, api: str = "https://api.github.com"):
        self.app_id = app_id
        self.installation_id = installation_id
        self.private_key = private_key
        self.api = api.rstrip("/")

    @classmethod
    def from_secret(cls, secret: str, api: str) -> "App":
        """`{"app_id": "...", "installation_id": "...", "private_key": "-----BEGIN RSA PRIVATE KEY-----..."}`"""
        values = json.loads(secret)
        return cls(values["app_id"], values["installation_id"], values["private_key"], api)

    def token(self, repo: str) -> str:
        """A token for `owner/name` only, with contents and pull request write access. It expires in an hour."""
        now = int(time.time())
        claims = {"iat": now - 60, "exp": now + 540, "iss": str(self.app_id)}
        bearer = jwt.encode(claims, self.private_key, algorithm="RS256")
        url = f"{self.api}/app/installations/{self.installation_id}/access_tokens"
        body = {"repositories": [repo.split("/")[-1]], "permissions": PERMISSIONS}
        return web.request("POST", url, body, {"Authorization": f"Bearer {bearer}"})["token"]
