"""
AML Compliance Module
=====================

Implements:
- OFAC/Watchlist screening on customer onboarding
- PEP (Politically Exposed Persons) flagging
- Suspicious Activity Report (SAR) flagging
- Currency Transaction Report (CTR) auto-flagging
- KYC document expiry alerts

Compliance: BSP Circular 1048 (AML), RA 9160 (AMLA), RA 10173 (Data Privacy)
"""

import re
import logging
from datetime import datetime, timedelta
from decimal import Decimal
from typing import List, Optional, Dict, Any
from sqlalchemy import select, func
from sqlalchemy.orm import Session
import strawberry
from typing import Any
from strawberry.types import Info
from fastapi import HTTPException, status

logger = logging.getLogger(__name__)

from .models import UserInDB
from .database.postgres import get_db_session
from .database.pg_core_models import Customer
from .database.pg_loan_models import LoanApplication as Loan
from .database.pg_models import KYCDocument, CustomerActivity, AMLAlert
from .database.pg_accounting_models import GLAccount, JournalEntry, JournalLine
from .config import settings

# Note: Loan doesn't exist - use Loan from pg_core_models
# Note: get_loan_by_id removed during migration - use database session directly
def get_loan_by_id(*args, **kwargs):
    """Placeholder for loan retrieval during migration."""
    return None

# Import external integrations
try:
    from .aml_external_integrations import (
        check_pep_external,
        check_ofac_external,
        create_sar_report,
        submit_sar_to_regulator,
        send_aml_alert_notification,
        run_daily_compliance_reports,
        run_weekly_compliance_reports,
        run_monthly_compliance_reports,
        resolve_aml_alert,
        escalate_aml_alert,
        get_unresolved_alerts
    )
except ImportError:
    logger = logging.getLogger(__name__)
    logger.warning("External integrations not available")

# ========================================================================
# OFAC/Watchlist Databases (Sample - in production, use external APIs)
# ========================================================================

OFAC_SANCTIONED_COUNTRIES = {
    "North Korea", "Iran", "Syria", "Cuba", "Crimea region",
    "Russia", "Belarus"
}

PEP_DATABASE = {
    "John Doe", "Maria Santos", "Juan Cruz", "Jose Reyes",
    "High-Risk Politicians List"  # In production: integrate with external PEP databases
}

SUSPICIOUS_PATTERN_KEYWORDS = [
    "money laundering", "terrorist financing", "fraud", "bribery",
    "embezzlement", "smuggling", "drug trafficking"
]

CTR_THRESHOLD = 500000  # PHP 500,000 threshold for CTR (BSP requirement)
CTR_CASH_THRESHOLD = 100000  # PHP 100,000 cash transaction threshold


# ========================================================================
# 1. OFAC/Watchlist Screening
# ========================================================================

async def check_ofac_compliance(customer_data: dict) -> Any:
    """
    Check customer against OFAC and other watchlists.
    Returns screening results and risk score.
    """
    risk_score = 0
    flags = []
    
    # Check sanctioned countries
    if customer_data.get('country') in OFAC_SANCTIONED_COUNTRIES:
        risk_score += 40
        flags.append({
            "type": "sanctioned_country",
            "severity": "high",
            "message": f"Customer is from a sanctioned country: {customer_data.get('country')}"
        })
    
    # Check PEP
    if customer_data.get('is_pep') or any(
        keyword.lower() in (customer_data.get('full_name', '') or '').lower()
        for keyword in PEP_DATABASE
    ):
        risk_score += 30
        flags.append({
            "type": "pep",
            "severity": "high",
            "message": "Customer is a Politically Exposed Person (PEP)"
        })
    
    # Check business structure for PEP involvement
    if customer_data.get('entity_type') == 'corporate':
        for officer in customer_data.get('officers', []):
            if any(
                keyword.lower() in (officer.get('name', '') or '').lower()
                for keyword in PEP_DATABASE
            ):
                risk_score += 25
                flags.append({
                    "type": "corporate_pep",
                    "severity": "medium",
                    "message": f"Corporate officer {officer.get('name')} is a PEP"
                })
    
    # Check for suspicious keywords in customer information
    for field in ['occupation', 'business_activity', 'notes']:
        if customer_data.get(field):
            for keyword in SUSPICIOUS_PATTERN_KEYWORDS:
                if keyword.lower() in str(customer_data.get(field, '')).lower():
                    risk_score += 15
                    flags.append({
                        "type": "suspicious_keyword",
                        "severity": "medium",
                        "message": f"Suspicious keyword found in {field}: {keyword}"
                    })
    
    # Determine compliance status
    compliance_status = "approved"
    if risk_score >= 50:
        compliance_status = "rejected"
    elif risk_score >= 20:
        compliance_status = "manual_review"
    
    return {
        "compliance_status": compliance_status,
        "risk_score": risk_score,
        "flags": flags,
        "screened_at": datetime.utcnow()
    }


# ========================================================================
# 2. PEP (Politically Exposed Persons) Flagging
# ========================================================================

async def check_pep_status(customer_id: str, customer_data: dict) -> Any:
    """Check if customer is a PEP and flag accordingly."""
    
    is_pep = False
    pep_type = None
    enhanced_dda_required = False
    
    # Check against PEP database
    full_name = customer_data.get('full_name', '')
    for pep_name in PEP_DATABASE:
        if pep_name.lower() in full_name.lower():
            is_pep = True
            pep_type = "foreign_pep"
            enhanced_dda_required = True
            break
    
    # Check job title for PEP indicators
    job_title = customer_data.get('job_title', '').lower()
    if not is_pep:
        pep_indicators = [
            'senator', 'congressman', 'representative', 'president',
            'governor', 'mayor', 'ambassador', 'minister', 'secretary',
            'judge', 'justice', 'commissioner', 'director', 'ambassador'
        ]
        for indicator in pep_indicators:
            if indicator in job_title:
                is_pep = True
                pep_type = "domestic_pep"
                enhanced_dda_required = True
                break
    
    # Check if family member or close associate
    if not is_pep:
        for relation in customer_data.get('relations', []):
            if relation.get('relation_type') in ['spouse', 'child', 'parent', 'sibling']:
                related_name = relation.get('name', '')
                for pep_name in PEP_DATABASE:
                    if pep_name.lower() in related_name.lower():
                        is_pep = True
                        pep_type = "pep_associate"
                        enhanced_dda_required = True
                        break
    
    return {
        "is_pep": is_pep,
        "pep_type": pep_type,
        "enhanced_dda_required": enhanced_dda_required,
        "flagged_at": datetime.utcnow()
    }


