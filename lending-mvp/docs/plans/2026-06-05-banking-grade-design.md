# Banking-Grade Hardening — Design

**Date:** 2026-06-05
**Scope:** P0 (Stop the bleeding) + P1 (DB integrity) on the lending-mvp stack
**Status:** Approved by user — ready for TDD implementation

## Goal

Bring `lending-mvp` from "demo with a few critical holes" to "defensible for a single-tenant, single-currency, audit-grade internal banking tool" — without breaking the working dev experience.

## Non-Goals (YAGNI)

- Full RBAC perm-graph (extend `require_roles` only)
- Service mesh / multi-currency / real credit-bureau integration
- Event bus / Kafka (we use a `outbox` table)
- Mobile app (web-responsive only)

## Architecture

Four coordinated lanes (per the audit reports):

1. **Backend** — single `post_journal()` writer, `SELECT FOR UPDATE` + `SERIALIZABLE` on money paths, `idempotency_key UNIQUE` columns, daily loan-interest accrual cron, monthly loss-provision cron, httpOnly cookies + CSRF, login rate-limit, security headers, Pydantic length caps.
2. **Database** — `Numeric(15,2)` everywhere money is stored, `CHECK (amount >= 0)`, `CHECK (debit=0 OR credit=0)`, per-journal balance trigger, soft-delete via `deleted_at`, drop dead models (`pg_core_models.Loan`, `Transaction`, `LedgerEntry`, `InterestLedger`), drop MongoDB `savings` dual-store.
3. **DevOps** — TLS+HSTS at nginx, security headers at edge, nginx `limit_req_zone`, secrets out of repo, container non-root, DB TLS, environment-gated demo seed.
4. **QA** — race tests, idempotency tests, RBAC tests, login-limit tests, audit-log tests, accrual tests, provision tests, e2e (Playwright), 80% coverage gate.

## Feature Flag

All P0/P1 changes gate behind `BANKING_GRADE_MODE` env var (default `false` until P3 ships):

```python
# app/feature_flags.py
from functools import lru_cache
from pydantic_settings import BaseSettings

class FeatureFlags(BaseSettings):
    banking_grade_mode: bool = False   # P0+P1 — DB constraints, idempotency, locks
    banking_grade_frontend: bool = False  # P3 — gradient refresh

flags = FeatureFlags()
```

## Data Model Changes

- `loan_transactions.idempotency_key VARCHAR(64) UNIQUE`
- `savings_transactions.idempotency_key VARCHAR(64) UNIQUE`
- `aml_alerts.ctr_amount` → `Numeric(15,2)` (was Float)
- `collections.amount` → `Numeric(15,2)` (was Float)
- `customers.email_address` → UNIQUE
- `customers.mobile_number` → UNIQUE
- All financial tables → `deleted_at TIMESTAMPTZ NULL` (soft-delete)
- All business tables → `created_by`, `updated_by` (`BigInteger FK users.id`)
- `journal_lines` → `CHECK (debit = 0 OR credit = 0)`, `CHECK (debit >= 0 AND credit >= 0)`
- `journal_lines` → AFTER INSERT/UPDATE trigger asserting per-entry `SUM(debit) = SUM(credit)`
- `password_history(user_id, created_at DESC)` → composite index

Drop:
- `pg_core_models.Loan` (Phase 1 dead schema)
- `pg_core_models.Transaction`, `pg_core_models.LedgerEntry` (orphaned)
- `pg_core_models.InterestLedger` (unused)
- MongoDB `savings` collection usage in `savings_crud.py`

## API / Behavior Changes

- `POST /api-login/` returns tokens as `Set-Cookie` httpOnly + sets `csrf_token` cookie; body no longer contains tokens
- Login rate-limit: 5 failed attempts per username per 15 min → progressive lockout
- CORS: `allow_origins` from `CORS_ORIGINS` env (JSON list); default `["http://localhost:3010"]`
- All GraphQL mutations accept `idempotencyKey: String`; return prior result on replay
- `GET /api/users` requires admin role
- `mutation createUser` requires admin role (was open)
- `mutation updateUser` blocks self-role-change
- Security headers on every response: `X-Content-Type-Options: nosniff`, `X-Frame-Options: DENY`, `Referrer-Policy: strict-origin-when-cross-origin`, `Content-Security-Policy: default-src 'self'; frame-ancestors 'none'`
- TLS at the edge (nginx 443 + redirect 80→443) — staged but optional in dev

## Phased Rollout

| Phase | Scope | Risk | Approx LoC |
|---|---|---|---|
| P0 | Stop the bleeding (security + auth + broken imports) | High | ~700 |
| P1 | DB integrity (constraints, migrations, dead-code purge) | Low (additive) | ~900 |

## TDD Approach

For each task:
1. Write a failing test that proves the bug
2. Run the test — confirm it fails for the right reason
3. Apply the minimum fix
4. Run the test — confirm it passes
5. Commit with a conventional message (`fix:`, `feat:`, `test:`, `chore:`)

Coverage gate: `pytest --cov=app --cov-fail-under=80` once P0+P1 land.

## Subagent Delegation

- **Group A — Auth/Sec/RBAC/Accounting** (single `general` subagent)
- **Group B — Teller cleanup + feature flag** (single `general` subagent)
- **Group C — DB integrity migrations** (single `general` subagent)
- **Group D — DB cleanup** (single `general` subagent)

Each subagent receives: (a) the audit findings for its scope, (b) the test conventions from `tests/conftest.py`, (c) the TDD order, (d) the commit-message convention. Each reports back with: tests added, fixes applied, files changed, commits made, residual risk.

## Verification

- `pytest -x` passes
- `docker compose up -d --build` succeeds
- `curl -X POST http://localhost:3010/api-login/ -H "Content-Type: application/json" -d '{"username":"admin","password":"Admin@123Demo"}'` returns 200 with `Set-Cookie` headers
- `curl http://localhost:3010/api/users` without cookie → 401
- `psql` query `SELECT conname FROM pg_constraint WHERE contype='c'` returns ≥ 5 rows
