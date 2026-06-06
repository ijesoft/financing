# Loan Assignment & Daily Collections Design

## Overview

Enable assignment of loans to specific branch/area and collections officers, with role-based daily collections querying.

## Data Model Changes

### LoanApplication (pg_loan_models.py)
- Add `assigned_collections_branch: Column(String(20), nullable, indexed)` — separate from origination `branch_code`
- Add index on `collections_officer` for query performance

### RBAC (user.py, rbac.py)
- Add `collections_officer` to `VALID_ROLES`
- Add `collections_officer` to `ALL_STAFF_ROLES` and `BRANCH_SCOPED_ROLES`

## Visibility Rules

| Role | Sees |
|------|------|
| collections_officer | Only loans where `collections_officer = {their id}` |
| branch_manager | Loans in their branch + optional officer filter |
| admin | All loans + branch + officer filters |

## GraphQL Changes

### Enhanced `resolve_collections_due` (graphql_collections_resolvers.py)
- Add params: `collections_officer_id`, `as_of` (date), `due_date_from`, `due_date_to`
- Apply RBAC filtering at query level

### New Mutations (graphql.py)
- `assignLoanCollectionsOfficer(loanId, collectionsOfficerId)` — admin/branch_manager only
- `assignLoanCollectionsBranch(loanId, branchCode)` — admin/branch_manager only

### New Query (graphql.py)
- `usersByRole(role)` — for populating assignment dropdowns

## Frontend Changes

### CollectionDuePage.tsx — Enhanced
- Rewire from old `collectionDue` query to new `collectionsDue` resolver
- Add date range filter (Today, This Week, This Month, Custom)
- Add collections officer dropdown filter (admin/branch_manager only)
- Add branch dropdown filter (admin only)
- RBAC-aware: collectors see only their loans with no filters

### New: LoanAssignment UI
- Inline dropdown per row for officer/branch assignment
- Bulk select + assign action buttons
- Visible only to admin/branch_manager

## Implementation Order

1. Backend: Model + RBAC changes
2. Backend: Enhanced resolvers + new mutations
3. Frontend: Enhanced CollectionDuePage
4. Frontend: Assignment UI
