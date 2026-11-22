# 1. Record architecture decisions

Date: 2026-11-22. Status: accepted.

## Context

The project makes security-relevant choices (how the agent authenticates, what it may do, where data lives). Those choices must be explainable to a reviewer months later, and they must not live only in someone's head or in chat history.

## Decision

Every significant decision gets a short Architecture Decision Record in `docs/adr/`, numbered in order, with Context, Decision and Consequences. A record is never rewritten: if a decision changes, a new record supersedes the old one.

## Consequences

- A reviewer can read the reasoning behind the design in a few minutes.
- Writing a record forces the alternatives to be named before code is written.
- There is a small cost per decision, accepted on purpose.
