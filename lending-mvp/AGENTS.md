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

## 3. Loan Amount Format — Missing Thousand Separators and Decimals (Loans Page)
**Date:** 2026-06-08
**Files Modified:**
- `frontend-react/src/pages/LoansPage.tsx` — Added `formatCurrency` import from `@/lib/utils` and replaced inline `toLocaleString()` 

**Root Cause:** Line 214 used `loan.principal.toLocaleString()` without specifying locale or `minimumFractionDigits: 2`, displaying amounts as `₱100,000` instead of `₱100,000.00`. Twelve other pages already used the shared `formatCurrency` utility, but `LoansPage.tsx` did not.

**Fix Summary:**
- Added `import { formatCurrency } from '@/lib/utils'`
- Replaced `` `₱${loan.principal.toLocaleString()}` `` with `formatCurrency(loan.principal)`, which uses `Intl.NumberFormat('en-PH', { style: 'currency', currency: 'PHP', minimumFractionDigits: 2 })`

## 4. Collection Officer Dropdown Empty (Loans Page — Assign Modal)
**Date:** 2026-06-08
**Files Modified:**
- `frontend-react/src/pages/LoansPage.tsx` — Fixed race condition in `openAssign`, improved `fetchModalData` error handling, switched to parallel fetches

**Root Cause:** The `openAssign` function called `setAssignTarget(loan)` (which immediately renders the modal) before `fetchModalData()` completed. If the initial mount fetch hadn't resolved or had failed, the modal appeared with `officers=[]`. Additionally, GraphQL errors in the response (e.g., auth failures) were silently swallowed by the try/catch, falling back to `[]` with no console visibility.

**Fix Summary:**
- `openAssign` is now `async` and `await`s `fetchModalData()` before setting `assignTarget`, ensuring officers are loaded before the modal shows
- `fetchModalData` now uses `Promise.all` for parallel officers/branches fetches
- Added GraphQL error logging (`console.warn`) instead of silently falling back to empty arrays

## 5. Amortization Schedule Shows Monthly When Should Be Daily (Loan #9)
**Date:** 2026-06-08
**Files Modified:**
- `backend/app/loan.py` — Added `_get_schedule_config()`, `_calc_due_date()`, rewrote `_build_schedule_preview()` to accept `repayment_frequency`, updated `disburse_loan()` and `generate_loan_schedule_preview()`
- `backend/app/graphql.py` — Rewrote inline schedule generation in `disburseLoan` to use frequency-aware logic, added `repaymentFrequency`/`amortizationType` to `LoanProductNode`, added `repaymentFrequency` to `LoanAmortizationNode`, updated `loanAmortization` and `loanProducts` resolvers
- `backend/app/customer.py` — Fixed pre-existing indentation error in `customers` resolver
- `frontend-react/src/api/queries.ts` — Added `repaymentFrequency` field to `GET_LOAN_AMORTIZATION`
- `frontend-react/src/pages/AmortizationSchedulePage.tsx` — Replaced hardcoded "Monthly" labels with dynamic frequency display, fixed periodic rate divisor, updated local fallback calculation

**Root Cause:** The `repayment_frequency` column on `PGLoanProduct` supported values `daily`, `weekly`, `bi_weekly`, `monthly`, `quarterly`, `bullet` — but all **3 schedule generation code paths** (`loan.py:_build_schedule_preview`, `graphql.py:disburseLoan` inline, `amortization_service.py:build_schedule`) hardcoded monthly intervals using `relativedelta(months=i)` and `rate / 12`. Loan #9 used product MF-Arawan (`repayment_frequency: "daily"`) but was generated with 3 monthly payments instead of ~90 daily payments.

**Fix Summary:**
- Added `_get_schedule_config()` helper mapping frequency → (num_periods, days_step, rate_divisor): daily(×30, 1d, /365), weekly(×4, 7d, /52), bi_weekly(×2, 14d, /26), monthly(×1, months, /12), quarterly(÷3, months×3, /4)
- Added `_calc_due_date()` using `timedelta(days=)` for day-based frequencies and `relativedelta(months=)` for month-based
- `_build_schedule_preview` now accepts `repayment_frequency` parameter (default `"monthly"` for backward compat) and uses it for all amortization types
- `LoanProductNode` now exposes `repaymentFrequency` and `amortizationType` fields
- `LoanAmortizationNode` now includes `repaymentFrequency` from the loan's product
- Frontend dynamically displays payment frequency label and calculates periodic rate with correct divisor
- Loan #9's amortization regenerated: 90 daily payments (Jun 9 → Sep 6) at ₱172.42/each (₱166.67 principal + ₱5.75 interest) at 14% flat rate
- Demo product MF-Arawan (ID 5) confirmed: `repayment_frequency: daily`, `amortization_type: flat_rate`