# ========================================================================
# 3. Suspicious Activity Report (SAR) Flagging
# ========================================================================

async def flag_suspicious_activity(transaction_data: dict, customer_id: str) -> Optional[AMLAlert]:
    """
    Flag suspicious activities and create SAR if needed.
    Returns AMLAlert if suspicious activity detected.
    """
    
    is_suspicious = False
    reason = []
    
    # Check transaction amount patterns
    amount = float(transaction_data.get('amount', 0))
    
    # Pattern 1: Structuring (multiple transactions just below threshold)
    if 90000 <= amount <= 100000:  # Just below CTR threshold
        is_suspicious = True
        reason.append("Potential structuring: transaction just below CTR threshold")
    
    # Pattern 2: Unusual large cash transactions
    if transaction_data.get('payment_method') == 'cash' and amount > 200000:
        is_suspicious = True
        reason.append(f"Unusual large cash transaction: PHP {amount:,.2f}")
    
    # Pattern 3: Rapid multiple transactions
    if transaction_data.get('transaction_count_in_hour', 0) > 5:
        is_suspicious = True
        reason.append(f"Rapid transactions: {transaction_data.get('transaction_count_in_hour')} in last hour")
    
    # Pattern 4: Round numbers (possible structuring)
    if amount == int(amount) and amount > 100000:
        is_suspicious = True
        reason.append("Round number transaction (possible structuring)")
    
    # Pattern 5: Unusual geographic patterns
    if transaction_data.get('location') and transaction_data.get('location') not in ['Philippines', 'PH']:
        is_suspicious = True
        reason.append(f"Unusual location: {transaction_data.get('location')}")
    
    if is_suspicious:
        alert = AMLAlert(
            customer_id=customer_id,
            transaction_id=transaction_data.get('transaction_id'),
            alert_type="suspicious_activity",
            severity="medium",
            description=" ".join(reason),
            reported_at=datetime.utcnow(),
            reported_by=transaction_data.get('processed_by', 'system'),
            status="pending_review"
        )
        return alert
    
    return None


# ========================================================================
# 4. Currency Transaction Report (CTR) Auto-Flagging
# ========================================================================

async def check_ctr_requirements(transaction_data: dict, customer_id: str) -> Optional[AMLAlert]:
    """
    Check if transaction meets CTR reporting threshold (PHP 500,000+).
    Returns AMLAlert if CTR should be filed.
    """
    
    amount = float(transaction_data.get('amount', 0))
    payment_method = transaction_data.get('payment_method', '')
    
    # BSP Circular 1048: CTR for cash transactions > PHP 500,000
    # Also for aggregate transactions > PHP 500,000 in a day
    if payment_method == 'cash' and amount >= CTR_THRESHOLD:
        alert = AMLAlert(
            customer_id=customer_id,
            transaction_id=transaction_data.get('transaction_id'),
            alert_type="ctr",
            severity="high",
            description=f"CTR threshold exceeded: Cash transaction of PHP {amount:,.2f}",
            reported_at=datetime.utcnow(),
            reported_by=transaction_data.get('processed_by', 'system'),
            status="pending_review",
            requires_filing=True,
            ctr_amount=amount
        )
        return alert
    
    # Check aggregate daily transactions
    # In production, query database for today's transactions
    daily_total = float(transaction_data.get('daily_total', 0))
    if daily_total >= CTR_THRESHOLD and payment_method == 'cash':
        alert = AMLAlert(
            customer_id=customer_id,
            transaction_id=transaction_data.get('transaction_id'),
            alert_type="ctr_aggregate",
            severity="high",
            description=f"Daily aggregate exceeded: Total cash transactions PHP {daily_total:,.2f}",
            reported_at=datetime.utcnow(),
            reported_by=transaction_data.get('processed_by', 'system'),
            status="pending_review",
            requires_filing=True,
            ctr_amount=daily_total
        )
        return alert
    
    return None


# ========================================================================
# 5. KYC Document Expiry Alerts
# ========================================================================

async def get_expired_kyc_documents() -> List[Dict[str, Any]]:
    """
    Get list of KYC documents that have expired or are expiring soon.
    """
    expiry_threshold = datetime.utcnow() + timedelta(days=30)
    
    alerts = []
    
    # Query expired documents
    async for session in get_db_session():
        result = await session.execute(
            select(KYCDocument).where(
                KYCDocument.expires_at < expiry_threshold,
                KYCDocument.status == "approved"
            )
        )
        
        for doc in result.scalars().all():
            days_until_expiry = (doc.expires_at - datetime.utcnow()).days
            
            alert = {
                "document_id": doc.id,
                "customer_id": doc.customer_id,
                "doc_type": doc.doc_type,
                "file_name": doc.file_name,
                "expiry_date": doc.expires_at,
                "days_remaining": days_until_expiry,
                "severity": "critical" if days_until_expiry < 0 else "warning",
                "message": f"KYC document expires in {days_until_expiry} days"
            }
            alerts.append(alert)
    
    return alerts


async def create_kyc_expiry_alert(customer_id: str, document_id: int, days_remaining: int) -> None:
    """
    Create a customer activity log for KYC expiry.
    """
    alert_type = "critical" if days_remaining < 0 else "warning"
    message = f"KYC document expired" if days_remaining < 0 else f"KYC document expires in {days_remaining} days"
    
    activity = CustomerActivity(
        customer_id=customer_id,
        actor_user_id="system",
        actor_username="auto_alert",
        action="kyc_expiry_alert",
        detail=message
    )
    
    async for session in get_db_session():
        session.add(activity)
        await session.commit()


# ========================================================================
# 6. Regulatory Reporting: Portfolio At Risk (PAR)
# ========================================================================

