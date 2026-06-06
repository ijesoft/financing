# Loan Assignment & Collections Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Enable loan assignment to branch/area and collections officers with role-based daily collections querying.

**Architecture:** Add `assigned_collections_branch` column to `LoanApplication`, add `collections_officer` to `VALID_ROLES`, enhance `resolve_collections_due` with RBAC filtering, add assignment mutations, rewire `CollectionDuePage` with filters.

**Tech Stack:** Python/Strawberry GraphQL, SQLAlchemy, React/TypeScript, Tailwind CSS.

---

### Task 1: Backend Model + RBAC Changes

**Files:**
- Modify: `lending-mvp/backend/app/database/pg_loan_models.py:107`
- Modify: `lending-mvp/backend/app/user.py:54`
- Modify: `lending-mvp/backend/app/auth/rbac.py:18-23`

**Steps:**
1. Add `assigned_collections_branch` column to LoanApplication model
2. Add `collections_officer` to `VALID_ROLES` in user.py
3. Add to `ALL_STAFF_ROLES` and `BRANCH_SCOPED_ROLES` in rbac.py

---

### Task 2: Backend GraphQL Schema + Resolver Enhancements

**Files:**
- Modify: `lending-mvp/backend/app/graphql_collections_schema.py` (add `assignedCollectionsBranch`)
- Modify: `lending-mvp/backend/app/graphql_collections_resolvers.py` (add filtering params + RBAC)
- Modify: `lending-mvp/backend/app/graphql.py` (add mutations + usersByRole query)

**Steps:**
1. Add `assignedCollectionsBranch` to `CollectionsDueEntry`
2. Add `collections_officer_id`, `due_date_from`, `due_date_to` params to `resolve_collections_due`
3. Apply RBAC filtering (collections_officer sees own, branch_manager sees branch)
4. Add `assignLoanCollectionsOfficer`, `assignLoanCollectionsBranch` mutations
5. Add `usersByRole(role)` query

---

### Task 3: Frontend - Enhanced CollectionDuePage + Assignment UI

**Files:**
- Modify: `lending-mvp/frontend-react/src/pages/CollectionDuePage.tsx`

**Steps:**
1. Rewire GraphQL query from old `collectionDue` to `collectionsDue`
2. Add date range filter (Today/This Week/This Month/Custom)
3. Add collections officer dropdown filter (admin/branch_manager only)
4. Add branch dropdown filter (admin only)
5. RBAC-aware visibility (collector sees own loans without filters)
6. Add inline assignment UI (dropdown per row for officer/branch)
