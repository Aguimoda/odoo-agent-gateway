"""Build the knowledge index (ADR 0011). Runs separately from the gateway:

    python -m odoo_agent_gateway.index --docs scripts/demo/knowledge

Environment: ODOO_URL, ODOO_DB, GATEWAY_DATABASE_URL, and for records INDEXER_LOGIN and
INDEXER_API_KEY (a dedicated read-only Odoo user, never the gateway's callers). Optional
GATEWAY_MODEL_CACHE (default .cache/models). Prints counts only, never credentials.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

import anyio
import httpx2

from odoo_agent_gateway.embeddings import FastEmbedEmbedder
from odoo_agent_gateway.indexer import Indexer
from odoo_agent_gateway.knowledge_store import PostgresKnowledgeStore
from odoo_agent_gateway.odoo import OdooClient


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="Build the Odoo Agent Gateway knowledge index.")
    parser.add_argument("--docs", type=Path, help="folder of Markdown documents to index")
    parser.add_argument("--no-records", action="store_true", help="skip Odoo records")
    args = parser.parse_args(argv)

    required = ["ODOO_URL", "ODOO_DB", "GATEWAY_DATABASE_URL"]
    if not args.no_records:
        required += ["INDEXER_LOGIN", "INDEXER_API_KEY"]
    missing = [name for name in required if not os.environ.get(name)]
    if missing:
        sys.exit(f"Missing environment variables: {', '.join(missing)}")
    if args.docs and not args.docs.is_dir():
        sys.exit(f"Not a folder: {args.docs}")

    stats = anyio.run(_run, args.docs, not args.no_records)
    print(json.dumps(stats, indent=2))


async def _run(docs: Path | None, records: bool) -> dict:
    env = os.environ
    store = PostgresKnowledgeStore(env["GATEWAY_DATABASE_URL"])
    embedder = FastEmbedEmbedder(cache_dir=env.get("GATEWAY_MODEL_CACHE", ".cache/models"))
    await store.start()
    stats: dict = {}
    try:
        async with httpx2.AsyncClient(timeout=60) as http:
            client = OdooClient(env["ODOO_URL"], env["ODOO_DB"], http)
            session = None
            if records:
                session = await client.authenticate(env["INDEXER_LOGIN"], env["INDEXER_API_KEY"])
            indexer = Indexer(store, embedder, session)
            if docs:
                stats["documents"] = await indexer.index_documents(docs)
            if records:
                stats["records"] = await indexer.index_records()
    finally:
        await store.close()
    return stats


if __name__ == "__main__":
    main()