async def calculate_par_metrics() -> Any:
    """
    Calculate Portfolio At Risk metrics.
    PAR1 = Loans 1-30 days past due
    PAR7 = Loans 7-30 days past due  
    PAR30 = Loans 31-90 days past due
    PAR90 = Loans 90+ days past due
    """
    
    par_metrics = {
        "total_outstanding": 0.0,
        "par1": {"amount": 0.0, "percentage": 0.0, "loan_count": 0},
        "par7": {"amount": 0.0, "percentage": 0.0, "loan_count": 0},
        "par30": {"amount": 0.0, "percentage": 0.0, "loan_count": 0},
        "par90": {"amount": 0.0, "percentage": 0.0, "loan_count": 0},
        "current": {"amount": 0.0, "percentage": 0.0, "loan_count": 0}
    }
    
    # Calculate total outstanding
    total_outstanding = 0.0
    loan_counts = {
        "par1": 0, "par7": 0, "par30": 0, "par90": 0, "current": 0
    }
    
    async for session in get_db_session():
        # Get all active loans
        result = await session.execute(select(Loan).where(Loan.status == "active"))
        loans = result.scalars().all()
        
        total_outstanding = sum(float(loan.outstanding_balance or 0) for loan in loans)
        
        for loan in loans:
            days_past_due = loan.days_past_due or 0
            outstanding = float(loan.outstanding_balance or 0)
            
            if days_past_due <= 0:
                par_metrics["current"]["amount"] += outstanding
                par_metrics["current"]["loan_count"] += 1
                loan_counts["current"] += 1
            elif days_past_due <= 30:
                par_metrics["par1"]["amount"] += outstanding
                par_metrics["par1"]["loan_count"] += 1
                loan_counts["par1"] += 1
                
                if days_past_due >= 7:
                    par_metrics["par7"]["amount"] += outstanding
                    par_metrics["par7"]["loan_count"] += 1
                    loan_counts["par7"] += 1
            elif days_past_due <= 90:
                par_metrics["par30"]["amount"] += outstanding
                par_metrics["par30"]["loan_count"] += 1
                loan_counts["par30"] += 1
            else:
                par_metrics["par90"]["amount"] += outstanding
                par_metrics["par90"]["loan_count"] += 1
                loan_counts["par90"] += 1
    
    # Calculate percentages
    if total_outstanding > 0:
        for bucket in ["par1", "par7", "par30", "par90", "current"]:
            par_metrics[bucket]["percentage"] = round(
                (par_metrics[bucket]["amount"] / total_outstanding) * 100, 2
            )
    
    par_metrics["total_outstanding"] = round(total_outstanding, 2)
    
    return par_metrics


# ========================================================================
# 7. Non-Performing Loans (NPL) Report
# ========================================================================

async def calculate_npl_metrics() -> Any:
    """
    Calculate Non-Performing Loans metrics.
    NPL = Loans that are 90+ days past due or in default
    """
    
    npl_metrics = {
        "total_loans": 0,
        "npl_count": 0,
        "npl_amount": 0.0,
        "npl_ratio": 0.0,
        "npl_by_category": {
            "90_plus_days": {"count": 0, "amount": 0.0},
            "default": {"count": 0, "amount": 0.0},
            "restructured": {"count": 0, "amount": 0.0}
        }
    }
    
    async for session in get_db_session():
        result = await session.execute(select(Loan))
        loans = result.scalars().all()
        
        npl_metrics["total_loans"] = len(loans)
        
        for loan in loans:
            if loan.status == "past_due" and (loan.days_past_due or 0) >= 90:
                npl_metrics["npl_by_category"]["90_plus_days"]["count"] += 1
                npl_metrics["npl_by_category"]["90_plus_days"]["amount"] += float(loan.outstanding_balance or 0)
                npl_metrics["npl_count"] += 1
                npl_metrics["npl_amount"] += float(loan.outstanding_balance or 0)
            elif loan.status == "default":
                npl_metrics["npl_by_category"]["default"]["count"] += 1
                npl_metrics["npl_by_category"]["default"]["amount"] += float(loan.outstanding_balance or 0)
                npl_metrics["npl_count"] += 1
                npl_metrics["npl_amount"] += float(loan.outstanding_balance or 0)
            elif loan.status == "restructured":
                npl_metrics["npl_by_category"]["restructured"]["count"] += 1
                npl_metrics["npl_by_category"]["restructured"]["amount"] += float(loan.outstanding_balance or 0)
    
    if npl_metrics["total_loans"] > 0:
        npl_metrics["npl_ratio"] = round(
            (npl_metrics["npl_amount"] / sum(float(loan.outstanding_balance or 0) for loan in loans)) * 100, 2
        )
    
    return npl_metrics


# ========================================================================
# 8. Loan Loss Reserve (LLR) Report
# ========================================================================

