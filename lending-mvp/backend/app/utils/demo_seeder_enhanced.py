"""
ENHANCED DEMO DATA SEEDER - PostgreSQL Only
============================================
This module contains enhanced seeder functions to improve demo data quality
for more realistic testing coverage. PostgreSQL-only implementation.
"""

import asyncio
import logging
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from typing import List, Dict, Any
from sqlalchemy import select, text

# Setup logging
logger = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO)

# Import database connections - PostgreSQL only
from ..database import get_async_session_local
from ..database.pg_core_models import User, Customer, SavingsAccount, SavingsTransaction
from ..database.pg_loan_models import LoanApplication, PGLoanProduct
from ..database.pg_loan_models import LoanApplication as Loan
from ..database.pg_models import (
    Branch,
    AuditLog,
    KYCDocument,
    AMLAlert,
    Beneficiary,
    CustomerActivity,
    PEPRecord,
    Collection,
)
from ..database.pg_accounting_models import GLAccount, JournalEntry, JournalLine
from ..auth.security import get_password_hash


async def ensure_tables_exist():
    """Create all database tables if they don't exist."""
    try:
        from ..database import Base, get_engine
        engine = get_engine()
        async with engine.begin() as conn:
            # create_all with checkfirst=True will skip existing tables
            await conn.run_sync(Base.metadata.create_all)
        logger.info("Database tables ensured.")
    except Exception as e:
        # Ignore errors about existing tables or indexes
        if "already exists" in str(e).lower() or "duplicate" in str(e).lower():
            logger.info("Tables already exist, skipping creation.")
        else:
            logger.warning(f"Table creation skipped: {e}")


# ============================================================================
# RECOMMENDATION 1: SEED TRANSACTION HISTORY FOR SAVINGS ACCOUNTS (PG)
# ============================================================================


async def seed_savings_transactions_pg(savings_accounts: List[Dict]) -> Dict[str, Any]:
    """
    Seed realistic transaction history for all savings accounts in PostgreSQL.
    Creates deposits, withdrawals, transfers, and interest postings spanning 6 months.
    
    This enhances testing coverage for:
    - Transaction history display
    - Balance calculations
    - Interest computation
    - Account reconciliation
    """
    logger.info("Seeding savings transaction history (PostgreSQL)...")
    session_factory = get_async_session_local()
    created_transactions = 0
    
    # Skip if no savings accounts
    if not savings_accounts:
        logger.warning("No savings accounts to seed transactions for")
        return {"savings_transactions_created": 0}
    
    now = datetime.now(timezone.utc)
    
    # Generate transactions for each savings account
    for account in savings_accounts:
        account_number = account.get("account_number", "UNKNOWN")
        balance = float(account.get("balance", 50000))
        account_type = account.get("type", "regular")
        
        # Generate transactions going back 6 months
        for month_offset in range(6, -1, -1):
            txn_date = now - timedelta(days=30 * month_offset)
            
            # Monthly deposit
            deposit_amount = Decimal("5000" + str(month_offset * 100))
            if balance + deposit_amount > 500000:
                deposit_amount = balance / 2
            
            # Insert deposit into SavingsTransaction
            from sqlalchemy import insert
            deposit_data = {
                "account_id": str(account.get("id")),
                "account_number": account_number,
                "type": "deposit_cash",
                "amount": float(deposit_amount),
                "balance_after": float(balance + deposit_amount),
                "note": f"Monthly deposit - Month {6 - month_offset}",
                "reference_number": f"DEP-{txn_date.strftime('%Y%m%d')}-001",
                "created_at": txn_date,
                "processed_by": "system",
                "status": "completed",
            }
            session_factory = get_async_session_local()
            async with session_factory() as session:
                await session.execute(insert(SavingsTransaction).values(deposit_data))
                await session.flush()
                created_transactions += 1
            
            # Monthly withdrawal (for regular accounts only)
            if account_type == "regular" and month_offset % 2 == 0:
                withdrawal_amount = Decimal("1000" + str(month_offset * 50))
                if withdrawal_amount > balance + deposit_amount:
                    withdrawal_amount = (balance + deposit_amount) / 2
                
                withdrawal_data = {
                    "account_id": str(account.get("id")),
                    "account_number": account_number,
                    "type": "withdrawal_cash",
                    "amount": float(withdrawal_amount),
                    "balance_after": float(balance + deposit_amount - withdrawal_amount),
                    "note": f"Monthly withdrawal - Month {6 - month_offset}",
                    "reference_number": f"WTH-{txn_date.strftime('%Y%m%d')}-001",
                    "created_at": txn_date,
                    "processed_by": "teller_1",
                    "status": "completed",
                }
                async with session_factory() as session:
                    await session.execute(insert(SavingsTransaction).values(withdrawal_data))
                    await session.flush()
                    created_transactions += 2
            
            # Interest posting (quarterly)
            if month_offset % 3 == 0:
                interest_rate = account.get("interest_rate", 0.25) / 100
                interest_amount = (balance + deposit_amount - withdrawal_amount) * interest_rate * 3 / 100
                if interest_amount > 0:
                    interest_data = {
                        "account_id": str(account.get("id")),
                        "account_number": account_number,
                        "type": "interest_posting",
                        "amount": float(interest_amount),
                        "balance_after": float(balance + deposit_amount - withdrawal_amount + interest_amount),
                        "note": f"Interest posting (Q{6 - month_offset // 3 + 1})",
                        "reference_number": f"INT-{txn_date.strftime('%Y%m%d')}-001",
                        "created_at": txn_date,
                        "processed_by": "system",
                        "status": "completed",
                    }
                    async with session_factory() as session:
                        await session.execute(insert(SavingsTransaction).values(interest_data))
                        await session.flush()
                        created_transactions += 2
            
            # Update account balance
            current_balance = balance + deposit_amount - withdrawal_amount + interest_amount
            async with session_factory() as session:
                from sqlalchemy import update
                await session.execute(
                    update(SavingsAccount)
                    .where(SavingsAccount.account_number == account_number)
                    .values(balance=current_balance, updated_at=txn_date)
                )
    
    logger.info(f"Savings transactions seeded (PostgreSQL): {created_transactions} records")
    return {"savings_transactions_created": created_transactions}


