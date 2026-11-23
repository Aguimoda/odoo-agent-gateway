-- One-time tickets from the Odoo module (ADR 0021): a ticket is a web session row that
-- only POST /session/redeem can use, once, within 60 seconds; it never works as a cookie.

alter table web_sessions add column if not exists ticket boolean not null default false;
