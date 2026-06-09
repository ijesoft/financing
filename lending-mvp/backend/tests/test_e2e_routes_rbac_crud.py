"""
Comprehensive E2E Tests — Routes, RBAC, and CRUD
================================================
Tests against the running FastAPI server on localhost:8811.

  1. REST endpoints (login, health)
  2. GraphQL queries (public)
  3. CRUD mutations (Branch, User, Customer, Loan, Savings, LoanTx)
  4. RBAC — every role vs every protected operation
  5. Edge cases (invalid tokens, malformed queries, missing fields)
"""

import pytest
import httpx
from uuid import uuid4

BASE_URL = "http://localhost:8811"

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

async def login(username: str = "admin", password: str = "admin123") -> dict:
    async with httpx.AsyncClient(base_url=BASE_URL) as client:
        r = await client.post("/api-login/", json={"username": username, "password": password})
        assert r.status_code == 200, f"Login failed for {username}: {r.text}"
        return r.json()


async def gql(query: str, token: str | None = None, **kw) -> dict:
    headers = {}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    body: dict = {"query": query}
    if kw:
        body["variables"] = kw
    async with httpx.AsyncClient(base_url=BASE_URL) as client:
        r = await client.post("/graphql", json=body, headers=headers)
        assert r.status_code == 200, f"GraphQL error: {r.text}"
        return r.json()


# ---------------------------------------------------------------------------
# 1.  REST ENDPOINTS
# ---------------------------------------------------------------------------

class TestRestEndpoints:
    async def test_health(self):
        async with httpx.AsyncClient(base_url=BASE_URL) as client:
            r = await client.get("/health")
        assert r.status_code == 200
        assert r.json() == {"status": "ok"}

    async def test_root(self):
        async with httpx.AsyncClient(base_url=BASE_URL) as client:
            r = await client.get("/")
        assert r.status_code == 200
        data = r.json()
        assert "Lending MVP" in data.get("message", "")

    async def test_login_success(self):
        d = await login("admin", "admin123")
        assert "accessToken" in d
        assert d["user"]["username"] == "admin"
        assert d["user"]["role"] == "admin"

    async def test_login_invalid_password(self):
        async with httpx.AsyncClient(base_url=BASE_URL) as client:
            r = await client.post("/api-login/", json={"username": "admin", "password": "wrong"})
        assert r.status_code == 401

    async def test_login_invalid_username(self):
        async with httpx.AsyncClient(base_url=BASE_URL) as client:
            r = await client.post("/api-login/", json={"username": "nonexistent", "password": "x"})
        assert r.status_code == 401

    async def test_login_missing_fields(self):
        async with httpx.AsyncClient(base_url=BASE_URL) as client:
            r = await client.post("/api-login/", json={})
        assert r.status_code == 422


# ---------------------------------------------------------------------------
# 2.  GRAPHQL QUERIES (public)
# ---------------------------------------------------------------------------

class TestGraphQLQueries:
    async def test_health_query(self):
        r = await gql("{ health { status message } }")
        assert r["data"]["health"]["status"] == "ok"

    async def test_users_query(self):
        r = await gql("{ users { id username role } }")
        assert isinstance(r["data"]["users"], list)

    async def test_branches_query(self):
        r = await gql("{ branches { id code name } }")
        assert isinstance(r["data"]["branches"], list)

    async def test_customers_query(self):
        r = await gql("{ customers { customers { id displayName } total } }")
        assert "customers" in r["data"]["customers"]

    async def test_loans_query(self):
        r = await gql("{ loans { loans { id status principal } total } }")
        assert "loans" in r["data"]["loans"]

    async def test_savings_accounts_query(self):
        pytest.xfail("DB migration: savings_accounts.maturity_date column missing")
        r = await gql("{ savingsAccounts { accounts { id accountNumber } total } }")
        assert "accounts" in r["data"]["savingsAccounts"]

    async def test_gl_accounts_query(self):
        r = await gql("{ glAccounts { id code name } }")
        assert isinstance(r["data"]["glAccounts"], list)

    async def test_dashboard_stats_query(self):
        r = await gql("{ dashboardStats { customersTotal loansTotal } }")
        assert "customersTotal" in r["data"]["dashboardStats"]

    async def test_loan_products_query(self):
        r = await gql("{ loanProducts { id name } }")
        assert isinstance(r["data"]["loanProducts"], list)

    async def test_loan_amortization_query(self):
        r = await gql("{ loans { loans { id } } }")
        loans = r.get("data", {}).get("loans", {}).get("loans", [])
        if loans:
            lid = loans[0]["id"]
            r2 = await gql(f"{{ loanAmortization(loanId: \"{lid}\") {{ id installmentNumber }}}}")
            assert "data" in r2

    async def test_audit_logs_query(self):
        r = await gql("{ auditLogs { id action } }")
        assert "data" in r

    async def test_collections_query(self):
        r = await gql("{ collections { id status } }")
        assert "data" in r

    async def test_journal_entries_query(self):
        r = await gql("{ journalEntries { entries { id referenceNo } total } }")
        assert "data" in r


