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

### Prisma Schema Definition

```prisma
generator client {
  provider = "prisma-client-py"
  output   = "../app/database/generated"
}

datasource db {
  provider = "postgresql"
  url      = env("DATABASE_URL")
}

enum Role { ADMIN; TELLER; BORROWER }
enum EntryType { DEBIT; CREDIT }
enum LoanStatus { PENDING; ACTIVE; PAID_OFF; DEFAULTED }

model User {
  id           String   @id @default(uuid())
  email        String   @unique
  username     String   @unique
  full_name    String
  role         Role
  hashed_password String
  is_active    Boolean  @default(true)
  created_at   DateTime @default(now())
  updated_at   DateTime @updatedAt

  customers    Customer[]
}

model Branch {
  id          String   @id @default(uuid())
  name        String   @unique
  address     String?
  created_at  DateTime @default(now())

  customers   Customer[]
}

model Customer {
  id                String   @id @default(uuid())
  customer_type     String
  last_name         String?
  first_name        String?
  display_name      String   @unique
  middle_name       String?
  tin_no            String?
  sss_no            String?
  permanent_address String?
  birth_date        DateTime?
  birth_place       String?
  mobile_number     String?
  email_address     String?
  employer_name_address String?
  job_title         String?
  salary_range      String?
  company_name      String?
  company_address   String?
  branch_id         String
  created_at        DateTime @default(now())
  updated_at        DateTime @updatedAt

  branch            Branch   @relation(fields: [branch_id], references: [id])
  loans             Loan[]
  savings           Savings[]
}

model LoanProduct {
  id          String   @id @default(uuid())
  name        String
  interest_rate Decimal @db.Decimal(5, 2)
  max_amount  Decimal  @db.Decimal(16, 2)
  term_months Int
  created_at  DateTime @default(now())

  loans       Loan[]
}

model Loan {
  id              String     @id @default(uuid())
  customer_id     String
  loan_product_id String
  amount          Decimal    @db.Decimal(16, 2)
  status          LoanStatus @default(PENDING)
  disbursement_date DateTime?
  maturity_date   DateTime?
  created_at      DateTime   @default(now())
  updated_at      DateTime   @updatedAt

  customer        Customer     @relation(fields: [customer_id], references: [id])
  loan_product    LoanProduct  @relation(fields: [loan_product_id], references: [id])
  transactions    LoanTransaction[]
}

model LoanTransaction {
  id          String   @id @default(uuid())
  loan_id     String
  amount      Decimal  @db.Decimal(16, 2)
  payment_date DateTime
  transaction_type String // e.g., "principal", "interest", "penalty"
  notes       String?
  created_at  DateTime @default(now())

  loan        Loan     @relation(fields: [loan_id], references: [id])
}

model LedgerEntry {
  id             String    @id @default(uuid())
  transaction_id String
  account        String
  amount         Decimal   @db.Decimal(16, 2)
  entry_type     EntryType
  timestamp      DateTime  @default(now())
}

model Savings {
  id          String   @id @default(uuid())
  customer_id String
  amount      Decimal  @db.Decimal(16, 2)
  created_at  DateTime @default(now())
  updated_at  DateTime @updatedAt

  customer    Customer @relation(fields: [customer_id], references: [id])
}
```

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
- **Invalidation**: Mutation-to-cache registry maps each mutation to the entity tags it invalidates:

  ```python
  INVALIDATION_MAP = {
      "createLoan":     ["loans", "dashboard"],
      "updateLoan":     ["loans", "dashboard"],
      "deleteLoan":     ["loans", "dashboard"],
      "createCustomer": ["customers", "dashboard"],
      "disburseLoan":   ["loans", "ledger", "dashboard"],
      # ... etc
  }
  ```

  Each cached query declares which entity tags it belongs to (e.g., `get_loans` → `["loans"]`). When a mutation fires, all cache keys tagged with those entities are evicted.

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
**Add:** `prisma`, `asyncpg`, `redis` (v4+, includes asyncio support — no separate aioredis needed)

## Error Handling

- **DB errors**: Prisma's `UniqueViolation` → HTTP 409, `RecordNotFound` → HTTP 404
- **Redis errors**: fail open — serve uncached data if Redis is down
- **Startup checks**:
  - PostgreSQL: required. App fails to start if unreachable.
  - Redis: optional at boot. If unreachable on startup, app starts with caching disabled and logs a warning. If Redis goes down during runtime, queries continue uncached (fail-open).

## Testing

- **Unit tests**: CRUD layer tested against a real PostgreSQL via `testcontainers` (Python testcontainers library spins up ephemeral PostgreSQL + Redis containers per test session)
- **E2E tests**: existing Playwright tests pass unchanged — GraphQL API contract stays the same
- **Integration**: verify cache hit/miss behavior, mutation invalidation using testcontainers Redis

## Data Migration

None required — fresh start with empty database. Seed data for `LoanProduct`, `Branch`, and default `User` roles will be loaded via Prisma seed script on first run.