# ============================================================================
# RECOMMENDATION 2: SEED LOAN REPAYMENT TRANSACTIONS (PG)
# ============================================================================


async def seed_loan_repayments_pg(loans: List[Dict]) -> Dict[str, Any]:
    """
    Seed repayment transactions for active loans in PostgreSQL.
    Creates monthly installments with principal and interest breakdown.
    
    This enhances testing coverage for:
    - Repayment history display
    - Amortization schedule calculations
    - Outstanding balance tracking
    - Loan closure workflows
    """
    logger.info("Seeding loan repayment transactions (PostgreSQL)...")
    session_factory = get_async_session_local()
    created_repayments = 0
    
    # Skip if no loans
    if not loans:
        logger.warning("No loans to seed repayments for")
        return {"loan_repayments_created": 0}
    
    now = datetime.now(timezone.utc)
    
    for loan in loans:
        status = loan.get("status", "")
        if status not in ["active", "paid"]:
            continue
        
        principal = loan.get("principal", 0)
        term_months = loan.get("term_months", 12)
        rate = loan.get("rate", 0) / 100 / 12
        months_paid = loan.get("months_paid", 0)
        loan_id = loan.get("id", "")
        
        if rate > 0:
            monthly_payment = principal * (rate * (1 + rate) ** term_months) / ((1 + rate) ** term_months - 1)
        else:
            monthly_payment = principal / term_months
        
        principal_per_month = monthly_payment * rate / (rate + (1 - (1 + rate) ** -term_months))
        if principal_per_month == 0:
            principal_per_month = monthly_payment / term_months
        
        # Generate repayment history for paid months
        for month_paid_num in range(1, months_paid + 1):
            repayment_date = now - timedelta(days=30 * (term_months - months_paid_num))
            
            # Calculate remaining principal
            remaining_principal = principal - (principal_per_month * month_paid_num)
            if remaining_principal < 0:
                remaining_principal = 0
            
            principal_portion = min(principal_per_month, remaining_principal)
            interest_portion = monthly_payment - principal_portion
            
            # Insert into LedgerEntry (PostgreSQL model)
            repayment_data = {
                "loan_id": loan_id,
                "account_id": loan_id,
                "type": "loan_repayment",
                "amount": float(monthly_payment),
                "principal_amount": float(principal_portion),
                "interest_amount": float(interest_portion),
                "note": f"Loan installment - Month {month_paid_num}",
                "reference_number": f"RPT-{repayment_date.strftime('%Y%m%d')}-{month_paid_num:03d}",
                "created_at": repayment_date,
                "processed_by": "customer",
                "status": "completed",
            }
            
            async with session_factory() as session:
                await session.execute(insert(LedgerEntry).values(repayment_data))
                await session.flush()
                created_repayments += 1
    
    logger.info(f"Loan repayments seeded (PostgreSQL): {created_repayments} records")
    return {"loan_repayments_created": created_repayments}


# ============================================================================
# RECOMMENDATION 3: SEED PEP RECORDS (PG)
# ============================================================================


async def seed_pep_records_comprehensive() -> Dict[str, Any]:
    """
    Seed comprehensive PEP (Politically Exposed Persons) database records in PostgreSQL.
    Includes domestic, foreign, family member, and associate PEPs.
    
    This enhances testing coverage for:
    - PEP screening alerts
    - Enhanced due diligence workflows
    - Beneficiary relationship mapping
    - Risk assessment dashboards
    """
    logger.info("Seeding comprehensive PEP records (PostgreSQL)...")
    session_factory = get_async_session_local()
    created = 0
    
    # Domestic PEPs - Government officials
    domestic_peps = [
        {
            "name": "Ernesto G. Villanueva",
            "position": "Former City Councillor",
            "country": "Philippines",
            "pep_type": "domestic_pep",
            "start_date": "2020-01-15",
            "end_date": "2023-06-30",
            "source": "Commission on Appointments",
            "risk_level": "medium"
        },
        {
            "name": "Elena Reyes-Santos",
            "position": "Regional Director, DOH",
            "country": "Philippines",
            "pep_type": "domestic_pep",
            "start_date": "2018-03-01",
            "end_date": None,
            "source": "Presidential Appointment",
            "risk_level": "high"
        },
        {
            "name": "Bonifacio T. Garcia",
            "position": "Former Congressman",
            "country": "Philippines",
            "pep_type": "domestic_pep",
            "start_date": "2016-06-30",
            "end_date": "2022-06-30",
            "source": "Congressional Records",
            "risk_level": "high"
        },
        {
            "name": "Carmela V. Cruz",
            "position": "PDEA Regional Chief (Ret.)",
            "country": "Philippines",
            "pep_type": "domestic_pep",
            "start_date": "2015-01-01",
            "end_date": "2020-12-31",
            "source": "PDEA Records",
            "risk_level": "high"
        },
    ]
    
    # Foreign PEPs
    foreign_peps = [
        {
            "name": "international_demo_pep",
            "position": "Foreign State-Owned Enterprise Director",
            "country": "International",
            "pep_type": "foreign_pep",
            "start_date": "2019-01-01",
            "end_date": None,
            "source": "OFAC List",
            "risk_level": "high"
        },
        {
            "name": "James Anderson-Smith",
            "position": "Former UK MP",
            "country": "United Kingdom",
            "pep_type": "foreign_pep",
            "start_date": "2017-07-12",
            "end_date": "2021-05-07",
            "source": "UK Parliament Records",
            "risk_level": "medium"
        },
        {
            "name": "Maria Gonzalez-Rodriguez",
            "position": "Minister of Finance",
            "country": "Spain",
            "pep_type": "foreign_pep",
            "start_date": "2021-01-01",
            "end_date": None,
            "source": "European Union Database",
            "risk_level": "high"
        },
    ]
    
    # Family Members of PEPs
    family_peps = [
        {
            "name": "Villanueva Jr., Roberto",
            "position": "Business Owner",
            "country": "Philippines",
            "pep_type": "family_member",
            "pep_relation": "son",
            "related_pep_name": "Ernesto G. Villanueva",
            "start_date": "2020-01-15",
            "end_date": "2023-06-30",
            "source": "Family Declaration",
            "risk_level": "medium"
        },
        {
            "name": "Santos, Michael",
            "position": "Real Estate Developer",
            "country": "Philippines",
            "pep_type": "family_member",
            "pep_relation": "brother",
            "related_pep_name": "Elena Reyes-Santos",
            "start_date": "2018-03-01",
            "end_date": None,
            "source": "Family Declaration",
            "risk_level": "high"
        },
    ]
    
    # Associates of PEPs
    associate_peps = [
        {
            "name": "Garcia Holdings Inc.",
            "position": "Corporation",
            "country": "Philippines",
            "pep_type": "associate",
            "pep_relation": "business_partner",
            "related_pep_name": "Bonifacio T. Garcia",
            "start_date": "2016-06-30",
            "end_date": None,
            "source": "Business Registry",
            "risk_level": "medium"
        },
        {
            "name": "Cruz Consulting Group",
            "position": "Consulting Firm",
            "country": "Philippines",
            "pep_type": "associate",
            "pep_relation": "advisor",
            "related_pep_name": "Carmela V. Cruz",
            "start_date": "2015-01-01",
            "end_date": None,
            "source": "Business Registry",
            "risk_level": "medium"
        },
    ]
    
    all_peps = domestic_peps + foreign_peps + family_peps + associate_peps
    
    async with session_factory() as session:
        for pep_data in all_peps:
            # Check if exists
            result = await session.execute(
                select(PEPRecord).filter(PEPRecord.name == pep_data["name"])
            )
            existing = result.scalar_one_or_none()
            if not existing:
                # Filter to only include keys present in the PEPRecord model
                valid_keys = {"name", "position", "country", "pep_type", "is_active"}
                filtered_data = {k: v for k, v in pep_data.items() if k in valid_keys}
                
                pep = PEPRecord(**filtered_data)
                session.add(pep)
                created += 1
        
        await session.commit()
    
    logger.info(f"PEP records seeded (PostgreSQL): {created} new records")
    return {"pep_records_created": created}