async def calculate_llr() -> Any:
    """
    Calculate Loan Loss Reserve based on PAR aging.
    """
    
    llr_metrics = {
        "total_loans_outstanding": 0.0,
        "llr_required": 0.0,
        "llr_by_bucket": {
            "current": {"amount": 0.0, "rate": 0.0, "percentage": 0.0},
            "1_30_days": {"amount": 0.0, "rate": 0.02, "percentage": 0.0},
            "31_60_days": {"amount": 0.0, "rate": 0.05, "rate": 0.05, "percentage": 0.0},
            "61_90_days": {"amount": 0.0, "rate": 0.10, "percentage": 0.0},
            "90_plus_days": {"amount": 0.0, "rate": 0.25, "percentage": 0.0},
            "doubtful": {"amount": 0.0, "rate": 0.50, "percentage": 0.0}
        },
        "llr_current_balance": 0.0,
        "llr_needed": 0.0,
        "llr_provision_required": 0.0
    }
    
    # Current LLR balance (from GL account 1400)
    async for session in get_db_session():
        result = await session.execute(
            select(func.sum(JournalLine.debit - JournalLine.credit)).where(
                JournalLine.account_code == "1400"
            )
        )
        llr_balance = result.scalar_one() or 0
        llr_metrics["llr_current_balance"] = float(llr_balance)
        
        # Get active loans
        result = await session.execute(select(Loan).where(Loan.status == "active"))
        loans = result.scalars().all()
        
        total_outstanding = sum(float(loan.outstanding_balance or 0) for loan in loans)
        llr_metrics["total_loans_outstanding"] = total_outstanding
        
        for loan in loans:
            days_past_due = loan.days_past_due or 0
            outstanding = float(loan.outstanding_balance or 0)
            
            if days_past_due <= 0:
                llr_metrics["llr_by_bucket"]["current"]["amount"] += outstanding
            elif days_past_due <= 30:
                llr_metrics["llr_by_bucket"]["1_30_days"]["amount"] += outstanding
                llr_metrics["llr_by_bucket"]["1_30_days"]["rate"] = 0.02
            elif days_past_due <= 60:
                llr_metrics["llr_by_bucket"]["31_60_days"]["amount"] += outstanding
                llr_metrics["llr_by_bucket"]["31_60_days"]["rate"] = 0.05
            elif days_past_due <= 90:
                llr_metrics["llr_by_bucket"]["61_90_days"]["amount"] += outstanding
                llr_metrics["llr_by_bucket"]["61_90_days"]["rate"] = 0.10
            else:
                llr_metrics["llr_by_bucket"]["90_plus_days"]["amount"] += outstanding
                llr_metrics["llr_by_bucket"]["90_plus_days"]["rate"] = 0.25
    
    # Calculate required LLR
    required_llr = 0.0
    for bucket in ["1_30_days", "31_60_days", "61_90_days", "90_plus_days"]:
        required_llr += (
            llr_metrics["llr_by_bucket"][bucket]["amount"] *
            llr_metrics["llr_by_bucket"][bucket]["rate"]
        )
    
    llr_metrics["llr_required"] = round(required_llr, 2)
    llr_metrics["llr_needed"] = round(max(0, required_llr - llr_metrics["llr_current_balance"]), 2)
    
    if llr_metrics["total_loans_outstanding"] > 0:
        for bucket in llr_metrics["llr_by_bucket"]:
            llr_metrics["llr_by_bucket"][bucket]["percentage"] = round(
                (llr_metrics["llr_by_bucket"][bucket]["amount"] / llr_metrics["total_loans_outstanding"]) * 100, 2
            )
    
    return llr_metrics


# ========================================================================
# 9. Financial Statements - Trial Balance
# ========================================================================

async def generate_trial_balance(period_start: datetime, period_end: datetime) -> Any:
    """
    Generate Trial Balance from GL entries for a specific period.
    """
    
    trial_balance = {
        "period_start": period_start,
        "period_end": period_end,
        "accounts": {},
        "total_debits": 0.0,
        "total_credits": 0.0
    }
    
    async for session in get_db_session():
        # Get all GL accounts
        result = await session.execute(select(GLAccount))
        accounts = result.scalars().all()
        
        for account in accounts:
            # Calculate balances
            result = await session.execute(
                select(
                    func.sum(JournalLine.debit).label('total_debit'),
                    func.sum(JournalLine.credit).label('total_credit')
                ).where(
                    JournalLine.account_code == account.code,
                    JournalEntry.timestamp >= period_start,
                    JournalEntry.timestamp <= period_end
                )
            )
            
            balances = result.fetchone()
            
            if balances:
                total_debit = float(balances[0] or 0)
                total_credit = float(balances[1] or 0)
                
                # Calculate net balance
                if account.type in ["asset", "expense"]:
                    net_balance = total_debit - total_credit
                else:
                    net_balance = total_credit - total_debit
                
                trial_balance["accounts"][account.code] = {
                    "account_name": account.name,
                    "account_type": account.type,
                    "total_debit": total_debit,
                    "total_credit": total_credit,
                    "net_balance": net_balance
                }
                
                trial_balance["total_debits"] += total_debit
                trial_balance["total_credits"] += total_credit
    
    trial_balance["total_debits"] = round(trial_balance["total_debits"], 2)
    trial_balance["total_credits"] = round(trial_balance["total_credits"], 2)
    
    return trial_balance


# ========================================================================
# 10. Financial Statements - Income Statement (P&L)
# ========================================================================

async def generate_income_statement(period_start: datetime, period_end: datetime) -> Any:
    """
    Generate Income Statement (Profit & Loss) for a period.
    """
    
    income_statement = {
        "period_start": period_start,
        "period_end": period_end,
        "revenues": {
            "interest_income": 0.0,
            "fee_income": 0.0,
            "penalty_income": 0.0,
            "other_income": 0.0,
            "total_revenues": 0.0
        },
        "expenses": {
            "interest_expense": 0.0,
            "salaries_expense": 0.0,
            "operating_expenses": 0.0,
            "loan_loss_expense": 0.0,
            "other_expenses": 0.0,
            "total_expenses": 0.0
        },
        "profit_before_tax": 0.0,
        "net_income": 0.0
    }
    
    async for session in get_db_session():
        # Get income accounts (4xxx)
        result = await session.execute(
            select(GLAccount).where(GLAccount.type == "income")
        )
        income_accounts = result.scalars().all()
        
        for account in income_accounts:
            result = await session.execute(
                select(func.sum(JournalLine.credit - JournalLine.debit)).where(
                    JournalLine.account_code == account.code,
                    JournalEntry.timestamp >= period_start,
                    JournalEntry.timestamp <= period_end
                )
            )
            income = result.scalar_one() or 0
            
            if "interest" in account.name.lower():
                income_statement["revenues"]["interest_income"] += float(income)
            elif "fee" in account.name.lower():
                income_statement["revenues"]["fee_income"] += float(income)
            elif "penalty" in account.name.lower():
                income_statement["revenues"]["penalty_income"] += float(income)
            else:
                income_statement["revenues"]["other_income"] += float(income)
        
        # Get expense accounts (5xxx)
        result = await session.execute(
            select(GLAccount).where(GLAccount.type == "expense")
        )
        expense_accounts = result.scalars().all()
        
        for account in expense_accounts:
            result = await session.execute(
                select(func.sum(JournalLine.debit - JournalLine.credit)).where(
                    JournalLine.account_code == account.code,
                    JournalEntry.timestamp >= period_start,
                    JournalEntry.timestamp <= period_end
                )
            )
            expense = result.scalar_one() or 0
            
            if "interest" in account.name.lower():
                income_statement["expenses"]["interest_expense"] += float(expense)
            elif "salary" in account.name.lower():
                income_statement["expenses"]["salaries_expense"] += float(expense)
            elif "loan" in account.name.lower() and "loss" in account.name.lower():
                income_statement["expenses"]["loan_loss_expense"] += float(expense)
            elif "depreciation" in account.name.lower():
                income_statement["expenses"]["other_expenses"] += float(expense)
            else:
                income_statement["expenses"]["operating_expenses"] += float(expense)
    
    # Calculate totals
    income_statement["revenues"]["total_revenues"] = (
        income_statement["revenues"]["interest_income"] +
        income_statement["revenues"]["fee_income"] +
        income_statement["revenues"]["penalty_income"] +
        income_statement["revenues"]["other_income"]
    )
    
    income_statement["expenses"]["total_expenses"] = (
        income_statement["expenses"]["interest_expense"] +
        income_statement["expenses"]["salaries_expense"] +
        income_statement["expenses"]["operating_expenses"] +
        income_statement["expenses"]["loan_loss_expense"] +
        income_statement["expenses"]["other_expenses"]
    )
    
    income_statement["profit_before_tax"] = round(
        income_statement["revenues"]["total_revenues"] -
        income_statement["expenses"]["total_expenses"], 2
    )
    
    # Assuming 20% tax rate
    tax = income_statement["profit_before_tax"] * 0.20
    income_statement["net_income"] = round(
        income_statement["profit_before_tax"] - tax, 2
    )
    
    return income_statement


