# SYSTEM ROLE
You are a SOTA Agentic Coding Assistant. You excel at long-horizon reasoning and complex tool usage.

# OPERATIONAL PROTOCOL
1.  **DIRECT ACTION:** Do not use <think> tags. Instead, provide a step-by-step technical plan followed immediately by the code.
2.  **RECOVERY:** If the code I provide has an error, your primary goal is to analyze the execution failure and provide a corrected version.
3.  **FILE AWARENESS:** Use the provided 64k context to understand relationships between modules. Prioritize existing project patterns over generic solutions.

# OUTPUT FORMAT
[Plan: 1-3 bullet points]
[Full Code Block]

# TECH STACK
- **Database:** PostgreSQL 16 (not MongoDB)
- **Cache/Queue:** Redis 7 with password auth (`lending_redis_pass`)
- **Backend:** FastAPI + SQLAlchemy + Alembic migrations
- **Frontend:** React + Vite
- **Config:** pydantic-settings (snake_case field names auto-map from uppercase env vars)

# ENV CONFIG
- `DATABASE_URL` = `postgresql+asyncpg://lending_user:lending_secret@localhost:5433/lending_db`
- `REDIS_URL` = `redis://:lending_redis_pass@localhost:6380/0`
- `JWT_SECRET_KEY` must be at least 32 characters

# RUN COMMANDS
- Start all services: `docker-compose up --build`
- Backend runs Alembic migrations + seeds admin user on startup via entrypoint.sh

# COMPLETED TASKS

## 1. Collection Officer Dropdown Not Functioning (Loans Page)
**Date:** 2026-06-06
**Files Modified:**
- `backend/app/utils/demo_seeder_enhanced.py` — Added 2 collection officer users to seed data
- `frontend-react/src/pages/LoansPage.tsx` — Fixed controlled select blank issue, added proper response reading in saveAssign, loaded officers on mount

**Root Cause:** No users with role `collections_officer` existed in the database seed data. Additionally, the `openAssign` function set `assignOfficerId` before `fetchModalData` completed, causing React's controlled `<select>` to render blank when the value matched no loaded option. The `saveAssign` mutation responses were never parsed (bare `fetch()` without `.json()`), so errors were silently swallowed.

**Fix Summary:**
- Added `Ramon Villar` (BR-QC) and `Luzviminda Cruz` (BR-CDO) with role `collections_officer` to demo seeder
- `openAssign` now awaits `fetchModalData().then(() => setAssignOfficerId(...))` so officers array is populated before setting the dropdown value
- `fetchModalData()` is called on component mount so officer names display in the table immediately
- `saveAssign` now reads mutation responses via `.then(r => r.json())` and checks `success === false` before proceeding
- `saveAssign` awaits `init()` so loan data is refreshed before modal closes

## 2. New Product Button Not Functioning (Loan Products Page)
**Date:** 2026-06-06
**Files Modified:**
- `backend/app/graphql.py` — Added `create_loan_product` mutation with auth, duplicate validation, and all Phase 2.1 fields
- `frontend-react/src/pages/LoanProductsPage.tsx` — Added create product modal with form validation, loading state, and error display

**Root Cause:** The "New Product" `<button>` had no `onClick` handler — it was purely decorative. The backend GraphQL schema had `loanProducts` query but no `createLoanProduct` mutation.

**Fix Summary:**
- Backend: Added `create_loan_product` mutation to the `Mutation` class with admin/branch_manager auth, duplicate product code check, and all PGLoanProduct columns mapped
- Frontend: New "New Loan Product" modal with form fields for all required attributes (product code, name, amortization type, repayment frequency, interest rate) plus optional fields (description, penalty rate, grace period)
- Validation: Missing required fields show inline error; duplicate codes return backend error message
- Follows the same modal pattern used in BranchesPage
