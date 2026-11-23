# 15. Provider keys encrypted and bound to their URL; administrators decided by an Odoo group

Date: 2026-11-23. Status: accepted.

## Context

The gateway now calls language-model providers itself (ADR 0016), so it must hold their API keys. Those keys are worth money and quota, and leaking one is the most likely serious incident of this milestone. Someone also has to configure providers, and the gateway has no user accounts of its own: Odoo decides who people are and what they may do (ADR 0002).

## Decision

**Keys**
- Stored encrypted with AES-256-GCM. The master keys come only from the server environment (`GATEWAY_SECRET_KEYS`, comma-separated, the first one encrypts, the others still decrypt for rotation). They are never in the database or the repository. Each ciphertext carries the id of its master key (the first bytes of its SHA-256), a random nonce and a version byte.
- The provider's normalised base URL is the GCM **associated data**. A ciphertext only decrypts for the URL it was entered for, so someone who can change rows in the database cannot point a stored key at a server of their own. Through the API, changing a provider's URL requires typing the key again.
- Write-only: the API reports whether a key is set and when it was last changed, never the key or part of it. The audit log stores `api_key` as `"***"` when one was sent.
- Without `GATEWAY_SECRET_KEYS` the provider and agent APIs answer `providers_unavailable`; the rest of the gateway works as before.
- Base URLs must be `https`, except loopback hosts and hosts listed in `GATEWAY_LOCAL_PROVIDER_HOSTS` (for a local model in the same Docker network). Redirects are never followed, so a key is only sent to the configured host.

**Administrators**
- A caller is an administrator when Odoo answers `res.users.has_group(GATEWAY_ADMIN_GROUP)` as that same caller, with their own key. The default group is `base.group_system` (Settings). It was checked against the demo: the admin is in it; Luis, a sales manager, and Ana are not.
- Admin calls take the same `Gateway.execute` path as everything else: rate limit, credentials checked by Odoo, fail-closed audit.
- Administrators configure providers and see usage, never other people's conversations.

## Consequences

- A database dump without the environment does not expose provider keys; a stolen dump plus write access still cannot redirect a key.
- Losing every master key means re-entering provider keys. Nothing else is lost.
- Rotation: put the new master key first, re-save each provider's key (or let it be re-encrypted on its next save), then drop the old master key.
- One extra Odoo call per admin request; admin requests are rare.