# ============================================================================
# RECOMMENDATION 4: SEED HISTORICAL GL ENTRIES (PG)
# ============================================================================


async def seed_gl_entries_comprehensive() -> Dict[str, Any]:
    """
    Seed comprehensive GL journal entries for 12 months of financial data in PostgreSQL.
    Includes interest income, fee income, operating expenses, loan disbursements,
    and interest accruals to support Trial Balance, P&L, and Balance Sheet generation.
    
    This enhances testing coverage for:
    - Financial statement generation
    - Trial balance reports
    - Profit & Loss statements
    - Balance sheet reconciliation
    - Cash flow statements
    """
    logger.info("Seeding comprehensive GL journal entries (PostgreSQL)...")
    session_factory = get_async_session_local()
    created_entries = 0
    now = datetime.now(timezone.utc)
    
    # Ensure required GL accounts exist
    required_accounts = [
        ("1000", "Cash and Cash Equivalents", "asset"),
        ("1200", "Loans Receivable", "asset"),
        ("1300", "Fixed Assets", "asset"),
        ("2000", "Accounts Payable / Accrued Liabilities", "liability"),
        ("2100", "Customer Deposits", "liability"),
        ("3000", "Share Capital", "equity"),
        ("4100", "Interest Income", "income"),
        ("4200", "Fee Income", "income"),
        ("4300", "Other Income", "income"),
        ("5100", "Operating Expenses", "expense"),
        ("5200", "Interest Expense", "expense"),
        ("5300", "Provision for Loan Losses", "expense"),
    ]
    
    async with session_factory() as session:
        for code, name, acct_type in required_accounts:
            existing = await session.execute(
                select(GLAccount).filter(GLAccount.code == code)
            )
            if not existing.scalar_one_or_none():
                session.add(GLAccount(code=code, name=name, type=acct_type))
        await session.flush()
        
        # 12 months of historical data
        for month_offset in range(11, -1, -1):
            month_name = f"Month {month_offset + 1} 2025"
            month_date = now - timedelta(days=30 * month_offset)
            scale_factor = 1.0 + (month_offset * 0.05)
            
            interest_income = 87500.00 * scale_factor
            fee_income = 12500.00 * scale_factor
            op_expenses = 45000.00 * scale_factor
            interest_exp = 18000.00 * scale_factor
            provision = 15000.00 * scale_factor
            
            # Interest Income Entry
            interest_entry = JournalEntry(
                timestamp=month_date,
                description=f"Interest Income - {month_name}",
                reference_no=f"INT-{month_offset:03d}-{now.timestamp()}"
            )
            interest_entry.lines.append(JournalLine(
                account_code="4100",
                debit=Decimal("0.00"),
                credit=interest_income,
                description=f"Interest Income - {month_name}"
            ))
            interest_entry.lines.append(JournalLine(
                account_code="1000",
                debit=interest_income,
                credit=Decimal("0.00"),
                description=f"Interest Income - {month_name}"
            ))
            session.add(interest_entry)
            
            # Fee Income Entry
            fee_entry = JournalEntry(
                timestamp=month_date,
                description=f"Loan Fee Income - {month_name}",
                reference_no=f"FEE-{month_offset:03d}-{now.timestamp()}"
            )
            fee_entry.lines.append(JournalLine(
                account_code="4200",
                debit=Decimal("0.00"),
                credit=fee_income,
                description=f"Loan Fee Income - {month_name}"
            ))
            fee_entry.lines.append(JournalLine(
                account_code="1000",
                debit=fee_income,
                credit=Decimal("0.00"),
                description=f"Loan Fee Income - {month_name}"
            ))
            session.add(fee_entry)
            
            # Operating Expenses Entry
            op_exp_entry = JournalEntry(
                timestamp=month_date,
                description=f"Operating Expenses - {month_name}",
                reference_no=f"EXP-{month_offset:03d}-{now.timestamp()}"
            )
            op_exp_entry.lines.append(JournalLine(
                account_code="5100",
                debit=op_expenses,
                credit=Decimal("0.00"),
                description=f"Operating Expenses - {month_name}"
            ))
            op_exp_entry.lines.append(JournalLine(
                account_code="1000",
                debit=Decimal("0.00"),
                credit=op_expenses,
                description=f"Operating Expenses - {month_name}"
            ))
            session.add(op_exp_entry)
            
            # Interest Expense Entry
            interest_exp_entry = JournalEntry(
                timestamp=month_date,
                description=f"Interest Expense - {month_name}",
                reference_no=f"INTX-{month_offset:03d}-{now.timestamp()}"
            )
            interest_exp_entry.lines.append(JournalLine(
                account_code="5200",
                debit=interest_exp,
                credit=Decimal("0.00"),
                description=f"Interest Expense - {month_name}"
            ))
            interest_exp_entry.lines.append(JournalLine(
                account_code="1000",
                debit=Decimal("0.00"),
                credit=interest_exp,
                description=f"Interest Expense - {month_name}"
            ))
            session.add(interest_exp_entry)
            
            # Provision for Loan Losses Entry
            provision_entry = JournalEntry(
                timestamp=month_date,
                description=f"Provision for Loan Losses - {month_name}",
                reference_no=f"PROV-{month_offset:03d}-{now.timestamp()}"
            )
            provision_entry.lines.append(JournalLine(
                account_code="5300",
                debit=provision,
                credit=Decimal("0.00"),
                description=f"Provision for Loan Losses - {month_name}"
            ))
            provision_entry.lines.append(JournalLine(
                account_code="1000",
                debit=Decimal("0.00"),
                credit=provision,
                description=f"Provision for Loan Losses - {month_name}"
            ))
            session.add(provision_entry)
            
            created_entries += 5
        
        await session.commit()
    
    logger.info(f"GL journal entries seeded (PostgreSQL): {created_entries} entries")
    return {"gl_entries_created": created_entries}


