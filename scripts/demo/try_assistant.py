"""Talk to the assistant from a terminal, with a real provider. Run from the repository root:

    python scripts/demo/try_assistant.py --provider groq
    python scripts/demo/try_assistant.py --provider groq --user luis "¿Qué pedidos tiene Acme?"

The gateway must be running with the demo settings (including GATEWAY_SECRET_KEYS). The
first time, Carmen (the demo IT administrator) registers the provider through /admin and
you type its API key at a prompt that does not echo; the gateway stores it encrypted and
never shows it again. Then the question is asked as Ana (or --user) and the answer streams
in: tool calls appear in brackets, and a provider failure shows the models you could switch
to. Type more questions to continue the conversation, or an empty line to stop.
"""

from __future__ import annotations

import argparse
import getpass
import json
import sys
from pathlib import Path

import httpx2

from odoo_agent_gateway.evals.agent import PROVIDERS, load_demo_env

ROOT = Path(__file__).resolve().parents[2]


def headers(env: dict[str, str], who: str) -> dict[str, str]:
    return {
        "x-odoo-login": env[f"DEMO_{who.upper()}_LOGIN"],
        "authorization": f"Bearer {env[f'DEMO_{who.upper()}_API_KEY']}",
    }


def ensure_provider(http: httpx2.Client, env: dict[str, str], name: str) -> int:
    """Make sure the provider and its model exist; return the model id."""
    admin = headers(env, "carmen")
    response = http.get("/admin/providers", headers=admin)
    if response.status_code != 200:
        sys.exit(f"Admin API answered {response.status_code}: {response.text[:300]}")
    preset = PROVIDERS[name]
    provider = next((p for p in response.json()["providers"] if p["name"] == name), None)
    if provider is None or not provider["key_set"] or provider["status"] == "auth_failed":
        key = getpass.getpass(f"{name} API key (not shown): ").strip()
        if not key:
            sys.exit("No API key given.")
        if provider is None:
            body = {"name": name, "base_url": preset["base_url"], "api_key": key}
            provider = http.post("/admin/providers", json=body, headers=admin).json()
        else:
            path = f"/admin/providers/{provider['id']}"
            provider = http.patch(path, json={"api_key": key}, headers=admin).json()
        tested = http.post(f"/admin/providers/{provider['id']}/test", headers=admin).json()
        print("Connection test:", "ok" if tested.get("ok") else tested)
    model = next((m for m in provider["models"] if m["name"] == preset["model"]), None)
    if model is None:
        view = http.post(
            f"/admin/providers/{provider['id']}/models",
            json={"name": preset["model"], "is_default": True},
            headers=admin,
        ).json()
        model = next(m for m in view["models"] if m["name"] == preset["model"])
    return model["id"]


def ask(http: httpx2.Client, env, who: str, conversation: str, text: str, model_id: int) -> None:
    path = f"/agent/conversations/{conversation}/messages"
    body = {"content": text, "model_id": model_id}
    with http.stream("POST", path, json=body, headers=headers(env, who), timeout=180) as response:
        if response.status_code != 200:
            print(f"\n[{response.status_code}] {response.read().decode()[:300]}")
            return
        kind = None
        for line in response.iter_lines():
            if line.startswith("event: "):
                kind = line[7:]
            elif line.startswith("data: "):
                show(kind, json.loads(line[6:]))
    print()


def show(kind: str | None, data: dict) -> None:
    if kind == "token":
        print(data["text"], end="", flush=True)
    elif kind == "tool_call":
        print(f"\n[{data['name']} {json.dumps(data['arguments'], ensure_ascii=False)}]")
    elif kind == "tool_result":
        print(f"[{'ok' if data['ok'] else 'error'}, {data['count']} result(s)]")
    elif kind == "proposal":
        print(f"\n[proposal {data['proposal_id']}: {data['status']}]")
    elif kind == "notice":
        print(f"\n[{data['message']}]")
    elif kind == "error":
        print(f"\n[{data['kind']}] {data['message']}")
        if data.get("retry_after"):
            print(f"Retry in about {round(data['retry_after'])} s.")
        for model in data.get("alternatives") or []:
            print(f"  or switch to {model['provider']} / {model['label']} (model id {model['id']})")


def main() -> None:
    parser = argparse.ArgumentParser(description="Talk to the assistant as a demo user.")
    parser.add_argument("question", nargs="?", default="¿Cuál es el plazo de envío?")
    parser.add_argument("--provider", choices=sorted(PROVIDERS), default="groq")
    parser.add_argument("--user", choices=["ana", "luis"], default="ana")
    parser.add_argument("--gateway", default="http://127.0.0.1:8000")
    args = parser.parse_args()
    sys.stdout.reconfigure(encoding="utf-8")

    env = load_demo_env({}, ROOT / ".env.demo-keys")
    with httpx2.Client(base_url=args.gateway, timeout=60) as http:
        model_id = ensure_provider(http, env, args.provider)
        created = http.post("/agent/conversations", json={}, headers=headers(env, args.user))
        conversation = created.json()["id"]
        question = args.question
        while question:
            print(f"\n{args.user}> {question}\n")
            ask(http, env, args.user, conversation, question, model_id)
            question = input(f"\n{args.user}> ").strip()


if __name__ == "__main__":
    main()