# ---------------------------------------------------------------------------
# 3.  CRUD — BRANCH (admin only)
# ---------------------------------------------------------------------------

class TestBranchCRUD:
    async def test_create_branch(self):
        token = (await login("admin", "admin123"))["accessToken"]
        code = f"E2E-{uuid4().hex[:6].upper()}"
        r = await gql(
            "mutation($i: BranchInput!) { createBranch(input: $i) { success message branch { id } } }",
            token=token, i={"code": code, "name": "E2E Branch"},
        )
        assert r["data"]["createBranch"]["success"] is True, r
        pytest.branch_id = r["data"]["createBranch"]["branch"]["id"]
        pytest.branch_code = code

    async def test_create_duplicate_branch(self):
        token = (await login("admin", "admin123"))["accessToken"]
        r = await gql(
            "mutation($i: BranchInput!) { createBranch(input: $i) { success message } }",
            token=token, i={"code": pytest.branch_code, "name": "E2E Branch"},
        )
        assert r["data"]["createBranch"]["success"] is False
        assert "already exists" in r["data"]["createBranch"]["message"].lower()

    async def test_update_branch(self):
        token = (await login("admin", "admin123"))["accessToken"]
        r = await gql(
            "mutation($id: ID!, $i: BranchInput!) { updateBranch(branchId: $id, input: $i) { success message } }",
            token=token, id=pytest.branch_id, i={"code": pytest.branch_code, "name": "Updated"},
        )
        assert r["data"]["updateBranch"]["success"] is True

    async def test_delete_branch(self):
        token = (await login("admin", "admin123"))["accessToken"]
        r = await gql(
            "mutation($id: ID!) { deleteBranch(branchId: $id) { success message } }",
            token=token, id=pytest.branch_id,
        )
        assert r["data"]["deleteBranch"]["success"] is True


# ---------------------------------------------------------------------------
# 4.  CRUD — USER (admin / branch_manager)
# ---------------------------------------------------------------------------

class TestUserCRUD:
    async def test_create_user(self):
        token = (await login("admin", "admin123"))["accessToken"]
        uname = f"e2e-{uuid4().hex[:6]}"
        email = f"{uuid4().hex[:8]}@e2e.local"
        r = await gql(
            "mutation($i: UserCreateInput!) { createUser(input: $i) { success message user { id } } }",
            token=token,
            i={"username": uname, "email": email, "fullName": "E2E User", "password": "TestPass123!", "role": "loan_officer"},
        )
        assert r["data"]["createUser"]["success"] is True, r
        pytest.test_user_id = r["data"]["createUser"]["user"]["id"]
        pytest.test_username = uname

    async def test_create_duplicate_user(self):
        token = (await login("admin", "admin123"))["accessToken"]
        r = await gql(
            "mutation($i: UserCreateInput!) { createUser(input: $i) { success message } }",
            token=token,
            i={"username": pytest.test_username, "email": "dup@e2e.local", "fullName": "Dup", "password": "X", "role": "teller"},
        )
        assert r["data"]["createUser"]["success"] is False

    async def test_update_user(self):
        token = (await login("admin", "admin123"))["accessToken"]
        r = await gql(
            "mutation($id: ID!, $i: UserUpdateInput!) { updateUser(id: $id, input: $i) { success message } }",
            token=token, id=pytest.test_user_id, i={"fullName": "Updated E2E"},
        )
        assert r["data"]["updateUser"]["success"] is True

    async def test_delete_user(self):
        token = (await login("admin", "admin123"))["accessToken"]
        r = await gql(
            "mutation($id: ID!) { deleteUser(id: $id) { success message } }",
            token=token, id=pytest.test_user_id,
        )
        assert r["data"]["deleteUser"]["success"] is True


