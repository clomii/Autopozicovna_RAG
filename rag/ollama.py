"""Small localhost-only Ollama client. No account, API key or external endpoint."""
from __future__ import annotations

import json
import os
import re
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit
from urllib.request import (HTTPRedirectHandler, ProxyHandler, Request, build_opener)


class ModelError(RuntimeError):
    def __init__(self, message, status=None):
        super().__init__(message)
        self.status = status


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise ModelError("Lokálny Ollama server sa pokúsil o presmerovanie.")


class Ollama:
    def __init__(self):
        self.url = os.getenv("RAG_OLLAMA_URL", "http://127.0.0.1:11434").rstrip("/")
        u = urlsplit(self.url)
        if (u.scheme != "http" or u.hostname not in {"localhost", "127.0.0.1", "::1"}
                or u.username or u.password or u.path or u.query or u.fragment):
            raise ValueError("RAG_OLLAMA_URL musí byť adresa HTTP na localhost.")
        self.chat_model = os.getenv("RAG_CHAT_MODEL", "qwen3:4b-instruct-2507-q4_K_M")
        self.embed_model = os.getenv("RAG_EMBED_MODEL", "qwen3-embedding:0.6b")
        for name in (self.chat_model, self.embed_model):
            if not re.fullmatch(r"[A-Za-z0-9_.:/-]{1,120}", name) or "cloud" in name.lower():
                raise ValueError("Použi názov stiahnutého lokálneho modelu bez cloudovej značky.")
        self.opener = build_opener(ProxyHandler({}), NoRedirect())

    def call(self, endpoint, payload=None, timeout=5):
        raw = json.dumps(payload, ensure_ascii=False).encode("utf-8") if payload is not None else None
        req = Request(self.url + endpoint, data=raw, headers={"Content-Type": "application/json"})
        try:
            with self.opener.open(req, timeout=timeout) as response:
                data = json.load(response)
        except HTTPError as exc:
            raise ModelError(f"Ollama vrátila HTTP {exc.code}.", exc.code) from exc
        except (URLError, TimeoutError, OSError, ValueError) as exc:
            raise ModelError("Lokálna Ollama neodpovedá alebo je model zaneprázdnený.") from exc
        if not isinstance(data, dict) or data.get("error"):
            raise ModelError("Ollama nevrátila očakávané údaje.")
        return data

    def tags(self):
        try:
            result = self.call("/api/tags", timeout=2.5)
        except ModelError:
            return False, {}
        local = {}
        for m in result.get("models", []):
            name = m.get("name") or m.get("model")
            if (name and m.get("size", 0) > 0 and "cloud" not in name.lower()
                    and not m.get("remote_host") and not m.get("remote_model")):
                local[name] = m.get("digest", name)
        return True, local

    def embed(self, texts):
        data = self.call("/api/embed", {
            "model": self.embed_model, "input": texts, "truncate": False, "keep_alive": "5m",
        }, timeout=180)
        result = data.get("embeddings")
        if not isinstance(result, list) or len(result) != len(texts):
            raise ModelError("Nesedí počet vektorov z Ollamy.")
        return result

    def answer(self, system, prompt, schema):
        body = {
            "model": self.chat_model, "stream": False, "think": False,
            "format": schema, "keep_alive": "5m",
            "messages": [{"role": "system", "content": system}, {"role": "user", "content": prompt}],
            "options": {"temperature": 0, "seed": 42, "num_ctx": 4096, "num_predict": 340},
        }
        try:
            data = self.call("/api/chat", body, timeout=240)
        except ModelError as exc:
            if exc.status not in (500, 503):
                raise
            # A local runner may restart under memory pressure. Retry once.
            data = self.call("/api/chat", body, timeout=240)
        if data.get("done_reason") == "length":
            raise ModelError("Odpoveď modelu sa nezmestila do limitu.")
        try:
            result = json.loads(data["message"]["content"])
        except (KeyError, TypeError, ValueError) as exc:
            raise ModelError("Model nevrátil čitateľnú štruktúrovanú odpoveď.") from exc
        if not isinstance(result, dict):
            raise ModelError("Model nevrátil štruktúrovaný objekt.")
        return result