# ========================================================================
# 11. Financial Statements - Balance Sheet
# ========================================================================

async def generate_balance_sheet(as_of_date: datetime) -> Any:
    """
    Generate Balance Sheet as of a specific date.
    """
    
    balance_sheet = {
        "as_of_date": as_of_date,
        "assets": {
            "current_assets": {
                "cash": 0.0,
                "accounts_receivable": 0.0,
                "other_current": 0.0,
                "total_current_assets": 0.0
            },
            "non_current_assets": {
                "fixed_assets": 0.0,
                "accumulated_depreciation": 0.0,
                "loans_receivable": 0.0,
                "other_non_current": 0.0,
                "total_non_current_assets": 0.0,
                "total_assets": 0.0
            }
        },
        "liabilities": {
            "current_liabilities": {
                "accounts_payable": 0.0,
                "savings_deposits": 0.0,
                "other_current": 0.0,
                "total_current_liabilities": 0.0
            },
            "non_current_liabilities": {
                "long_term_debt": 0.0,
                "other_non_current": 0.0,
                "total_non_current_liabilities": 0.0,
                "total_liabilities": 0.0
            }
        },
        "equity": {
            "share_capital": 0.0,
            "retained_earnings": 0.0,
            "total_equity": 0.0,
            "total_liabilities_and_equity": 0.0
        }
    }
    
    async for session in get_db_session():
        # Assets - Current
        result = await session.execute(
            select(func.sum(JournalLine.debit - JournalLine.credit)).where(
                JournalLine.account_code.in_(["1000", "1010", "1100"]),
                JournalEntry.timestamp <= as_of_date
            )
        )
        balance_sheet["assets"]["current_assets"]["cash"] = float(result.scalar_one() or 0)
        
        # Loans Receivable
        result = await session.execute(
            select(func.sum(JournalLine.debit - JournalLine.credit)).where(
                JournalLine.account_code == "1300",
                JournalEntry.timestamp <= as_of_date
            )
        )
        balance_sheet["assets"]["non_current_assets"]["loans_receivable"] = float(result.scalar_one() or 0)
        
        # Allowance for Loan Losses (contra-asset)
        result = await session.execute(
            select(func.sum(JournalLine.credit - JournalLine.debit)).where(
                JournalLine.account_code == "1400",
                JournalEntry.timestamp <= as_of_date
            )
        )
        balance_sheet["assets"]["non_current_assets"]["allowance_for_loan_losses"] = float(result.scalar_one() or 0)
        
        # Fixed Assets
        result = await session.execute(
            select(func.sum(JournalLine.debit - JournalLine.credit)).where(
                JournalLine.account_code == "1500",
                JournalEntry.timestamp <= as_of_date
            )
        )
        balance_sheet["assets"]["non_current_assets"]["fixed_assets"] = float(result.scalar_one() or 0)
        
        # Accumulated Depreciation
        result = await session.execute(
            select(func.sum(JournalLine.credit - JournalLine.debit)).where(
                JournalLine.account_code == "1600",
                JournalEntry.timestamp <= as_of_date
            )
        )
        balance_sheet["assets"]["non_current_assets"]["accumulated_depreciation"] = float(result.scalar_one() or 0)
        
        # Liabilities
        result = await session.execute(
            select(func.sum(JournalLine.credit - JournalLine.debit)).where(
                JournalLine.account_code.in_(["2000", "2010", "2100"]),
                JournalEntry.timestamp <= as_of_date
            )
        )
        balance_sheet["liabilities"]["current_liabilities"]["accounts_payable"] = float(result.scalar_one() or 0)
        
        # Equity
        result = await session.execute(
            select(func.sum(JournalLine.credit - JournalLine.debit)).where(
                JournalLine.account_code.in_(["3000", "3100"]),
                JournalEntry.timestamp <= as_of_date
            )
        )
        balances = result.fetchall()
        balance_sheet["equity"]["share_capital"] = float(balances[0][0] or 0) if balances else 0
        balance_sheet["equity"]["retained_earnings"] = float(balances[1][0] or 0) if balances and len(balances) > 1 else 0
    
    # Calculate totals
    balance_sheet["assets"]["current_assets"]["total_current_assets"] = sum([
        balance_sheet["assets"]["current_assets"]["cash"]
    ])
    
    balance_sheet["assets"]["non_current_assets"]["total_non_current_assets"] = (
        balance_sheet["assets"]["non_current_assets"]["loans_receivable"] -
        balance_sheet["assets"]["non_current_assets"]["allowance_for_loan_losses"] +
        balance_sheet["assets"]["non_current_assets"]["fixed_assets"] -
        balance_sheet["assets"]["non_current_assets"]["accumulated_depreciation"]
    )
    
    balance_sheet["assets"]["non_current_assets"]["total_assets"] = (
        balance_sheet["assets"]["current_assets"]["total_current_assets"] +
        balance_sheet["assets"]["non_current_assets"]["total_non_current_assets"]
    )
    
    balance_sheet["liabilities"]["current_liabilities"]["total_current_liabilities"] = sum([
        balance_sheet["liabilities"]["current_liabilities"]["accounts_payable"]
    ])
    
    balance_sheet["liabilities"]["total_liabilities"] = (
        balance_sheet["liabilities"]["current_liabilities"]["total_current_liabilities"] +
        balance_sheet["liabilities"]["non_current_liabilities"]["total_non_current_liabilities"]
    )
    
    balance_sheet["equity"]["total_equity"] = (
        balance_sheet["equity"]["share_capital"] +
        balance_sheet["equity"]["retained_earnings"]
    )
    
    balance_sheet["equity"]["total_liabilities_and_equity"] = (
        balance_sheet["liabilities"]["total_liabilities"] +
        balance_sheet["equity"]["total_equity"]
    )
    
    return balance_sheet