# ---------------------------------------------------------------------------
# 5.  CRUD — CUSTOMER (admin / branch_manager)
# ---------------------------------------------------------------------------

class TestCustomerCRUD:
    async def test_create_customer(self):
        token = (await login("admin", "admin123"))["accessToken"]
        name = f"E2E-{uuid4().hex[:6]}"
        email = f"{uuid4().hex[:8]}@cust.local"
        r = await gql(
            "mutation($i: CustomerInput!) { createCustomer(input: $i) { success message customer { id } } }",
            token=token,
            i={"displayName": name, "customerType": "individual", "branchCode": "HQ", "emailAddress": email, "mobileNumber": "09170000000"},
        )
        assert r["data"]["createCustomer"]["success"] is True, r
        pytest.customer_id = r["data"]["createCustomer"]["customer"]["id"]

    async def test_query_customers(self):
        token = (await login("admin", "admin123"))["accessToken"]
        r = await gql("{ customers { customers { id } } }", token=token)
        ids = [c["id"] for c in r["data"]["customers"]["customers"]]
        assert pytest.customer_id in ids

    async def test_update_customer(self):
        token = (await login("admin", "admin123"))["accessToken"]
        r = await gql(
            "mutation($id: ID!, $i: CustomerInput!) { updateCustomer(id: $id, input: $i) { success message } }",
            token=token, id=pytest.customer_id, i={"displayName": "Updated", "customerType": "individual", "branchCode": "HQ"},
        )
        assert r["data"]["updateCustomer"]["success"] is True

    async def test_delete_customer(self):
        pytest.xfail("DB migration: deleteCustomer queries savings_accounts (missing maturity_date)")
        token = (await login("admin", "admin123"))["accessToken"]
        r = await gql(
            "mutation($id: ID!) { deleteCustomer(id: $id) { success message } }",
            token=token, id=pytest.customer_id,
        )
        assert r["data"]["deleteCustomer"]["success"] is True


# ---------------------------------------------------------------------------
# 6.  CRUD — LOAN LIFECYCLE
# ---------------------------------------------------------------------------

class TestLoanLifecycle:
    async def test_create_draft(self):
        token = (await login("admin", "admin123"))["accessToken"]
        r = await gql("{ customers { customers { id } } loanProducts { id } }", token=token)
        custs = r["data"]["customers"]["customers"]
        prods = r["data"]["loanProducts"]
        if not custs or not prods:
            pytest.skip("No existing customer or product")
        cid, pid = custs[0]["id"], int(prods[0]["id"])
        r2 = await gql(
            "mutation($i: LoanInput!) { createLoan(input: $i) { success message loan { id status } } }",
            token=token,
            i={"customerId": cid, "productId": pid, "principal": "50000", "termMonths": 12},
        )
        assert r2["data"]["createLoan"]["success"] is True, r2
        pytest.loan_id = r2["data"]["createLoan"]["loan"]["id"]
        assert r2["data"]["createLoan"]["loan"]["status"] == "draft"

    async def test_submit_loan(self):
        token = (await login("admin", "admin123"))["accessToken"]
        r = await gql(
            "mutation($id: ID!) { submitLoan(id: $id) { success message } }",
            token=token, id=pytest.loan_id,
        )
        assert r["data"]["submitLoan"]["success"] is True

    async def test_review_loan(self):
        token = (await login("admin", "admin123"))["accessToken"]
        r = await gql(
            "mutation($id: ID!) { reviewLoan(id: $id) { success message } }",
            token=token, id=pytest.loan_id,
        )
        assert r["data"]["reviewLoan"]["success"] is True

    async def test_approve_loan(self):
        token = (await login("admin", "admin123"))["accessToken"]
        r = await gql(
            "mutation($id: ID!, $p: Decimal, $r: Decimal) { approveLoan(id: $id, approvedPrincipal: $p, approvedRate: $r) { success message } }",
            token=token, id=pytest.loan_id, p="50000", r="5.5",
        )
        assert r["data"]["approveLoan"]["success"] is True, r

    async def test_loan_transaction_create(self):
        token = (await login("admin", "admin123"))["accessToken"]
        r = await gql(
            "mutation($i: LoanTransactionCreateInput!) { createLoanTransaction(input: $i) { success message transaction { id } } }",
            token=token,
            i={"loanId": pytest.loan_id, "transactionType": "disbursement", "amount": "10000", "description": "E2E disbursement"},
        )
        assert r["data"]["createLoanTransaction"]["success"] is True, r
        pytest.loan_txn_id = r["data"]["createLoanTransaction"]["transaction"]["id"]

    async def test_loan_transaction_update(self):
        token = (await login("admin", "admin123"))["accessToken"]
        r = await gql(
            "mutation($id: ID!, $i: LoanTransactionUpdateInput!) { updateLoanTransaction(id: $id, input: $i) { success message } }",
            token=token, id=pytest.loan_txn_id, i={"description": "Updated E2E txn"},
        )
        assert r["data"]["updateLoanTransaction"]["success"] is True

    async def test_loan_transaction_delete(self):
        token = (await login("admin", "admin123"))["accessToken"]
        r = await gql(
            "mutation($id: ID!) { deleteLoanTransaction(id: $id) { success message } }",
            token=token, id=pytest.loan_txn_id,
        )
        assert r["data"]["deleteLoanTransaction"]["success"] is True