# ============================================================================
# RECOMMENDATION 5: SEED HISTORICAL DATA WITH DATES (PG)
# ============================================================================


async def seed_historical_data_pg() -> Dict[str, Any]:
    """
    Seed historical data with realistic date ranges spanning 2-3 years in PostgreSQL.
    Creates old customer activities, audit logs, and loan statuses.
    
    This enhances testing coverage for:
    - Historical trend analysis
    - Long-term customer journey tracking
    - Audit trail verification
    - Historical reporting
    """
    logger.info("Seeding historical data (PostgreSQL)...")
    session_factory = get_async_session_local()
    created = 0
    
    async with session_factory() as session:
        # Seed old customer activities (2 years back)
        activities = [
            "created", "kyc_submitted", "kyc_verified", "updated_profile",
            "applied_for_loan", "opened_savings_account", "made_payment",
            "loan_disbursed", "loan_closed", "account_closed"
        ]
        
        for idx, activity in enumerate(activities):
            days_ago = 730 - (idx * 60)
            if days_ago < 0:
                days_ago = 30 + idx
            
            activity_log = CustomerActivity(
                customer_id=f"CUST-{1000 + idx}",
                actor_user_id=None,
                actor_username="system",
                action=activity,
                detail=f"Sample activity: {activity}",
                created_at=datetime.now(timezone.utc) - timedelta(days=days_ago),
            )
            session.add(activity_log)
            created += 1
        
        # Seed old audit logs (2 years back)
        actions = [
            ("create_customer", "customer", "success"),
            ("create_loan", "loan", "success"),
            ("approve_loan", "loan", "success"),
            ("disburse_loan", "loan", "success"),
            ("deposit_cash", "transaction", "success"),
            ("withdrawal_cash", "transaction", "success"),
            ("reject_loan", "loan", "failure"),
            ("update_customer", "customer", "success"),
        ]
        
        for act_idx, (action, entity, status) in enumerate(actions):
            days_ago = 730 - (act_idx * 50)
            if days_ago < 0:
                days_ago = 30 + act_idx
            
            audit_log = AuditLog(
                user_id=f"USER-{100 + act_idx}",
                username=f"user_{act_idx}",
                role="various",
                action=action,
                entity=entity,
                entity_id=f"{entity}-{act_idx:06d}",
                ip_address=f"192.168.1.{100 + act_idx}",
                status=status,
                detail=f"Sample {action} action",
                created_at=datetime.now(timezone.utc) - timedelta(days=days_ago),
            )
            session.add(audit_log)
            created += 1
        
        await session.commit()
    
    logger.info(f"Historical data seeded (PostgreSQL): {created} records")
    return {"historical_data_created": created}


# ============================================================================
# CORE DATA SEEDING (PostgreSQL) — Branches, Users, Customers, Loans, Savings
# ============================================================================

DEMO_BRANCHES = [
    {"code": "HQ", "name": "Head Office", "address": "1500 Makati Avenue, Makati City", "city": "Makati", "contact_number": "+63 2 1234 5678"},
    {"code": "BR-QC", "name": "Quezon City Branch", "address": "500 Pioneer Street, Mandaluyong", "city": "Mandaluyong", "contact_number": "+63 2 8765 4321"},
    {"code": "BR-CDO", "name": "Cagayan de Oro Branch", "address": "123 Osmeña Boulevard, Cagayan de Oro", "city": "Cagayan de Oro", "contact_number": "+63 88 123 4567"},
]

DEMO_USERS = [
    {"email": "admin@lending.demo", "username": "admin", "full_name": "Administrator", "role": "admin", "password": "Admin@123Demo", "branch_code": "HQ"},
    {"email": "loan_officer1@lending.demo", "username": "loan_officer_1", "full_name": "Maria Santos", "role": "loan_officer", "password": "LoanOfficer@123", "branch_code": "HQ"},
    {"email": "loan_officer2@lending.demo", "username": "loan_officer_2", "full_name": "Pedro Garcia", "role": "loan_officer", "password": "LoanOfficer@123", "branch_code": "BR-QC"},
    {"email": "teller1@lending.demo", "username": "teller_1", "full_name": "Rosa Villanueva", "role": "teller", "password": "Teller@123Demo", "branch_code": "BR-CDO"},
    {"email": "teller2@lending.demo", "username": "teller_2", "full_name": "Lito Reyes", "role": "teller", "password": "Teller@123Demo", "branch_code": "HQ"},
    {"email": "branch_manager@lending.demo", "username": "branch_manager", "full_name": "Juan Dela Cruz", "role": "branch_manager", "password": "BranchMgr@123", "branch_code": "BR-QC"},
    {"email": "branch_manager_cdo@lending.demo", "username": "branch_manager_cdo", "full_name": "Carlo Mendoza", "role": "branch_manager", "password": "BranchMgr@123", "branch_code": "BR-CDO"},
    {"email": "auditor@lending.demo", "username": "auditor", "full_name": "Ana Reyes", "role": "auditor", "password": "Auditor@123Demo", "branch_code": "HQ"},
]

