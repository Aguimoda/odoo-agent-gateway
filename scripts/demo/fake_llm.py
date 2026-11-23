"""A scripted, OpenAI-compatible model for demos and browser tests. No real AI, no network.

    python scripts/demo/fake_llm.py            # listens on 127.0.0.1:8090

Register it in the admin panel with any key and one of these base URLs:

    http://127.0.0.1:8090/good/v1      answers, using one tool first
    http://127.0.0.1:8090/limited/v1   always "429 rate limited", retry after 20 s
    http://127.0.0.1:8090/down/v1      always "503 unavailable"

The good one picks a tool from the question (orders -> search_records, permissions ->
my_permissions, anything else -> search_knowledge), then writes a short answer from what
the tool returned, streamed word by word. It is deterministic, so tests can rely on it.
"""

from __future__ import annotations

import argparse
import json
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any

MODELS = ["scripted-mini", "scripted-large"]
WORD_DELAY = 0.025


def choose_tool(question: str) -> tuple[str, dict[str, Any]]:
    text = question.lower()
    if any(word in text for word in ("pedido", "order", "venta", "sale")):
        fields = ["name", "partner_id", "amount_total", "state"]
        return "search_records", {"model": "sale.order", "fields": fields, "limit": 5}
    if any(word in text for word in ("permis", "puedo", "can i", "what can")):
        return "my_permissions", {}
    return "search_knowledge", {"query": question.strip()[:200], "limit": 3}


def first_list(value: Any) -> list[Any]:
    if isinstance(value, list):
        return value
    if isinstance(value, dict):
        for item in value.values():
            if isinstance(item, list):
                return item
    return []


def describe(item: Any) -> str:
    if not isinstance(item, dict):
        return str(item)[:120]
    name = item.get("name") or item.get("title") or item.get("display_name") or item.get("model")
    if isinstance(name, list) and len(name) == 2:
        name = name[1]
    partner = item.get("partner_id")
    if isinstance(partner, list) and len(partner) == 2:
        name = f"{name} ({partner[1]})"
    text = item.get("text") or item.get("snippet") or ""
    source = item.get("source") or item.get("ref") or ""
    line = f"**{name}**" if name else ""
    if text:
        line += (": " if line else "") + " ".join(str(text).split())[:160]
    if source and isinstance(source, str):
        line += f" ({source})"
    return line or json.dumps(item, ensure_ascii=False)[:120]


def answer_from(tool_name: str, content: str, spanish: bool) -> str:
    try:
        data = json.loads(content)
    except ValueError:
        data = None
    if content.startswith("Error") or data is None:
        return (
            "No he podido consultarlo con tus permisos." if spanish else "I could not look it up."
        )
    items = first_list(data)
    if tool_name == "my_permissions" and isinstance(data, dict):
        areas = first_list(data.get("models") or data)
        head = "Esto es lo que puedes ver en Odoo:" if spanish else "This is what you can see:"
        lines = [describe(a) for a in areas[:6]]
        if not lines:
            return (
                "No puedes leer ninguna de las áreas que expone el gateway."
                if spanish
                else "You cannot read any of the areas this gateway exposes."
            )
        return head + "\n\n" + "\n".join(f"- {line}" for line in lines)
    if not items:
        return (
            "No lo he encontrado en lo que puedes ver."
            if spanish
            else "I could not find it in what you can see."
        )
    head = (
        f"He encontrado {len(items)} resultado(s) con tus permisos:"
        if spanish
        else f"I found {len(items)} result(s) with your permissions:"
    )
    return head + "\n\n" + "\n".join(f"- {describe(item)}" for item in items[:5])


def is_spanish(text: str) -> bool:
    return any(ch in text for ch in "¿¡ñáéíóú") or any(
        word in text.lower().split() for word in ("qué", "que", "cuál", "el", "de", "los")
    )


