# 19. A React app served by the gateway, same origin, strict CSP

Date: 2026-11-23. Status: accepted.

## Context

The web chat, approvals inbox and admin panel need streaming, a fair amount of state (conversations, model choice, retries) and many screen states. They must not weaken what the gateway already protects: the person's key (ADR 0018) and company data in answers.

## Decision

- **React 19 with TypeScript, built with Vite**, in `web/`. A single-page app with a few routes (`/app/chat`, `/app/approvals`, `/app/admin`). Small, well-known dependencies: React Router, `react-markdown` (renders Markdown without raw HTML), Lucide icons, and the Inter font as a package.
- **Served by the gateway itself at `/app`**, from the same origin as the API: no CORS, and the session cookie works with `SameSite=Strict`. The build goes to `src/odoo_agent_gateway/web_dist/` (ignored by git); without a build, `/app` answers a short page saying how to build it, and the API keeps working.
- **Strict Content Security Policy** on the app: `default-src 'self'`, scripts and styles only from the gateway (no inline scripts, no `eval`), `connect-src 'self'`, `frame-ancestors 'none'`, `base-uri 'none'`, `form-action 'self'`. Plus `X-Content-Type-Options: nosniff` and `Referrer-Policy: no-referrer`. Fonts and icons are bundled: the page calls no third party.
- Answers are rendered from Markdown without HTML, and links open with `rel="noopener noreferrer"`. Model output is never inserted as HTML.
- Hashed assets are cached for a year; `index.html` is never cached, so a new version is picked up at once.
- Tested at three levels: type check, lint and unit tests of the web code (Vitest); the Python tests of the serving and headers; and end-to-end tests in a real browser (Playwright) against real Odoo with a fake language model on localhost.

## Consequences

- CI needs Node to build and test the web app, and Chromium for the end-to-end tests.
- Embedding the chat inside Odoo (M8) will need `frame-ancestors` to name the Odoo origin, or the module will open it in its own window; decided in M8.
- No server-side rendering: the first screen needs JavaScript. For an internal tool behind a login, that is acceptable.