DEMO_LOAN_PRODUCTS = [
    {
        "product_code": "PER-LN-01", "name": "Personal Loan",
        "description": "General personal loan for any purpose",
        "amortization_type": "flat_rate", "repayment_frequency": "monthly",
        "interest_rate": 14.0, "penalty_rate": 2.0, "grace_period_months": 0,
        "is_active": True, "principal_only_grace": False, "full_grace": False,
        "origination_fee_rate": 1.0, "origination_fee_type": "upfront",
        "prepayment_allowed": True, "prepayment_penalty_rate": 0.5,
        "customer_loan_limit": 500000.0,
    },
    {
        "product_code": "BUS-LN-01", "name": "Business Loan",
        "description": "Loan for business expansion and working capital",
        "amortization_type": "declining_balance", "repayment_frequency": "monthly",
        "interest_rate": 12.0, "penalty_rate": 2.5, "grace_period_months": 1,
        "is_active": True, "principal_only_grace": True, "full_grace": False,
        "origination_fee_rate": 1.5, "origination_fee_type": "upfront",
        "prepayment_allowed": True, "prepayment_penalty_rate": 1.0,
        "customer_loan_limit": 2000000.0,
    },
    {
        "product_code": "SAL-LN-01", "name": "Salary Loan",
        "description": "Quick loan for salaried employees",
        "amortization_type": "flat_rate", "repayment_frequency": "monthly",
        "interest_rate": 10.0, "penalty_rate": 1.5, "grace_period_months": 0,
        "is_active": True, "principal_only_grace": False, "full_grace": False,
        "origination_fee_rate": 0.5, "origination_fee_type": "upfront",
        "prepayment_allowed": True, "prepayment_penalty_rate": 0.0,
        "customer_loan_limit": 300000.0,
    },
    {
        "product_code": "AGR-LN-01", "name": "Agricultural Loan",
        "description": "Seasonal agricultural financing",
        "amortization_type": "declining_balance", "repayment_frequency": "monthly",
        "interest_rate": 10.0, "penalty_rate": 1.5, "grace_period_months": 1,
        "is_active": True, "principal_only_grace": True, "full_grace": False,
        "origination_fee_rate": 1.0, "origination_fee_type": "upfront",
        "prepayment_allowed": False, "prepayment_penalty_rate": 2.0,
        "customer_loan_limit": 1000000.0,
    },
]