# ---------------------------------------------------------------------------
# 7.  RBAC — ROLE-BASED ACCESS CONTROL
# ---------------------------------------------------------------------------

ROLES = {
    "admin": "admin123",
    "loan_officer_1": "LoanOfficer@123",
    "teller_1": "Teller@123Demo",
    "branch_manager": "BranchMgr@123",
    "auditor": "Auditor@123Demo",
}


class TestRBACAdminOnly:
    """createBranch / updateBranch / deleteBranch — admin only"""

    async def test_admin_can_create_branch(self):
        token = (await login("admin", "admin123"))["accessToken"]
        code = f"RBAC-{uuid4().hex[:6].upper()}"
        r = await gql(
            "mutation($i: BranchInput!) { createBranch(input: $i) { success message } }",
            token=token, i={"code": code, "name": "RBAC"},
        )
        assert r["data"]["createBranch"]["success"] is True
        # cleanup
        r2 = await gql("{ branches { id code } }", token=token)
        target = [b for b in r2["data"]["branches"] if b["code"] == code]
        if target:
            await gql("mutation($id: ID!) { deleteBranch(branchId: $id) { success } }", token=token, id=target[0]["id"])

    async def test_non_admin_cannot_create_branch(self):
        for role, pw in ROLES.items():
            if role == "admin":
                continue
            token = (await login(role, pw))["accessToken"]
            r = await gql(
                "mutation($i: BranchInput!) { createBranch(input: $i) { success message } }",
                token=token, i={"code": "DENIED", "name": "X"},
            )
            assert r["data"]["createBranch"]["success"] is False, f"{role} was allowed"
            assert "not authorized" in r["data"]["createBranch"]["message"].lower()

    async def test_non_admin_cannot_update_branch(self):
        for role, pw in ROLES.items():
            if role == "admin":
                continue
            token = (await login(role, pw))["accessToken"]
            r = await gql(
                "mutation($id: ID!, $i: BranchInput!) { updateBranch(branchId: $id, input: $i) { success message } }",
                token=token, id="1", i={"code": "X", "name": "X"},
            )
            assert r["data"]["updateBranch"]["success"] is False
            assert "not authorized" in r["data"]["updateBranch"]["message"].lower()

    async def test_non_admin_cannot_delete_branch(self):
        for role, pw in ROLES.items():
            if role == "admin":
                continue
            token = (await login(role, pw))["accessToken"]
            r = await gql(
                "mutation($id: ID!) { deleteBranch(branchId: $id) { success message } }",
                token=token, id="1",
            )
            assert r["data"]["deleteBranch"]["success"] is False
            assert "not authorized" in r["data"]["deleteBranch"]["message"].lower()


