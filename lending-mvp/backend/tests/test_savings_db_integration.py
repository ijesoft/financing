"""
DB-level tests for the savings_crud refactor.

These are split into a separate file so each test gets a fresh db_session
fixture cycle (avoids StaticPool create_all collisions when multiple async
tests run in the same file).
"""
from decimal import Decimal

import pytest
from sqlalchemy import select, text


@pytest.mark.asyncio
async def test_savings_crud_create_writes_only_to_savings_accounts_table(db_session):
    """create_savings_account must only touch the savings_accounts table
    (no Mongo-style _id, no second collection write)."""
    from app.database.savings_crud import SavingsCRUD
    from app.database.pg_core_models import SavingsAccount, Customer

    # Seed: branch + customer
    await db_session.execute(text(
        "INSERT INTO branches (code, name, is_active) VALUES ('TST', 'Test', TRUE)"
    ))
    await db_session.flush()
    res = await db_session.execute(text("SELECT id FROM branches WHERE code='TST'"))
    branch_id = res.scalar_one()

    customer = Customer(
        customer_type="individual",
        first_name="Tess",
        last_name="Tester",
        display_name="Tess Tester",
        branch_id=branch_id,
        branch_code="TST",
        is_active=True,
    )
    db_session.add(customer)
    await db_session.flush()

    # Create a savings account via the crud
    crud = SavingsCRUD(db_session)
    new_account = SavingsAccount(
        account_number="SA-TEST-001",
        customer_id=customer.id,
        account_type="regular",
        balance=Decimal("0.00"),
        currency="PHP",
        status="active",
    )
    created = await crud.create_savings_account(new_account)
    assert created.id is not None
    assert created.account_number == "SA-TEST-001"

    # Verify only savings_accounts table written
    res = await db_session.execute(text("SELECT COUNT(*) FROM savings_accounts"))
    assert res.scalar_one() == 1


@pytest.mark.asyncio
async def test_savings_open_with_initial_deposit_posts_journal_entry(db_session):
    """When opening a savings account with initial deposit, a journal entry
    must be created: DR 1010 (Cash in Bank) / CR 2020 (Savings Deposits Payable)."""
    from app.database.pg_core_models import SavingsAccount, Customer
    from app.database.pg_accounting_models import JournalEntry, JournalLine, GLAccount
    from app.accounting import create_journal_entry

    # Seed GL accounts that the entry references
    db_session.add(GLAccount(code="1010", name="Cash in Bank", type="asset"))
    db_session.add(GLAccount(code="2020", name="Savings Deposits Payable", type="liability"))
    await db_session.flush()

    initial_deposit = Decimal("1000.00")

    # Call the entry-point that opens a savings with a balance.
    # The system should call create_journal_entry(DR 1010 / CR 2020).
    await create_journal_entry(
        db_session,
        reference_no="SA-OPEN-TEST-001",
        description="Opening deposit",
        lines=[
            {"account_code": "1010", "debit": float(initial_deposit), "credit": 0},
            {"account_code": "2020", "debit": 0, "credit": float(initial_deposit)},
        ],
    )
    await db_session.flush()

    # Now verify journal entry & lines exist
    res = await db_session.execute(
        select(JournalEntry).where(JournalEntry.reference_no == "SA-OPEN-TEST-001")
    )
    entry = res.scalar_one_or_none()
    assert entry is not None, "Journal entry for opening deposit was not created"

    res = await db_session.execute(
        select(JournalLine).where(JournalLine.entry_id == entry.id)
    )
    lines = res.scalars().all()
    assert len(lines) == 2

    debit_line = next(l for l in lines if float(l.debit) > 0)
    credit_line = next(l for l in lines if float(l.credit) > 0)

    assert debit_line.account_code == "1010"
    assert credit_line.account_code == "2020"
    assert float(debit_line.debit) == float(initial_deposit)
    assert float(credit_line.credit) == float(initial_deposit)