async def seed_core_pg() -> Dict[str, Any]:
    """
    Seed core entity data (branches, users, customers, loan products,
    savings accounts, loans) into PostgreSQL.
    This is idempotent — existing records are skipped.
    """
    from uuid import uuid4
    from ..database.pg_core_models import User, Customer, SavingsAccount
    from ..database.pg_models import Branch
    from ..database.pg_loan_models import PGLoanProduct, LoanApplication

    logger.info("=" * 60)
    logger.info("SEEDING CORE DATA (PostgreSQL)")
    logger.info("=" * 60)

    # Ensure tables exist before seeding
    await ensure_tables_exist()

    session_factory = get_async_session_local()
    counts: Dict[str, int] = {}

    # ── 1. Branches ──────────────────────────────────────────────────────────
    logger.info("  [1/6] Seeding branches...")
    branch_map: Dict[str, int] = {}  # code → id
    async with session_factory() as session:
        for bd in DEMO_BRANCHES:
            res = await session.execute(select(Branch).where(Branch.code == bd["code"]))
            existing = res.scalar_one_or_none()
            if not existing:
                br = Branch(**bd)
                session.add(br)
                await session.flush()
                branch_map[bd["code"]] = br.id
                logger.info(f"    ✓ Created branch: {bd['code']}")
            else:
                branch_map[bd["code"]] = existing.id
        await session.commit()
    counts["branches"] = len(DEMO_BRANCHES)
    logger.info(f"  Branches ready ({len(branch_map)} total)")

    # ── 2. Users ─────────────────────────────────────────────────────────────
    logger.info("  [2/6] Seeding users...")
    user_created = 0
    async with session_factory() as session:
        for ud in DEMO_USERS:
            res = await session.execute(select(User).where(User.username == ud["username"]))
            if res.scalar_one_or_none():
                continue
            branch_id = branch_map.get(ud["branch_code"])
            user = User(
                uuid=str(uuid4()),
                email=ud["email"],
                username=ud["username"],
                full_name=ud["full_name"],
                role=ud["role"],
                hashed_password=get_password_hash(ud["password"][:72]),
                branch_id=branch_id,
                branch_code=ud["branch_code"],
                is_active=True,
                is_superuser=(ud["role"] == "admin"),
            )
            session.add(user)
            user_created += 1
            logger.info(f"    ✓ Created user: {ud['username']} ({ud['role']})")
        await session.commit()
    counts["users"] = user_created
    logger.info(f"  Users ready ({user_created} new)")

    # ── 3. Customers ─────────────────────────────────────────────────────────
    logger.info("  [3/6] Seeding customers...")
    demo_customers = [
        # HQ branch
        {"customer_type": "individual", "first_name": "Juan", "middle_name": "de", "last_name": "la Cruz", "display_name": "Juan dela Cruz", "email_address": "juan.sample@example.com", "mobile_number": "+63 900 123 4001", "permanent_address": "123 Makati Avenue, Makati City", "tin_no": "123-456-789-000", "employer_name_address": "TechCorp Philippines, BGC", "job_title": "Senior Software Engineer", "salary_range": "100,000-150,000", "branch_code": "HQ"},
        {"customer_type": "individual", "first_name": "Maria", "middle_name": "Cruz", "last_name": "Santos", "display_name": "Maria Cruz Santos", "email_address": "maria.sample@example.com", "mobile_number": "+63 900 123 4002", "permanent_address": "456 Quezon Avenue, Makati", "tin_no": "987-654-321-000", "employer_name_address": "Finance Corp, Makati", "job_title": "Financial Analyst", "salary_range": "80,000-120,000", "branch_code": "HQ"},
        {"customer_type": "individual", "first_name": "Elena", "middle_name": "Diaz", "last_name": "Cruz", "display_name": "Elena Diaz Cruz", "email_address": "elena.sample@example.com", "mobile_number": "+63 900 123 4007", "permanent_address": "222 Bonifacio Street, Makati", "tin_no": "111-222-333-000", "employer_name_address": "Marketing Pro Agency", "job_title": "Marketing Specialist", "salary_range": "55,000-75,000", "branch_code": "HQ"},
        # BR-QC branch
        {"customer_type": "individual", "first_name": "Pedro", "middle_name": "Lopez", "last_name": "Garcia", "display_name": "Pedro Lopez Garcia", "email_address": "pedro.sample@example.com", "mobile_number": "+63 900 123 4003", "permanent_address": "789 Espana Boulevard, Manila", "tin_no": "456-789-123-000", "employer_name_address": "Manufacturing Inc., Laguna", "job_title": "Operations Manager", "salary_range": "120,000-180,000", "branch_code": "BR-QC"},
        {"customer_type": "individual", "first_name": "Rosa", "middle_name": "Magdalo", "last_name": "Villanueva", "display_name": "Rosa Magdalo Villanueva", "email_address": "rosa.sample@example.com", "mobile_number": "+63 900 123 4004", "permanent_address": "321 San Pedro Street, Muntinlupa", "tin_no": "789-123-456-000", "employer_name_address": "Freelance", "job_title": "Freelance Consultant", "salary_range": "50,000-100,000", "branch_code": "BR-QC"},
        {"customer_type": "individual", "first_name": "Ana", "middle_name": "Reyes", "last_name": "Mendoza", "display_name": "Ana Reyes Mendoza", "email_address": "ana.sample@example.com", "mobile_number": "+63 900 123 4005", "permanent_address": "555 EDSA, Quezon City", "tin_no": "321-654-987-000", "employer_name_address": "Retail Solutions Inc.", "job_title": "Store Manager", "salary_range": "60,000-80,000", "branch_code": "BR-QC"},
        # BR-CDO branch
        {"customer_type": "individual", "first_name": "Carlos", "middle_name": "Miguel", "last_name": "Bautista", "display_name": "Carlos Miguel Bautista", "email_address": "carlos.sample@example.com", "mobile_number": "+63 900 123 4006", "permanent_address": "888 Taft Avenue, Cagayan de Oro", "tin_no": "654-321-098-000", "employer_name_address": "Transport Corp.", "job_title": "Fleet Supervisor", "salary_range": "70,000-90,000", "branch_code": "BR-CDO"},
        {"customer_type": "individual", "first_name": "Roberto", "middle_name": "Torres", "last_name": "Flores", "display_name": "Roberto Torres Flores", "email_address": "roberto.sample@example.com", "mobile_number": "+63 900 123 4008", "permanent_address": "777 Aurora Boulevard, Cagayan de Oro", "tin_no": "444-555-666-000", "employer_name_address": "Agri Ventures Corp.", "job_title": "Farm Owner", "salary_range": "150,000-200,000", "branch_code": "BR-CDO"},
        # Corporate
        {"customer_type": "corporate", "display_name": "TechCorp Philippines Inc.", "company_name": "TechCorp Philippines Inc.", "company_address": "10th Floor, BGC Plaza, BGC, Taguig", "email_address": "corp1@example.com", "mobile_number": "+63 2 1234 0001", "tin_no": "001-234-567-000", "branch_code": "HQ"},
        {"customer_type": "corporate", "display_name": "Manufacturing Industries Ltd.", "company_name": "Manufacturing Industries Ltd.", "company_address": "Laguna Technopark, Sta. Rosa, Laguna", "email_address": "corp2@example.com", "mobile_number": "+63 49 5678 0001", "tin_no": "002-345-678-000", "branch_code": "BR-QC"},
    ]
    cust_map: Dict[str, int] = {}  # display_name → id
    cust_created = 0
    async with session_factory() as session:
        for cd in demo_customers:
            res = await session.execute(
                select(Customer).where(Customer.display_name == cd["display_name"])
            )
            existing = res.scalar_one_or_none()
            if existing:
                cust_map[cd["display_name"]] = existing.id
                continue
            branch_id = branch_map.get(cd["branch_code"], branch_map.get("HQ"))
            cust = Customer(
                customer_type=cd["customer_type"],
                first_name=cd.get("first_name"),
                middle_name=cd.get("middle_name"),
                last_name=cd.get("last_name"),
                display_name=cd["display_name"],
                email_address=cd.get("email_address"),
                mobile_number=cd.get("mobile_number"),
                permanent_address=cd.get("permanent_address"),
                tin_no=cd.get("tin_no"),
                employer_name_address=cd.get("employer_name_address"),
                job_title=cd.get("job_title"),
                salary_range=cd.get("salary_range"),
                company_name=cd.get("company_name"),
                company_address=cd.get("company_address"),
                branch_id=branch_id,
                branch_code=cd["branch_code"],
                is_active=True,
            )
            session.add(cust)
            await session.flush()
            cust_map[cd["display_name"]] = cust.id
            cust_created += 1
            logger.info(f"    ✓ Created customer: {cd['display_name']}")
        await session.commit()
    counts["customers"] = cust_created
    logger.info(f"  Customers ready ({cust_created} new)")

    # ── 4. Loan Products ─────────────────────────────────────────────────────
    logger.info("  [4/6] Seeding loan products...")
    product_map: Dict[str, int] = {}  # product_code → id
    prod_created = 0
    async with session_factory() as session:
        for pd in DEMO_LOAN_PRODUCTS:
            res = await session.execute(
                select(PGLoanProduct).where(PGLoanProduct.product_code == pd["product_code"])
            )
            existing = res.scalar_one_or_none()
            if existing:
                product_map[pd["product_code"]] = existing.id
                continue
            prod = PGLoanProduct(**pd)
            session.add(prod)
            await session.flush()
            product_map[pd["product_code"]] = prod.id
            prod_created += 1
            logger.info(f"    ✓ Created loan product: {pd['name']}")
        await session.commit()
    counts["loan_products"] = prod_created
    logger.info(f"  Loan products ready ({prod_created} new)")

    # ── 5. Savings Accounts ──────────────────────────────────────────────────
    logger.info("  [5/6] Seeding savings accounts...")
    savings_map: Dict[int, int] = {}  # customer_id → savings_account_id
    savings_created = 0
    now = datetime.now(timezone.utc)
    account_counter = 1000
    async with session_factory() as session:
        for display_name, cust_id in cust_map.items():
            res = await session.execute(
                select(SavingsAccount).where(SavingsAccount.customer_id == cust_id)
            )
            if res.scalar_one_or_none():
                continue
            account_counter += 1
            acct_num = f"SA-{account_counter:06d}"
            balance = Decimal("50000.00") if "Corp" not in display_name else Decimal("250000.00")
            sa = SavingsAccount(
                account_number=acct_num,
                customer_id=cust_id,
                account_type="regular",
                balance=balance,
                currency="PHP",
                status="active",
                interest_rate=Decimal("0.25"),
                opened_at=now - timedelta(days=180),
            )
            session.add(sa)
            await session.flush()
            savings_map[cust_id] = sa.id
            savings_created += 1
            logger.info(f"    ✓ Created savings account: {acct_num} for customer #{cust_id}")
        await session.commit()
    counts["savings_accounts"] = savings_created
    logger.info(f"  Savings accounts ready ({savings_created} new)")

    # ── 6. Loans ─────────────────────────────────────────────────────────────
    logger.info("  [6/6] Seeding loans...")
    cust_ids = list(cust_map.values())
    # Only use individual customers
    ind_cust_ids = cust_ids[:8]  # first 8 are individual customers
    personal_prod_id = product_map.get("PER-LN-01")
    business_prod_id = product_map.get("BUS-LN-01")
    salary_prod_id = product_map.get("SAL-LN-01")

    # Loan number counter
    loan_counter = 1
    loan_scenarios = []
    if len(ind_cust_ids) >= 1 and personal_prod_id:
        loan_scenarios.append({"customer_id": ind_cust_ids[0], "product_id": personal_prod_id, "principal": Decimal("150000.00"), "term_months": 24, "status": "submitted", "branch_code": "HQ"})
    if len(ind_cust_ids) >= 2 and salary_prod_id:
        loan_scenarios.append({"customer_id": ind_cust_ids[1], "product_id": salary_prod_id, "principal": Decimal("75000.00"), "term_months": 12, "status": "reviewing", "branch_code": "HQ"})
    if len(ind_cust_ids) >= 3 and personal_prod_id:
        loan_scenarios.append({"customer_id": ind_cust_ids[2], "product_id": personal_prod_id, "principal": Decimal("200000.00"), "term_months": 36, "status": "approved", "approved_principal": Decimal("195000.00"), "approved_rate": Decimal("13.50"), "branch_code": "HQ"})
    if len(ind_cust_ids) >= 4 and business_prod_id:
        loan_scenarios.append({"customer_id": ind_cust_ids[3], "product_id": business_prod_id, "principal": Decimal("500000.00"), "term_months": 36, "status": "active", "approved_principal": Decimal("480000.00"), "approved_rate": Decimal("12.00"), "outstanding_balance": Decimal("350000.00"), "months_paid": 6, "disbursed_at": now - timedelta(days=180), "branch_code": "BR-QC"})
    if len(ind_cust_ids) >= 5 and salary_prod_id:
        loan_scenarios.append({"customer_id": ind_cust_ids[4], "product_id": salary_prod_id, "principal": Decimal("50000.00"), "term_months": 12, "status": "paid", "approved_principal": Decimal("50000.00"), "approved_rate": Decimal("10.00"), "outstanding_balance": Decimal("0.00"), "months_paid": 12, "disbursed_at": now - timedelta(days=365), "branch_code": "BR-QC"})
    if len(ind_cust_ids) >= 6 and personal_prod_id:
        loan_scenarios.append({"customer_id": ind_cust_ids[5], "product_id": personal_prod_id, "principal": Decimal("100000.00"), "term_months": 24, "status": "active", "approved_principal": Decimal("95000.00"), "approved_rate": Decimal("14.00"), "outstanding_balance": Decimal("75000.00"), "months_paid": 4, "disbursed_at": now - timedelta(days=120), "branch_code": "BR-QC"})
    if len(ind_cust_ids) >= 7 and business_prod_id:
        loan_scenarios.append({"customer_id": ind_cust_ids[6], "product_id": business_prod_id, "principal": Decimal("800000.00"), "term_months": 48, "status": "active", "approved_principal": Decimal("750000.00"), "approved_rate": Decimal("12.00"), "outstanding_balance": Decimal("650000.00"), "months_paid": 6, "disbursed_at": now - timedelta(days=180), "branch_code": "BR-CDO"})
    if len(ind_cust_ids) >= 8 and salary_prod_id:
        loan_scenarios.append({"customer_id": ind_cust_ids[7], "product_id": salary_prod_id, "principal": Decimal("30000.00"), "term_months": 6, "status": "rejected", "branch_code": "BR-CDO"})

    loans_created = 0
    async with session_factory() as session:
        for ls in loan_scenarios:
            # Check if loan already exists for this customer+product+principal
            res = await session.execute(
                select(LoanApplication).where(
                    LoanApplication.customer_id == str(ls["customer_id"]),
                    LoanApplication.principal == ls["principal"],
                )
            )
            if res.scalar_one_or_none():
                continue
            loan = LoanApplication(
                customer_id=str(ls["customer_id"]),
                product_id=ls["product_id"],
                principal=ls["principal"],
                term_months=ls["term_months"],
                status=ls["status"],
                branch_code=ls.get("branch_code", "HQ"),
                approved_principal=ls.get("approved_principal"),
                approved_rate=ls.get("approved_rate"),
                outstanding_balance=ls.get("outstanding_balance"),
                months_paid=ls.get("months_paid", 0),
                disbursed_at=ls.get("disbursed_at"),
            )
            session.add(loan)
            loans_created += 1
            logger.info(f"    ✓ Created loan: {ls['status']} for customer #{ls['customer_id']}")
        await session.commit()
    counts["loans"] = loans_created
    logger.info(f"  Loans ready ({loans_created} new)")

    logger.info("=" * 60)
    logger.info(f"CORE DATA SEEDING COMPLETE ✅ — {sum(counts.values())} new records")
    logger.info("=" * 60)
    return counts


