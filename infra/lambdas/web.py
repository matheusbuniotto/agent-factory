"""JSON over HTTPS with the standard library. Honours HTTPS_PROXY, the only way out of a closed VPC."""

import json
import urllib.request


def request(method: str, url: str, body: dict | None = None, headers: dict[str, str] | None = None) -> dict:
    data = json.dumps(body).encode() if body is not None else None
    headers = {"Accept": "application/json", "Content-Type": "application/json", **(headers or {})}
    with urllib.request.urlopen(urllib.request.Request(url, data, headers, method=method), timeout=20) as reply:
        text = reply.read()
    return json.loads(text) if text else {}