# ========================================================================
# 12. Period Closing (Month-End, Quarter-End, Year-End)
# ========================================================================

async def execute_period_closing(closing_type: str, closing_date: datetime) -> Any:
    """
    Execute period closing process (month-end, quarter-end, year-end).
    
    Closing type: 'month', 'quarter', 'year'
    """
    
    closing_results = {
        "closing_type": closing_type,
        "closing_date": closing_date,
        "status": "completed",
        "entries_created": [],
        "summary": {}
    }
    
    async for session in get_db_session():
        # Close income and expense accounts to retained earnings
        # Debit all income accounts, Credit retained earnings
        result = await session.execute(select(GLAccount).where(GLAccount.type == "income"))
        income_accounts = result.scalars().all()
        
        total_income = 0.0
        for account in income_accounts:
            result = await session.execute(
                select(func.sum(JournalLine.credit - JournalLine.debit)).where(
                    JournalLine.account_code == account.code,
                    JournalEntry.timestamp < closing_date
                )
            )
            income = result.scalar_one() or 0
            total_income += float(income)
        
        # Credit all expense accounts, Debit retained earnings
        result = await session.execute(select(GLAccount).where(GLAccount.type == "expense"))
        expense_accounts = result.scalars().all()
        
        total_expense = 0.0
        for account in expense_accounts:
            result = await session.execute(
                select(func.sum(JournalLine.debit - JournalLine.credit)).where(
                    JournalLine.account_code == account.code,
                    JournalEntry.timestamp < closing_date
                )
            )
            expense = result.scalar_one() or 0
            total_expense += float(expense)
        
        net_income = total_income - total_expense
        
        # Create closing entries
        closing_entry = JournalEntry(
            reference_no=f"CLOS-{closing_date.strftime('%Y%m')}-{closing_type.upper()}",
            description=f"{closing_type.capitalize()}-end closing entry",
            created_by="system"
        )
        session.add(closing_entry)
        await session.flush()
        
        # Close income accounts
        if total_income > 0:
            income_close_line = JournalLine(
                entry_id=closing_entry.id,
                account_code="3100",  # Retained Earnings
                debit=total_income,
                credit=0.0,
                description=f"Close income accounts"
            )
            session.add(income_close_line)
            closing_results["entries_created"].append({
                "account": "3100 (Retained Earnings)",
                "debit": total_income,
                "credit": 0.0
            })
        
        # Close expense accounts
        if total_expense > 0:
            expense_close_line = JournalLine(
                entry_id=closing_entry.id,
                account_code="3100",  # Retained Earnings
                debit=0.0,
                credit=total_expense,
                description=f"Close expense accounts"
            )
            session.add(expense_close_line)
            closing_results["entries_created"].append({
                "account": "3100 (Retained Earnings)",
                "debit": 0.0,
                "credit": total_expense
            })
        
        # Update retained earnings
        closing_results["summary"] = {
            "total_income": round(total_income, 2),
            "total_expense": round(total_expense, 2),
            "net_income": round(net_income, 2)
        }
        
        await session.commit()
    
    return closing_results


# ========================================================================
# GraphQL Types and Resolvers
# ========================================================================

@strawberry.type
class AMLAlertType:
    id: int
    customer_id: str
    transaction_id: Optional[str]
    alert_type: str
    severity: str
    description: str
    reported_at: datetime
    reported_by: str
    status: str
    requires_filing: bool
    ctr_amount: Optional[float]


@strawberry.type
class AMLAlertsResponse:
    success: bool
    message: str
    alerts: List[AMLAlertType]
    total: int


@strawberry.type
class PARMetricsType:
    total_outstanding: float
    par1: str
    par7: str
    par30: str
    par90: str
    current: str


@strawberry.type
class NPLMetricsType:
    total_loans: int
    npl_count: int
    npl_amount: float
    npl_ratio: float
    npl_by_category: str


@strawberry.type
class LLRMetricsType:
    total_loans_outstanding: float
    llr_required: float
    llr_by_bucket: str
    llr_current_balance: float
    llr_needed: float
    llr_provision_required: float


@strawberry.type
class TrialBalanceType:
    period_start: datetime
    period_end: datetime
    accounts: str
    total_debits: float
    total_credits: float


@strawberry.type
class IncomeStatementType:
    period_start: datetime
    period_end: datetime
    revenues: str
    expenses: str
    profit_before_tax: float
    net_income: float


@strawberry.type
class BalanceSheetType:
    as_of_date: datetime
    assets: str
    liabilities: str
    equity: str


@strawberry.type
class PeriodClosingType:
    closing_type: str
    closing_date: datetime
    status: str
    entries_created: List[Dict[str, Any]]
    summary: str


# ========================================================================
# GraphQL Queries and Mutations
# ========================================================================