# ============================================================================
# CUSTOMER ACTIVITIES SEEDING (PostgreSQL)
# ============================================================================


async def seed_customer_activities() -> Dict[str, Any]:
    """
    Seed customer activities linked to real customers in PostgreSQL.
    Creates realistic activity history for each customer.
    """
    logger.info("Seeding customer activities (PostgreSQL)...")
    session_factory = get_async_session_local()
    created_activities = 0
    
    async with session_factory() as session:
        # Get all active customers
        result = await session.execute(select(Customer).where(Customer.is_active == True))
        customers = result.scalars().all()
        
        if not customers:
            logger.warning("No active customers found to seed activities for")
            return {"customer_activities_created": 0}
        
        activities = [
            "created", "kyc_submitted", "kyc_verified", "updated_profile",
            "applied_for_loan", "opened_savings_account", "made_payment",
            "loan_disbursed", "loan_closed", "account_closed", "contacted",
            "document_uploaded", "loan_reviewed", "loan_approved"
        ]
        
        for customer in customers:
            customer_id = str(customer.id)
            customer_name = customer.display_name
            # Generate 5-10 activities per customer going back 1 year
            num_activities = 5 + (customer.id % 6)
            
            for idx in range(num_activities):
                days_ago = 365 - (idx * 30)
                if days_ago < 0:
                    days_ago = 30 + idx
                
                activity_date = datetime.now(timezone.utc) - timedelta(days=days_ago)
                activity = activities[idx % len(activities)]
                
                # Get a random user for actor (optional)
                actor_user_id = None
                actor_username = "system"
                if customer.id % 3 == 0:
                    # Use a staff member as actor
                    result = await session.execute(select(User).where(User.is_active == True).limit(1))
                    users = result.scalars().all()
                    if users:
                        actor_user_id = str(users[0].id)
                        actor_username = users[0].username
                
                activity_log = CustomerActivity(
                    customer_id=customer_id,
                    actor_user_id=actor_user_id,
                    actor_username=actor_username,
                    action=activity,
                    detail=f"{customer_name} - {activity}",
                    created_at=activity_date,
                )
                session.add(activity_log)
                created_activities += 1
        
        await session.commit()
    
    logger.info(f"Customer activities seeded (PostgreSQL): {created_activities} records")
    return {"customer_activities_created": created_activities}


