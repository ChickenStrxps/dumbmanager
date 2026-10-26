"""Tiny optional Python client for a running DumbAPI HTTP server."""
import json
import os
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path


class DumbClient:
    def __init__(self, base_url="http://127.0.0.1:8781", token_file=None):
        self.base_url = base_url.rstrip("/")
        state = Path(os.environ.get("DUMBAPI_DATA_DIR", Path(os.environ.get("LOCALAPPDATA", Path.home() / ".local/share")) / "DumbAPICommunity"))
        self.token_file = Path(token_file) if token_file else state / "http.token"
        self.opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))

    def request(self, path, payload=None):
        headers = {"Authorization": "Bearer " + self.token_file.read_text(encoding="utf-8").strip()}
        raw = None
        if payload is not None:
            headers["Content-Type"] = "application/json"
            raw = json.dumps(payload).encode("utf-8")
        request = urllib.request.Request(self.base_url + path, data=raw, headers=headers)
        try:
            with self.opener.open(request, timeout=30) as response:
                return json.load(response)
        except urllib.error.HTTPError as exc:
            body = json.loads(exc.read())
            raise RuntimeError(body.get("message", str(exc))) from exc

    def search(self, query, **filters):
        return self.request("/v1/search?" + urllib.parse.urlencode({"query": query, **filters}))

    def describe(self, id):
        return self.request("/v1/describe/" + urllib.parse.quote(id, safe=""))

    def call(self, capability, arguments=None, idempotency_key=None):
        payload = {"capability": capability, "arguments": arguments or {}}
        if idempotency_key:
            payload["idempotency_key"] = idempotency_key
        return self.request("/v1/call", payload)

    def job(self, id, log_lines=0):
        return self.request("/v1/jobs/" + urllib.parse.quote(id, safe="") + "?log_lines=" + str(log_lines))

    def wait(self, id, timeout=120):
        deadline = time.monotonic() + timeout
        while True:
            value = self.job(id)
            if value["state"] not in {"queued", "running"}:
                return value
            if time.monotonic() >= deadline:
                raise TimeoutError("Job is still running; keep its ID and inspect it later.")
            time.sleep(0.5)
