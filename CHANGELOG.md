# Changelog

All notable changes are recorded here. The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/) and the project uses [Semantic Versioning](https://semver.org/).

## [Unreleased]

### Added

- Specification, tool catalogue and architecture decision records (ADR 0001 to 0004).
- Python project with FastAPI, an application factory and a `GET /health` endpoint, written test-first.
- Docker Compose stack: Odoo 18, its PostgreSQL, and a separate PostgreSQL with pgvector for the gateway.
- GitHub Actions workflow: lint and tests on Python 3.11 and 3.12, Compose validation, secret scan.