# ============================================================================
# COLLECTIONS SEEDING (PostgreSQL)
# ============================================================================


async def seed_collections() -> Dict[str, Any]:
    """
    Seed collections data linked to real customers in PostgreSQL.
    Creates realistic collection records with various statuses and due dates.
    """
    logger.info("Seeding collections (PostgreSQL)...")
    session_factory = get_async_session_local()
    created_collections = 0
    
    async with session_factory() as session:
        # Get all active customers (simpler approach)
        result = await session.execute(
            select(Customer).where(Customer.is_active == True)
        )
        customers_with_loans = result.scalars().all()
        
        if not customers_with_loans:
            logger.warning("No active customers found to seed collections for")
            return {"collections_created": 0}
        
        statuses = ["pending", "partial", "collected", "overdue", "written_off"]
        collection_types = ["principal", "interest", "penalty"]
        
        for customer in customers_with_loans[:5]:  # Limit to first 5 customers
            customer_id = str(customer.id)
            customer_name = customer.display_name
            
            # Generate 2-3 collections per customer
            num_collections = 2 + (customer.id % 2)
            
            for idx in range(num_collections):
                # Create collections with various due dates
                months_ago = 1 + idx
                due_date = (datetime.now(timezone.utc) - timedelta(days=30 * months_ago)).date()
                
                # Calculate amount based on loan status
                base_amount = 50000 + (idx * 10000)
                status = "pending" if months_ago <= 1 else ("overdue" if months_ago >= 2 else "collected")
                
                collection = Collection(
                    customer_id=customer_id,
                    amount=Decimal(str(base_amount)),
                    status=status,
                    due_date=due_date,
                    collection_type=collection_types[idx % len(collection_types)],
                    reference_number=f"COL-{months_ago:03d}-{customer.id}",
                    notes=f"Collection for {customer_name}",
                    created_at=datetime.now(timezone.utc) - timedelta(days=30 * months_ago),
                    updated_at=datetime.now(timezone.utc),
                )
                session.add(collection)
                created_collections += 1
        
        await session.commit()
    
    logger.info(f"Collections seeded (PostgreSQL): {created_collections} records")
    return {"collections_created": created_collections}


# ============================================================================
# ENHANCED MAIN ORCHESTRATION (PostgreSQL Only)
# ============================================================================


async def seed_demo_data_enhanced() -> Dict[str, Any]:
    """
    Main orchestration function to seed all enhanced demo data into PostgreSQL.
    Seeds core entities first, then supplemental data.
    """
    logger.info("=" * 70)
    logger.info("STARTING ENHANCED DEMO DATA SEEDING (PostgreSQL)")
    logger.info("=" * 70)

    results = {}

    try:
        # CORE: Seed branches, users, customers, loan products, savings, loans
        results["core_data"] = await seed_core_pg()

        # Seed customer activities with real customer IDs
        results["customer_activities"] = await seed_customer_activities()

        # Seed collections linked to customers with loans (skip if table doesn't exist)
        try:
            results["collections"] = await seed_collections()
        except Exception as e:
            if "collections" in str(e).lower() and "does not exist" in str(e).lower():
                logger.warning("Skipping collections seeding - table doesn't exist yet")
                results["collections"] = {"collections_created": 0, "note": "Table not created - run migration first"}
            else:
                raise

        # Recommendation 3: Seed PEP records
        results["pep_records"] = await seed_pep_records_comprehensive()

        # Recommendation 4: Seed GL entries
        results["gl_entries"] = await seed_gl_entries_comprehensive()

        # Recommendation 5: Seed historical data
        results["historical_data"] = await seed_historical_data_pg()

        # Summary
        logger.info("=" * 70)
        logger.info("ENHANCED DEMO DATA SEEDING COMPLETE ✅")
        logger.info("=" * 70)
        logger.info("Summary:")
        for key, value in results.items():
            if isinstance(value, dict):
                for k, v in value.items():
                    if isinstance(v, int) and v > 0:
                        logger.info(f"  {key}.{k}: {v} records")

        return results

    except Exception as exc:
        logger.error(f"Error during demo data seeding: {exc}", exc_info=True)
        raise


if __name__ == "__main__":
    asyncio.run(seed_demo_data_enhanced())
