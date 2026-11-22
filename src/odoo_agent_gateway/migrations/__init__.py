"""SQL migrations for the gateway database, applied in order on start.

Every file is idempotent, so applying all of them on each start is safe. A transaction-level
advisory lock keeps several gateway processes from applying them at the same time.
"""

from __future__ import annotations

from importlib import resources

import asyncpg

_LOCK_KEY = 7_202_611  # arbitrary, fixed: identifies "odoo-agent-gateway migrations"


def migration_files() -> list[tuple[str, str]]:
    folder = resources.files(__name__)
    names = sorted(entry.name for entry in folder.iterdir() if entry.name.endswith(".sql"))
    return [(name, folder.joinpath(name).read_text(encoding="utf-8")) for name in names]


async def apply_migrations(connection: asyncpg.Connection) -> list[str]:
    applied = []
    async with connection.transaction():
        await connection.execute("select pg_advisory_xact_lock($1)", _LOCK_KEY)
        for name, sql in migration_files():
            await connection.execute(sql)
            applied.append(name)
    return applied
