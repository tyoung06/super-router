"""A fake Hindsight behind an injected request function (build brief 19). The test guards block every real HTTP
call, loopback included, so the router's memory code takes its request function as an argument (main passes
`requests.request`) and tests pass this. It answers the routes the router uses from canned JSON, keeps every
request, and can be told to be offline, slow, refusing or nonsensical per route (decision 12). Not a test file.
Every value here is fake."""
import json as _json

import requests

BANKS = "/v1/default/banks/"


class Reply:
    """What the request function returns: a status code and a body (or raw text that may not be JSON)."""

    def __init__(self, status=200, body=None, raw=None):
        self.status_code = status
        self._body = body
        self._raw = raw

    def json(self):
        if self._raw is not None:
            return _json.loads(self._raw)  # ValueError on bad JSON, as requests raises
        return self._body


class Ticker:
    """A fake clock and sleep: `now()` is the time, `sleep(s)` moves it on and records the call."""

    def __init__(self, start=0.0):
        self.t = float(start)
        self.sleeps = []

    def now(self):
        return self.t

    def sleep(self, seconds):
        self.sleeps.append(seconds)
        self.t += seconds


class FakeHindsight:
    """`online=False`: every request raises a connection error. `online_after=n`: the first n `/health` calls are
    refused, then everything answers (a server still starting). `fail={"recall": "timeout"}` makes one route fail
    one way: "refused", "timeout", an int status, or "bad json". `results=None` derives recall results from the
    retained documents (every chunk is the whole content, type "world"); a list is returned as given."""

    def __init__(self, *, online=True, online_after=0, version="1.0.0", results=None, fail=None, documents=None):
        self.online = online
        self.online_after = online_after
        self.version = version
        self.results = results
        self.fail = dict(fail or {})
        self.requests = []
        self.documents = dict(documents or {})
        self.banks = {}
        self.health_calls = 0

    # ---------- what tests read ----------

    @property
    def client(self):
        """The router's client over this fake (what main builds over requests.request)."""
        from router import memory
        return memory.Client("http://127.0.0.1:8888", "super-router", self.request)

    def of(self, route):
        return [r for r in self.requests if r["route"] == route]

    @property
    def retains(self):
        return [r["json"]["items"][0] for r in self.of("retain")]

    @property
    def recalls(self):
        return [r["json"] for r in self.of("recall")]

    # ---------- the request function ----------

    def request(self, method, url, json=None, timeout=None):
        path = "/" + url.split("://", 1)[1].split("/", 1)[1]
        route = self._route(method, path)
        self.requests.append({"method": method, "path": path, "json": json, "timeout": timeout, "route": route})
        if route == "health":
            self.health_calls += 1
            if not self.online or self.health_calls <= self.online_after:
                raise requests.exceptions.ConnectionError("connection refused")
            return Reply(200, {"status": "ok"})
        if not self.online or (self.online_after and self.health_calls <= self.online_after):
            raise requests.exceptions.ConnectionError("connection refused")
        mode = self.fail.get(route)
        if mode == "refused":
            raise requests.exceptions.ConnectionError("connection refused")
        if mode == "timeout":
            raise requests.exceptions.Timeout("read timed out")
        if isinstance(mode, int):
            return Reply(mode, {"detail": "boom"})
        if mode == "bad json":
            return Reply(200, raw="{not json")
        return self._answer(route, method, path, json)

    @staticmethod
    def _route(method, path):
        if path == "/health":
            return "health"
        if path == "/version":
            return "version"
        if not path.startswith(BANKS):
            return "other"
        rest = path[len(BANKS):]
        bank, _, tail = rest.partition("/")
        if tail == "" and method == "PUT":
            return "bank"
        if tail == "" and method == "DELETE":
            return "delete_bank"
        if tail == "stats":
            return "stats"
        if tail == "tags":
            return "tags"
        if tail == "memories" and method == "POST":
            return "retain"
        if tail == "memories" and method == "DELETE":
            return "clear"
        if tail == "memories/recall":
            return "recall"
        if tail.startswith("documents/") and method == "DELETE":
            return "delete_document"
        if tail.split("?", 1)[0] == "documents" and method == "GET":  # brief 22: the backfill's listing
            return "documents"
        return "other"

    def _answer(self, route, method, path, json):
        bank = path[len(BANKS):].partition("/")[0]
        if route == "version":
            return Reply(200, {"api_version": self.version, "features": {"mcp": True}})
        if route == "bank":
            self.banks[bank] = json
            return Reply(200, {"bank_id": bank, "name": bank, "disposition": {}, "mission": None, "background": None})
        if route == "delete_bank":
            self.banks.pop(bank, None)
            self.documents.clear()
            return Reply(200, {"success": True, "message": "deleted", "deleted_count": 0})
        if route == "stats":
            return Reply(200, {"bank_id": bank, "total_nodes": len(self.documents), "total_links": 0,
                               "total_documents": len(self.documents), "total_observations": 0})
        if route == "tags":
            counts = {}
            for item in self.documents.values():
                for tag in item.get("tags") or []:
                    counts[tag] = counts.get(tag, 0) + 1
            items = [{"tag": t, "count": c} for t, c in sorted(counts.items())]
            return Reply(200, {"items": items, "total": len(items), "limit": 100, "offset": 0})
        if route == "retain":
            for item in json["items"]:
                self.documents[item["document_id"]] = item
            return Reply(200, {"success": True, "bank_id": bank, "items_count": len(json["items"]), "async": False,
                               "usage": {"input_tokens": 0, "output_tokens": 0, "total_tokens": 0}})
        if route == "recall":
            return Reply(200, {"results": self._results(json), "trace": None, "entities": None, "chunks": None,
                               "source_facts": None, "source_facts_truncated": False})
        if route == "documents":
            from urllib.parse import parse_qs, urlsplit
            query = {k: v[0] for k, v in parse_qs(urlsplit(path).query).items()}
            q, limit, offset = query.get("q", ""), int(query.get("limit", 100)), int(query.get("offset", 0))
            ids = [d for d in self.documents if q in d]
            items = [{"id": d, "bank_id": bank, "tags": self.documents[d].get("tags")} for d in ids[offset:offset + limit]]
            return Reply(200, {"items": items, "total": len(ids), "limit": limit, "offset": offset})
        if route == "delete_document":
            document_id = path.rsplit("/", 1)[1]
            gone = self.documents.pop(document_id, None)
            return Reply(200, {"success": True, "document_id": document_id,
                               "memory_units_deleted": 1 if gone is not None else 0})
        if route == "clear":
            n = len(self.documents)
            self.documents.clear()
            return Reply(200, {"success": True, "message": f"deleted {n}", "deleted_count": n})
        return Reply(404, {"detail": "Not Found"})

    def _results(self, body):
        if self.results is not None:
            return list(self.results)
        wanted = set(body.get("tags") or [])
        found = []
        for document_id, item in self.documents.items():
            tags = set(item.get("tags") or [])
            if wanted and not (tags & wanted):
                continue
            found.append(self.result(document_id, item["content"], metadata=item.get("metadata"), tags=sorted(tags)))
        return found

    @staticmethod
    def result(document_id, text, *, metadata=None, tags=(), type_="world", score=0.5):
        """One recall result in Hindsight's shape (the fields the recall page lists)."""
        return {"id": f"fact-{document_id}", "text": text, "type": type_, "context": None, "metadata": metadata,
                "tags": list(tags), "entities": None, "occurred_start": None, "occurred_end": None,
                "mentioned_at": "2026-10-18T00:00:00+00:00", "document_id": document_id,
                "chunk_id": f"chunk-{document_id}", "source_fact_ids": None,
                "scores": {"final": score, "reranker": None, "semantic": score, "keyword": 0.0}}