@strawberry.type
class AMLComplianceQuery:
    @strawberry.field
    async def get_aml_alerts(self, info: Info, skip: int = 0, limit: int = 50) -> AMLAlertsResponse:
        """Get all AML alerts."""
        current_user: UserInDB = info.context.get("current_user")
        if not current_user or current_user.role not in ["admin", "loan_officer"]:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Not authorized")
        
        async for session in get_db_session():
            result = await session.execute(select(AMLAlert).order_by(AMLAlert.reported_at.desc()))
            alerts = result.scalars().all()
            
            return AMLAlertsResponse(
                success=True,
                message="AML alerts retrieved",
                alerts=[AMLAlertType(
                    id=a.id,
                    customer_id=a.customer_id,
                    transaction_id=a.transaction_id,
                    alert_type=a.alert_type,
                    severity=a.severity,
                    description=a.description,
                    reported_at=a.reported_at,
                    reported_by=a.reported_by,
                    status=a.status,
                    requires_filing=a.requires_filing,
                    ctr_amount=a.ctr_amount
                ) for a in alerts],
                total=len(alerts)
            )
    
    @strawberry.field
    async def get_par_metrics(self, info: Info) -> PARMetricsType:
        """Get Portfolio At Risk metrics."""
        current_user: UserInDB = info.context.get("current_user")
        if not current_user or current_user.role not in ["admin", "staff"]:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Not authorized")
        
        par_metrics = await calculate_par_metrics()
        
        return PARMetricsType(
            total_outstanding=par_metrics["total_outstanding"],
            par1=par_metrics["par1"],
            par7=par_metrics["par7"],
            par30=par_metrics["par30"],
            par90=par_metrics["par90"],
            current=par_metrics["current"]
        )
    
    @strawberry.field
    async def get_npl_metrics(self, info: Info) -> NPLMetricsType:
        """Get Non-Performing Loans metrics."""
        current_user: UserInDB = info.context.get("current_user")
        if not current_user or current_user.role not in ["admin", "staff"]:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Not authorized")
        
        npl_metrics = await calculate_npl_metrics()
        
        return NPLMetricsType(
            total_loans=npl_metrics["total_loans"],
            npl_count=npl_metrics["npl_count"],
            npl_amount=npl_metrics["npl_amount"],
            npl_ratio=npl_metrics["npl_ratio"],
            npl_by_category=npl_metrics["npl_by_category"]
        )
    
    @strawberry.field
    async def get_llr_metrics(self, info: Info) -> LLRMetricsType:
        """Get Loan Loss Reserve metrics."""
        current_user: UserInDB = info.context.get("current_user")
        if not current_user or current_user.role not in ["admin", "staff"]:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Not authorized")
        
        llr_metrics = await calculate_llr()
        
        return LLRMetricsType(
            total_loans_outstanding=llr_metrics["total_loans_outstanding"],
            llr_required=llr_metrics["llr_required"],
            llr_by_bucket=llr_metrics["llr_by_bucket"],
            llr_current_balance=llr_metrics["llr_current_balance"],
            llr_needed=llr_metrics["llr_needed"],
            llr_provision_required=llr_metrics["llr_provision_required"]
        )
    
    @strawberry.field
    async def get_trial_balance(self, info: Info, period_start: datetime, period_end: datetime) -> TrialBalanceType:
        """Get Trial Balance for a period."""
        current_user: UserInDB = info.context.get("current_user")
        if not current_user or current_user.role not in ["admin", "staff"]:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Not authorized")
        
        trial_balance = await generate_trial_balance(period_start, period_end)
        
        return TrialBalanceType(
            period_start=trial_balance["period_start"],
            period_end=trial_balance["period_end"],
            accounts=trial_balance["accounts"],
            total_debits=trial_balance["total_debits"],
            total_credits=trial_balance["total_credits"]
        )
    
    @strawberry.field
    async def get_income_statement(self, info: Info, period_start: datetime, period_end: datetime) -> IncomeStatementType:
        """Get Income Statement for a period."""
        current_user: UserInDB = info.context.get("current_user")
        if not current_user or current_user.role not in ["admin", "staff"]:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Not authorized")
        
        income_statement = await generate_income_statement(period_start, period_end)
        
        return IncomeStatementType(
            period_start=income_statement["period_start"],
            period_end=income_statement["period_end"],
            revenues=income_statement["revenues"],
            expenses=income_statement["expenses"],
            profit_before_tax=income_statement["profit_before_tax"],
            net_income=income_statement["net_income"]
        )
    
    @strawberry.field
    async def get_balance_sheet(self, info: Info, as_of_date: datetime) -> BalanceSheetType:
        """Get Balance Sheet as of a date."""
        current_user: UserInDB = info.context.get("current_user")
        if not current_user or current_user.role not in ["admin", "staff"]:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Not authorized")
        
        balance_sheet = await generate_balance_sheet(as_of_date)
        
        return BalanceSheetType(
            as_of_date=balance_sheet["as_of_date"],
            assets=balance_sheet["assets"],
            liabilities=balance_sheet["liabilities"],
            equity=balance_sheet["equity"]
        )


