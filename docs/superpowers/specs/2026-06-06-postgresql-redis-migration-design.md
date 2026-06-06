# MongoDB → PostgreSQL + Redis Migration Design

**Date:** 2026-06-06  
**Status:** Approved  
**Approach:** Full rewrite — replace MongoDB entirely with PostgreSQL + Prisma + Redis

---

## Architecture

```
┌─────────────────────────────────┐
│  Frontend-React (Vite, React)    │  :5173 / :8080
│  Apollo Client → /graphql        │
└──────────────┬──────────────────┘
               │
┌──────────────▼──────────────────┐
│  Backend (FastAPI + Strawberry) │  :8000
│  ┌───────────────────────────┐  │
│  │ Redis Caching Middleware   │  │  ← caches query results by hash+TTL
│  └─────────────┬─────────────┘  │
│                │                 │
│  ┌─────────────▼─────────────┐  │
│  │ Prisma Client (async)     │  │  ← type-safe DB queries
│  └─────────────┬─────────────┘  │
└────────────────┼────────────────┘
                 │
      ┌──────────┴──────────┐
      │   PostgreSQL        │  :5432
      └─────────────────────┘
```

## Prisma Schema

### Collections → Tables Mapping

| MongoDB Collection | PostgreSQL Table | Key Changes |
|---|---|---|
| `users` | `User` | `_id` (ObjectId) → `id` (UUID), timestamps as `timestamptz` |
| `customers` | `Customer` | FK to `Branch`, unique on `display_name` |
| `loans` | `Loan` | FK to `Customer`, `LoanProduct` |
| `loan_transactions` | `LoanTransaction` | FK to `Loan`, `payment_date` as `date` |
| `loan_products` | `LoanProduct` | interest rate as `decimal` |
| `ledger_entries` | `LedgerEntry` | `amount` as `decimal(16,2)`, `entry_type` as enum |
| savings (implied) | `Savings` | FK to `Customer` |

### Key Decisions

- **UUIDs** for all primary keys (standard PostgreSQL pattern, replaces MongoDB ObjectIds)
- **Foreign keys** enforce referential integrity (MongoDB had none)
- **Enums** for `entry_type` (debit/credit), `role`, `loan_status` — type safety at DB level
- **Timestamps** as `timestamptz` with DB-level defaults (`DEFAULT NOW()`)

## Redis Caching Strategy

### Approach

Per-resolver decorator pattern — cache applied individually to each query resolver:

```python
@cache(ttl=60)  # cache for 60 seconds
async def get_customers(info):
    ...
```

### Details

- **Cache key**: SHA-256 of (query string + variables) — deterministic per request
- **TTLs**:
  - 60s for list queries (customers, loans, etc.)
  - 300s for dashboard/aggregated data
  - 0 for mutations (not cached)
- **Invalidation**: On any mutation, invalidate all caches for affected entity types
  - e.g., `createLoan` invalidates `Loan*` and `Dashboard*` caches
- **Connection pool**: shared Redis connection via `redis.asyncio.from_url`

### Fail-open Behavior

If Redis is down, queries serve uncached data from the database. No crash, no downtime. Cache errors are logged but not propagated to the client.

## File Structure Changes

```
backend/app/
├── main.py                    # unchanged (startup, CORS, routes)
├── config.py                  # DATABASE_URL → DB_URL + REDIS_URL
├── models.py                  # remove PyObjectId, keep Pydantic models (no _id alias)
│
├── database/                  # ← REPLACE entirely
│   ├── __init__.py            # motor client → prisma client init
│   ├── crud.py                # motor queries → prisma queries
│   ├── customer_crud.py
│   ├── loan_crud.py
│   ├── loan_product_crud.py
│   ├── loan_transaction_crud.py
│   ├── savings_crud.py
│   └── transaction_crud.py
│
├── cache/                     # ← NEW
│   ├── __init__.py            # redis connection
│   └── decorators.py          # @cache decorator + invalidation
│
├── user.py                    # GraphQL resolvers — update to use new CRUD
├── customer.py                # same
├── loan.py                    # same
├── loan_transaction.py        # same
├── loan_product.py            # same
├── savings.py                 # same
└── transaction.py             # same
```

### New Files

- `backend/prisma/schema.prisma` — Prisma schema definition
- `backend/app/cache/__init__.py` — Redis connection setup
- `backend/app/cache/decorators.py` — `@cache` decorator and invalidation logic

### Dependencies

**Remove:** `motor`, `pymongo`, `bson`  
**Add:** `prisma`, `asyncpg`, `redis`, `aioredis`

## Error Handling

- **DB errors**: Prisma's `UniqueViolation` → HTTP 409, `RecordNotFound` → HTTP 404
- **Redis errors**: fail open — serve uncached data if Redis is down
- **Connection errors**: FastAPI startup event checks both PostgreSQL and Redis connectivity; fails fast if either is unreachable

## Testing

- **Unit tests**: CRUD layer with Prisma test adapter
- **E2E tests**: existing Playwright tests pass unchanged — GraphQL API contract stays the same
- **Integration**: verify cache hit/miss behavior, mutation invalidation

## Data Migration

None required — fresh start with empty database.