class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def log_message(self, format: str, *args: Any) -> None:  # quiet
        return

    def _kind(self) -> str:
        return self.path.strip("/").split("/", 1)[0]

    def _json(self, status: int, body: Any, headers: dict[str, str] | None = None) -> None:
        payload = json.dumps(body).encode()
        self.send_response(status)
        self.send_header("content-type", "application/json")
        self.send_header("content-length", str(len(payload)))
        for key, value in (headers or {}).items():
            self.send_header(key, value)
        self.end_headers()
        self.wfile.write(payload)

    def _authorized(self) -> bool:
        scheme, _, key = self.headers.get("authorization", "").partition(" ")
        if scheme.lower() != "bearer" or not key.strip():
            self._json(401, {"error": {"message": "Invalid API Key"}})
            return False
        return True

    def do_GET(self) -> None:
        if not self.path.endswith("/models"):
            self._json(404, {"error": {"message": "not found"}})
        elif self._authorized():
            self._json(200, {"data": [{"id": m, "object": "model"} for m in MODELS]})

    def do_POST(self) -> None:
        length = int(self.headers.get("content-length") or 0)
        body = json.loads(self.rfile.read(length) or b"{}")
        if not self.path.endswith("/chat/completions"):
            self._json(404, {"error": {"message": "not found"}})
            return
        if not self._authorized():
            return
        kind = self._kind()
        if kind == "limited":
            self._json(
                429,
                {"error": {"message": "Rate limit reached for requests per minute."}},
                {"retry-after": "20"},
            )
            return
        if kind == "down":
            self._json(503, {"error": {"message": "Service unavailable"}})
            return
        self._stream(body)

    def _chunk(self, data: dict[str, Any]) -> None:
        payload = f"data: {json.dumps(data, ensure_ascii=False)}\n\n".encode()
        self.wfile.write(f"{len(payload):x}\r\n".encode() + payload + b"\r\n")
        self.wfile.flush()

    def _stream(self, body: dict[str, Any]) -> None:
        messages = body.get("messages") or []
        last = messages[-1] if messages else {}
        question = next(
            (m.get("content") or "" for m in reversed(messages) if m.get("role") == "user"), ""
        )
        self.send_response(200)
        self.send_header("content-type", "text/event-stream")
        self.send_header("transfer-encoding", "chunked")
        self.end_headers()

        if last.get("role") == "tool" or not body.get("tools"):
            tool_name = next(
                (
                    call["function"]["name"]
                    for m in reversed(messages)
                    for call in (m.get("tool_calls") or [])
                ),
                "",
            )
            text = answer_from(tool_name, last.get("content") or "", is_spanish(question))
            words = text.split(" ")
            for index, word in enumerate(words):
                piece = word if index == len(words) - 1 else word + " "
                self._chunk({"choices": [{"delta": {"content": piece}}]})
                time.sleep(WORD_DELAY)
            self._chunk(
                {
                    "choices": [{"delta": {}, "finish_reason": "stop"}],
                    "usage": {"prompt_tokens": 120, "completion_tokens": len(words)},
                }
            )
        else:
            name, arguments = choose_tool(question)
            call = {
                "index": 0,
                "id": "call-1",
                "type": "function",
                "function": {"name": name, "arguments": json.dumps(arguments, ensure_ascii=False)},
            }
            time.sleep(0.2)
            self._chunk({"choices": [{"delta": {"tool_calls": [call]}}]})
        self._chunk_raw(b"data: [DONE]\n\n")
        self.wfile.write(b"0\r\n\r\n")
        self.wfile.flush()

    def _chunk_raw(self, payload: bytes) -> None:
        self.wfile.write(f"{len(payload):x}\r\n".encode() + payload + b"\r\n")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8090)
    args = parser.parse_args()
    server = ThreadingHTTPServer((args.host, args.port), Handler)
    print(f"Scripted model on http://{args.host}:{args.port}/good/v1 (also /limited, /down)")
    server.serve_forever()


if __name__ == "__main__":
    main()
