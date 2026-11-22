# 7. MCP over stateless streamable HTTP, with host protection on

Date: 2026-11-22. Status: accepted.

## Context

The gateway must be reachable by remote MCP clients and must read per-request headers (ADR 0005). The official Python SDK (`mcp`, version 2.3) offers stdio, SSE and streamable HTTP transports. Its HTTP transport validates the `Host` header to block DNS rebinding attacks.

## Decision

- Expose MCP over **streamable HTTP** at `/mcp`, mounted in the FastAPI application next to `/health`.
- Run it **stateless** with JSON responses: every request stands alone and re-authenticates against Odoo, which fits ADR 0005 and lets the gateway scale horizontally.
- Keep the SDK's **host validation enabled**. Allowed hosts are configured explicitly for each deployment.

## Consequences

- No server-side MCP sessions to store or expire.
- Server-initiated messages (notifications, streaming progress) are not available in this mode. The read tools do not need them.
- Tests must call the app with an allowed host (`127.0.0.1`).