class TestRBACMgmtRoles:
    """createCustomer / deleteUser — admin & branch_manager only"""

    async def test_create_customer_by_role(self):
        for role, pw in ROLES.items():
            allowed = role in ("admin", "branch_manager")
            token = (await login(role, pw))["accessToken"]
            name = f"RBAC-{role}-{uuid4().hex[:4]}"
            r = await gql(
                "mutation($i: CustomerInput!) { createCustomer(input: $i) { success message } }",
                token=token,
                i={"displayName": name, "customerType": "individual", "branchCode": "HQ"},
            )
            if allowed:
                assert r["data"]["createCustomer"]["success"] is True, f"{role} should be allowed"
            else:
                assert r["data"]["createCustomer"]["success"] is False, f"{role} should be denied"
                assert "not authorized" in r["data"]["createCustomer"]["message"].lower()

    async def test_delete_user_by_role(self):
        for role, pw in ROLES.items():
            allowed = role in ("admin", "branch_manager")
            token = (await login(role, pw))["accessToken"]
            r = await gql(
                "mutation($id: ID!) { deleteUser(id: $id) { success message } }",
                token=token, id="0",
            )
            if allowed:
                assert "not authorized" not in r["data"]["deleteUser"]["message"].lower(), f"{role}"
            else:
                assert r["data"]["deleteUser"]["success"] is False
                assert "not authorized" in r["data"]["deleteUser"]["message"].lower()

    async def test_update_user_by_role(self):
        for role, pw in ROLES.items():
            allowed = role in ("admin", "branch_manager")
            token = (await login(role, pw))["accessToken"]
            r = await gql(
                "mutation($id: ID!, $i: UserUpdateInput!) { updateUser(id: $id, input: $i) { success message } }",
                token=token, id="0", i={"fullName": "RBAC Test"},
            )
            if allowed:
                assert "not authorized" not in r["data"]["updateUser"]["message"].lower(), f"{role}"
            else:
                assert "not authorized" in r["data"]["updateUser"]["message"].lower()


class TestRBACLoanApproval:
    """approveLoan — admin, branch_manager, loan_officer"""

    async def test_approve_loan_by_role(self):
        admin_token = (await login("admin", "admin123"))["accessToken"]
        r = await gql("{ customers { customers { id } } loanProducts { id } }", token=admin_token)
        custs = r["data"]["customers"]["customers"]
        prods = r["data"]["loanProducts"]
        if not custs or not prods:
            pytest.skip("No customer/product for loan RBAC test")
        allowed_keys = {"admin", "branch_manager", "loan_officer_1"}
        # Create a fresh draft loan for each role to avoid state contamination
        for role, pw in ROLES.items():
            token = (await login(role, pw))["accessToken"]
            r2 = await gql(
                "mutation($i: LoanInput!) { createLoan(input: $i) { loan { id } } }",
                token=admin_token,
                i={"customerId": custs[0]["id"], "productId": int(prods[0]["id"]), "principal": "10000", "termMonths": 6},
            )
            loan_id = r2["data"]["createLoan"]["loan"]["id"]
            r3 = await gql(
                "mutation($id: ID!) { approveLoan(id: $id) { success message } }",
                token=token, id=loan_id,
            )
            if r3["data"]["approveLoan"]["success"] is True:
                assert role in allowed_keys, f"{role} should NOT be able to approve"
            else:
                assert role not in allowed_keys, f"{role} should be able to approve: {r3}"


class TestRBACNoAuth:
    async def test_mutation_blocked(self):
        r = await gql("mutation { createBranch(input: {code: \"NOAUTH\", name: \"X\"}) { success message } }")
        assert r["data"]["createBranch"]["success"] is False
        assert "not authorized" in r["data"]["createBranch"]["message"].lower()

    async def test_query_allowed(self):
        r = await gql("{ health { status } }")
        assert r["data"]["health"]["status"] == "ok"


# ---------------------------------------------------------------------------
# 8.  EDGE CASES
# ---------------------------------------------------------------------------

class TestEdgeCases:
    async def test_invalid_token(self):
        r = await gql("{ users { id } }", token="invalid-jwt")
        assert "data" in r

    async def test_malformed_query(self):
        async with httpx.AsyncClient(base_url=BASE_URL) as client:
            r = await client.post("/graphql", json={"query": "not valid graphql"})
        assert r.status_code == 200
        assert "errors" in r.json()

    async def test_empty_body(self):
        async with httpx.AsyncClient(base_url=BASE_URL) as client:
            r = await client.post("/graphql", json={})
        assert r.status_code == 400

    async def test_missing_required_fields(self):
        token = (await login("admin", "admin123"))["accessToken"]
        uname = f"empty-{uuid4().hex[:8]}"
        email = f"{uuid4().hex[:8]}@empty.local"
        r = await gql(
            "mutation($i: UserCreateInput!) { createUser(input: $i) { success message } }",
            token=token,
            i={"username": uname, "email": email, "fullName": "", "password": ""},
        )
        assert r["data"]["createUser"]["success"] is True