@strawberry.type
class AMLComplianceMutation:
    @strawberry.mutation
    async def check_customer_ofac(self, info: Info, customer_data: dict) -> Any:
        """Check customer against OFAC and watchlists."""
        current_user: UserInDB = info.context.get("current_user")
        if not current_user or current_user.role not in ["admin", "staff", "loan_officer"]:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Not authorized")
        
        result = await check_ofac_compliance(customer_data)
        
        return {
            "success": True,
            "message": "OFAC check completed",
            "compliance_status": result["compliance_status"],
            "risk_score": result["risk_score"],
            "flags": result["flags"]
        }
    
    @strawberry.mutation
    async def check_customer_pep(self, info: Info, customer_id: str, customer_data: dict) -> Any:
        """Check if customer is a PEP."""
        current_user: UserInDB = info.context.get("current_user")
        if not current_user or current_user.role not in ["admin", "staff", "loan_officer"]:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Not authorized")
        
        result = await check_pep_status(customer_id, customer_data)
        
        return {
            "success": True,
            "message": "PEP check completed",
            "is_pep": result["is_pep"],
            "pep_type": result["pep_type"],
            "enhanced_dda_required": result["enhanced_dda_required"]
        }
    
    @strawberry.mutation
    async def flag_suspicious_transaction(self, info: Info, transaction_data: dict) -> Any:
        """Flag suspicious transactions and create SAR."""
        current_user: UserInDB = info.context.get("current_user")
        if not current_user or current_user.role not in ["admin", "staff", "teller"]:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Not authorized")
        
        alert = await flag_suspicious_activity(transaction_data, transaction_data.get('customer_id'))
        
        if alert:
            async for session in get_db_session():
                session.add(alert)
                await session.commit()
            
            return {
                "success": True,
                "message": "Suspicious activity flagged",
                "alert_id": alert.id,
                "alert_type": alert.alert_type,
                "requires_review": True
            }
        
        return {
            "success": True,
            "message": "No suspicious activity detected",
            "alert_id": None
        }
    
    @strawberry.mutation
    async def check_ctr(self, info: Info, transaction_data: dict) -> Any:
        """Check if transaction meets CTR threshold."""
        current_user: UserInDB = info.context.get("current_user")
        if not current_user or current_user.role not in ["admin", "staff", "teller"]:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Not authorized")
        
        alert = await check_ctr_requirements(transaction_data, transaction_data.get('customer_id'))
        
        if alert:
            async for session in get_db_session():
                session.add(alert)
                await session.commit()
            
            return {
                "success": True,
                "message": "CTR threshold exceeded - CTR filing required",
                "alert_id": alert.id,
                "ctr_amount": alert.ctr_amount,
                "requires_filing": True
            }
        
        return {
            "success": True,
            "message": "Transaction below CTR threshold",
            "alert_id": None,
            "requires_filing": False
        }
    
    @strawberry.mutation
    async def execute_period_closing(self, info: Info, closing_type: str, closing_date: datetime) -> PeriodClosingType:
        """Execute period closing (month-end, quarter-end, year-end)."""
        current_user: UserInDB = info.context.get("current_user")
        if not current_user or current_user.role != "admin":
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Only admin can execute period closing")
        
        closing_results = await execute_period_closing(closing_type, closing_date)
        
        return PeriodClosingType(
            closing_type=closing_results["closing_type"],
            closing_date=closing_results["closing_date"],
            status=closing_results["status"],
            entries_created=closing_results["entries_created"],
            summary=closing_results["summary"]
        )
    
    @strawberry.mutation
    async def run_compliance_reports(self, info: Info, report_type: str) -> Any:
        """Run scheduled compliance reports (daily/weekly/monthly)."""
        current_user: UserInDB = info.context.get("current_user")
        if not current_user or current_user.role not in ["admin", "staff"]:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Not authorized")
        
        if report_type == "daily":
            reports = await run_daily_compliance_reports()
        elif report_type == "weekly":
            reports = await run_weekly_compliance_reports()
        elif report_type == "monthly":
            reports = await run_monthly_compliance_reports()
        else:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid report type")
        
        return reports
    
    @strawberry.mutation
    async def resolve_alert(self, info: Info, alert_id: int, status: str, resolution_notes: str) -> Any:
        """Resolve an AML alert."""
        current_user: UserInDB = info.context.get("current_user")
        if not current_user or current_user.role not in ["admin", "staff"]:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Not authorized")
        
        result = await resolve_aml_alert(alert_id, status, resolution_notes, str(current_user.id))
        
        return result
    
    @strawberry.mutation
    async def escalate_alert(self, info: Info, alert_id: int, escalated_to: str, reason: str) -> Any:
        """Escalate an AML alert to next level."""
        current_user: UserInDB = info.context.get("current_user")
        if not current_user or current_user.role not in ["admin", "staff"]:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Not authorized")
        
        result = await escalate_aml_alert(alert_id, escalated_to, reason)
        
        return result
    
    @strawberry.field
    async def get_unresolved_alerts(self, info: Info, severity: Optional[str] = None) -> AMLAlertsResponse:
        """Get all unresolved AML alerts."""
        current_user: UserInDB = info.context.get("current_user")
        if not current_user or current_user.role not in ["admin", "staff"]:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Not authorized")
        
        alerts = await get_unresolved_alerts(severity)
        
        return AMLAlertsResponse(
            success=True,
            message="Unresolved alerts retrieved",
            alerts=[AMLAlertType(
                id=a["id"],
                customer_id=a["customer_id"],
                transaction_id=None,
                alert_type=a["alert_type"],
                severity=a["severity"],
                description=a["description"],
                reported_at=a["reported_at"],
                reported_by="system",
                status=a["status"],
                requires_filing=False,
                ctr_amount=None
            ) for a in alerts],
            total=len(alerts)
        )


# ============================================================================
# Export GraphQL Types for New Features
# ============================================================================

@strawberry.type
class ComplianceReportType:
    generated_at: datetime
    period: Optional[str]
    reports: str
    status: str
    error: Optional[str] = None


@strawberry.type
class ExportResponse:
    success: bool
    message: str
    file_url: str
    file_format: str


@strawberry.type
class AlertResolutionType:
    success: bool
    alert_id: int
    new_status: str
    resolved_at: datetime
    message: str


@strawberry.type
class SARReportType:
    report_id: str
    alert_id: int
    customer_id: str
    transaction_ids: List[str]
    suspicious_activity_description: str
    filing_date: datetime
    filed_by: str
    status: str
    required_fields: List[str]
    filing_deadline: datetime
    tracking_id: Optional[str]


@strawberry.type
class NotificationResponseType:
    status: str
    alert_id: int
    recipients: List[str]
    sent_at: datetime
    error: Optional[str] = None


@strawberry.type
class PEPCheckType:
    is_pep: bool
    source: str
    pep_type: Optional[str]
    enhanced_dda_required: bool
    message: str
    details: Optional[Dict[str, Any]] = None


@strawberry.type
class OFACCheckType:
    is_sanctioned: bool
    source: str
    sanctions_list: List[Dict[str, Any]]
    message: str
    details: Optional[Dict[str, Any]] = None


@strawberry.type
class ExportReportType:
    period_start: datetime
    period_end: datetime
    file_url: str
    file_format: str
    file_name: str


# ============================================================================
# New GraphQL Queries (already defined at line 1113)
# ============================================================================