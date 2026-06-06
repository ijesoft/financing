import strawberry
from typing import List, Optional
from decimal import Decimal
from datetime import datetime
from strawberry.types import Info
from fastapi import HTTPException, status
from sqlalchemy.future import select

from .models import UserInDB
from .database.postgres import get_db_session
from .database.pg_loan_models import LoanApplication, PGLoanProduct
from .customer import CustomerType, convert_customer_db_to_customer_type
from .auth.rbac import get_sql_branch_filter, require_approval_role
import math
import uuid
import os
from dateutil.relativedelta import relativedelta
from sqlalchemy import func as sa_func
from .database.pg_loan_models import AmortizationSchedule, LoanTransaction
from .database.pg_loan_models import (
    CreditScore,
    LoanApplicationDocument,
    DisbursementChecklist,
    LoanTranche,
    PromiseToPay,
)
from .database.pg_accounting_models import GLAccount
from .accounting import create_journal_entry
from datetime import date
from .config import settings
import aiofiles
from .utils.receipt_generator import generate_receipt_pdf


@strawberry.type
class ScheduleRowPreview:
    installment_number: int = strawberry.field(name="installmentNumber")
    due_date: datetime = strawberry.field(name="dueDate")
    principal_due: Decimal = strawberry.field(name="principalDue")
    interest_due: Decimal = strawberry.field(name="interestDue")
    total_due: Decimal = strawberry.field(name="totalDue")
    balance: Decimal


@strawberry.type
class LoanType:
    id: strawberry.ID
    customer_id: str = strawberry.field(name="customerId")
    product_id: int = strawberry.field(name="productId")
    principal: Decimal
    term_months: int = strawberry.field(name="termMonths")
    approved_principal: Optional[Decimal] = strawberry.field(
        name="approvedPrincipal", default=None
    )
    approved_rate: Optional[Decimal] = strawberry.field(
        name="approvedRate", default=None
    )
    status: str
    created_at: datetime = strawberry.field(name="createdAt")
    updated_at: datetime = strawberry.field(name="updatedAt")
    disbursed_at: Optional[datetime] = strawberry.field(
        name="disbursedAt", default=None
    )
    outstanding_balance: Optional[Decimal] = strawberry.field(
        name="outstandingBalance", default=None
    )
    next_due_date: Optional[datetime] = strawberry.field(
        name="nextDueDate", default=None
    )
    months_paid: Optional[int] = strawberry.field(name="monthsPaid", default=None)
    branch_code: Optional[str] = strawberry.field(name="branchCode", default=None)

    @strawberry.field
    async def product_name(self) -> Optional[str]:
        async for session in get_db_session():
            result = await session.execute(
                select(PGLoanProduct).filter(PGLoanProduct.id == self.product_id)
            )
            prod = result.scalar_one_or_none()
            return prod.name if prod else "Unknown Product"

    @strawberry.field(name="borrowerName")
    async def borrower_name(self) -> Optional[str]:
        try:
            from .database import get_async_session_local
            from .database.pg_core_models import Customer
            session_factory = get_async_session_local()
            async with session_factory() as session:
                if str(self.customer_id).isdigit():
                    stmt = select(Customer).where(Customer.id == int(str(self.customer_id)))
                    result = await session.execute(stmt)
                    customer = result.scalar_one_or_none()
                    return customer.display_name if customer else f"Customer {self.customer_id}"
                return f"Customer {self.customer_id}"
        except Exception:
            return "N/A"


@strawberry.input
class LoanCreateInput:
    customer_id: str
    product_id: int
    principal: Decimal
    term_months: int
    disbursement_method: Optional[str] = (
        None  # cash | bank_transfer | cheque | savings_transfer
    )


@strawberry.input
class LoanUpdateInput:
    status: Optional[str] = None
    approved_principal: Optional[Decimal] = None
    approved_rate: Optional[Decimal] = None


@strawberry.type
class LoanResponse:
    success: bool
    message: str
    loan: Optional[LoanType] = None


@strawberry.type
class LoansResponse:
    success: bool
    message: str
    loans: List[LoanType]
    total: int


@strawberry.type
class LoanQuery:
    @strawberry.field
    async def loan(self, info: Info, id: strawberry.ID) -> LoanResponse:
        current_user: UserInDB = info.context.get("current_user")
        if not current_user:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED, detail="Not authenticated"
            )

        async for session in get_db_session():
            result = await session.execute(
                select(LoanApplication).filter(LoanApplication.id == int(id))
            )
            loan_db = result.scalar_one_or_none()
            if not loan_db:
                return LoanResponse(success=False, message="Loan not found")

            if current_user.role == "customer" and str(loan_db.customer_id) != str(
                current_user.id
            ):
                raise HTTPException(
                    status_code=status.HTTP_403_FORBIDDEN, detail="Not authorized"
                )

            return LoanResponse(
                success=True,
                message="OK",
                loan=LoanType(
                    id=strawberry.ID(str(loan_db.id)),
                    customer_id=loan_db.customer_id,
                    product_id=loan_db.product_id,
                    principal=loan_db.principal,
                    term_months=loan_db.term_months,
                    approved_principal=loan_db.approved_principal,
                    approved_rate=loan_db.approved_rate,
                    status=loan_db.status,
                    created_at=loan_db.created_at,
                    updated_at=loan_db.updated_at,
                    disbursed_at=loan_db.disbursed_at,
                ),
            )

    @strawberry.field
    async def loans(
        self,
        info: Info,
        skip: int = 0,
        limit: int = 100,
        customer_id: Optional[str] = None,
    ) -> LoansResponse:
        current_user: UserInDB = info.context.get("current_user")
        if not current_user:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED, detail="Not authenticated"
            )

        async for session in get_db_session():
            query = (
                select(LoanApplication)
                .order_by(LoanApplication.id.desc())
                .offset(skip)
                .limit(limit)
            )
            count_query = select(LoanApplication)

            if current_user.role == "customer":
                customer_id = str(current_user.id)

            if customer_id:
                query = query.filter(LoanApplication.customer_id == customer_id)
                count_query = count_query.filter(
                    LoanApplication.customer_id == customer_id
                )

            # Apply branch filter for non-admin/non-auditor staff
            branch_code_filter = get_sql_branch_filter(current_user)
            if branch_code_filter:
                query = query.filter(LoanApplication.branch_code == branch_code_filter)
                count_query = count_query.filter(LoanApplication.branch_code == branch_code_filter)

            result = await session.execute(query)
            loans_db = result.scalars().all()
            total_result = await session.execute(count_query)
            total = len(total_result.scalars().all())  # Inefficient but ok for now

            loans_type = [
                LoanType(
                    id=strawberry.ID(str(l.id)),
                    customer_id=l.customer_id,
                    product_id=l.product_id,
                    principal=l.principal,
                    term_months=l.term_months,
                    approved_principal=l.approved_principal,
                    approved_rate=l.approved_rate,
                    status=l.status,
                    created_at=l.created_at,
                    updated_at=l.updated_at,
                    disbursed_at=l.disbursed_at,
                    outstanding_balance=l.outstanding_balance,
                    next_due_date=l.next_due_date,
                    months_paid=l.months_paid,
                    branch_code=l.branch_code,
                )
                for l in loans_db
            ]

            return LoansResponse(
                success=True, message="OK", loans=loans_type, total=total
            )

    @strawberry.field
    async def customerLoans(self, info: Info) -> LoansResponse:
        """Get loans for the current authenticated customer."""
        current_user: UserInDB = info.context.get("current_user")
        if not current_user:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED, detail="Not authenticated"
            )

        if current_user.role != "customer":
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN, detail="Not authorized"
            )

        async for session in get_db_session():
            query = (
                select(LoanApplication)
                .filter(LoanApplication.customer_id == str(current_user.id))
                .order_by(LoanApplication.id.desc())
            )

            result = await session.execute(query)
            loans_db = result.scalars().all()

            loans_type = [
                LoanType(
                    id=strawberry.ID(str(l.id)),
                    customer_id=l.customer_id,
                    product_id=l.product_id,
                    principal=l.principal,
                    term_months=l.term_months,
                    approved_principal=l.approved_principal,
                    approved_rate=l.approved_rate,
                    status=l.status,
                    created_at=l.created_at,
                    updated_at=l.updated_at,
                    disbursed_at=l.disbursed_at,
                )
                for l in loans_db
            ]

            return LoansResponse(
                success=True, message="OK", loans=loans_type, total=len(loans_db)
            )

    @strawberry.field
    async def generate_loan_schedule_preview(
        self,
        info: Info,
        principal: Decimal,
        rate_annual: Decimal,
        term_months: int,
        amortization_type: str,
    ) -> List[ScheduleRowPreview]:
        current_user: UserInDB = info.context.get("current_user")
        if not current_user:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED, detail="Not authenticated"
            )

        return _build_schedule_preview(
            principal, rate_annual, term_months, amortization_type, datetime.now()
        )


def _build_schedule_preview(
    principal: Decimal,
    rate_annual: Decimal,
    term_months: int,
    amortization_type: str,
    start_date: datetime,
) -> List[ScheduleRowPreview]:
    """Pure helper to compute amortization preview rows for all 4 types."""
    schedule: List[ScheduleRowPreview] = []
    balance = principal
    rate_monthly = (rate_annual / Decimal(100)) / Decimal(12)

    if amortization_type == "flat_rate":
        interest_per_month = principal * rate_monthly
        principal_per_month = principal / Decimal(term_months)
        for i in range(1, term_months + 1):
            balance -= principal_per_month
            schedule.append(
                ScheduleRowPreview(
                    installment_number=i,
                    due_date=start_date + relativedelta(months=i),
                    principal_due=round(principal_per_month, 2),
                    interest_due=round(interest_per_month, 2),
                    total_due=round(principal_per_month + interest_per_month, 2),
                    balance=max(Decimal(0), round(balance, 2)),
                )
            )

    elif amortization_type == "declining_balance":
        if rate_monthly > 0:
            pmt = (principal * rate_monthly) / (
                Decimal(1) - (Decimal(1) + rate_monthly) ** Decimal(-term_months)
            )
        else:
            pmt = principal / Decimal(term_months)
        for i in range(1, term_months + 1):
            interest_for_month = balance * rate_monthly
            principal_for_month = pmt - interest_for_month
            balance -= principal_for_month
            schedule.append(
                ScheduleRowPreview(
                    installment_number=i,
                    due_date=start_date + relativedelta(months=i),
                    principal_due=round(principal_for_month, 2),
                    interest_due=round(interest_for_month, 2),
                    total_due=round(pmt, 2),
                    balance=max(Decimal(0), round(balance, 2)),
                )
            )

    elif amortization_type == "balloon_payment":
        # Interest-only payments for term-1 months, then full principal + interest on final month
        interest_per_month = balance * rate_monthly
        for i in range(1, term_months):
            schedule.append(
                ScheduleRowPreview(
                    installment_number=i,
                    due_date=start_date + relativedelta(months=i),
                    principal_due=Decimal(0),
                    interest_due=round(interest_per_month, 2),
                    total_due=round(interest_per_month, 2),
                    balance=round(balance, 2),
                )
            )
        # Final balloon payment
        schedule.append(
            ScheduleRowPreview(
                installment_number=term_months,
                due_date=start_date + relativedelta(months=term_months),
                principal_due=round(principal, 2),
                interest_due=round(interest_per_month, 2),
                total_due=round(principal + interest_per_month, 2),
                balance=Decimal(0),
            )
        )

    elif amortization_type == "interest_only":
        # Interest-only every month, full principal due on last month
        interest_per_month = balance * rate_monthly
        for i in range(1, term_months):
            schedule.append(
                ScheduleRowPreview(
                    installment_number=i,
                    due_date=start_date + relativedelta(months=i),
                    principal_due=Decimal(0),
                    interest_due=round(interest_per_month, 2),
                    total_due=round(interest_per_month, 2),
                    balance=round(balance, 2),
                )
            )
        # Final month: principal + interest
        schedule.append(
            ScheduleRowPreview(
                installment_number=term_months,
                due_date=start_date + relativedelta(months=term_months),
                principal_due=round(principal, 2),
                interest_due=round(interest_per_month, 2),
                total_due=round(principal + interest_per_month, 2),
                balance=Decimal(0),
            )
        )

    return schedule


@strawberry.type
class LoanMutation:
    @strawberry.mutation
    async def create_loan(self, info: Info, input: LoanCreateInput) -> LoanResponse:
        current_user: UserInDB = info.context.get("current_user")
        if not current_user:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED, detail="Not authenticated"
            )

        if current_user.role == "customer" and input.customer_id != str(
            current_user.id
        ):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Cannot apply for someone else",
            )

        async for session in get_db_session():
            # --- Enforce customer_loan_limit ---
            prod_result = await session.execute(
                select(PGLoanProduct).filter(PGLoanProduct.id == input.product_id)
            )
            product = prod_result.scalar_one_or_none()
            if not product:
                return LoanResponse(success=False, message="Loan product not found")

            if product.customer_loan_limit and product.customer_loan_limit > 0:
                # Sum principal of all non-rejected/non-paid loans for this customer under this product
                existing_result = await session.execute(
                    select(sa_func.coalesce(sa_func.sum(LoanApplication.principal), 0))
                    .filter(LoanApplication.customer_id == input.customer_id)
                    .filter(LoanApplication.product_id == input.product_id)
                    .filter(
                        LoanApplication.status.notin_(
                            ["rejected", "paid", "written_off"]
                        )
                    )
                )
                existing_total = existing_result.scalar() or Decimal(0)
                if existing_total + input.principal > product.customer_loan_limit:
                    return LoanResponse(
                        success=False,
                        message=f"Exceeds customer loan limit of {product.customer_loan_limit}. Current outstanding: {existing_total}",
                    )

            new_loan = LoanApplication(
                customer_id=input.customer_id,
                product_id=input.product_id,
                principal=input.principal,
                term_months=input.term_months,
                disbursement_method=input.disbursement_method,
                status="draft",
            )
            session.add(new_loan)
            await session.flush()
            await session.commit()
            await session.refresh(new_loan)

            return LoanResponse(
                success=True,
                message="Loan created successfully",
                loan=LoanType(
                    id=strawberry.ID(str(new_loan.id)),
                    customer_id=new_loan.customer_id,
                    product_id=new_loan.product_id,
                    principal=new_loan.principal,
                    term_months=new_loan.term_months,
                    approved_principal=new_loan.approved_principal,
                    approved_rate=new_loan.approved_rate,
                    status=new_loan.status,
                    created_at=new_loan.created_at,
                    updated_at=new_loan.updated_at,
                    disbursed_at=new_loan.disbursed_at,
                ),
            )

    @strawberry.mutation
    async def createCustomerLoan(
        self, info: Info, input: LoanCreateInput
    ) -> LoanResponse:
        """Create a loan application for the current authenticated customer."""
        current_user: UserInDB = info.context.get("current_user")
        if not current_user:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED, detail="Not authenticated"
            )

        if current_user.role != "customer":
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN, detail="Not authorized"
            )

        # Override customer_id to use current user's ID
        input.customer_id = str(current_user.id)

        # Re-use the existing create_loan logic
        return await self.create_loan(info, input)

    @strawberry.mutation
    async def update_loan(
        self, info: Info, id: strawberry.ID, input: LoanUpdateInput
    ) -> LoanResponse:
        current_user: UserInDB = info.context.get("current_user")
        if not current_user or current_user.role in ["customer"]:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Not authorized to approve loans",
            )

        async for session in get_db_session():
            result = await session.execute(
                select(LoanApplication).filter(LoanApplication.id == int(id))
            )
            loan = result.scalar_one_or_none()
            if not loan:
                return LoanResponse(success=False, message="Loan not found")

            if input.status:
                loan.status = input.status
            if input.approved_principal:
                loan.approved_principal = input.approved_principal
            if input.approved_rate:
                loan.approved_rate = input.approved_rate

            await session.flush()
            await session.refresh(loan)

            return LoanResponse(
                success=True,
                message="Loan updated",
                loan=LoanType(
                    id=strawberry.ID(str(loan.id)),
                    customer_id=loan.customer_id,
                    product_id=loan.product_id,
                    principal=loan.principal,
                    term_months=loan.term_months,
                    approved_principal=loan.approved_principal,
                    approved_rate=loan.approved_rate,
                    status=loan.status,
                    created_at=loan.created_at,
                    updated_at=loan.updated_at,
                    disbursed_at=loan.disbursed_at,
                ),
            )

    @strawberry.mutation
    async def delete_loan(self, info: Info, id: strawberry.ID) -> LoanResponse:
        current_user: UserInDB = info.context.get("current_user")
        if not current_user or current_user.role not in ["admin", "staff"]:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN, detail="Not authorized"
            )

        async for session in get_db_session():
            result = await session.execute(
                select(LoanApplication).filter(LoanApplication.id == int(id))
            )
            loan = result.scalar_one_or_none()
            if not loan:
                return LoanResponse(success=False, message="Loan not found")

            if loan.status not in ["draft", "submitted"]:
                return LoanResponse(
                    success=False, message="Can only delete draft or submitted loans"
                )

            await session.delete(loan)
            await session.commit()
            return LoanResponse(success=True, message="Loan deleted successfully")

    @strawberry.mutation
    async def disburse_loan(self, info: Info, id: strawberry.ID) -> LoanResponse:
        """Approves and disburses the loan, generating Amortization and GL entries.
        Applies origination fee if configured on the product.
        Supports all 4 amortization types: flat_rate, declining_balance, balloon_payment, interest_only.

        Only admin and branch_manager may disburse (approve) loans.
        """
        current_user: UserInDB = info.context.get("current_user")
        if not current_user or current_user.role not in ("admin", "branch_manager"):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Not authorized — only admin or branch_manager may disburse loans",
            )

        async for session in get_db_session():
            result = await session.execute(
                select(LoanApplication).filter(LoanApplication.id == int(id))
            )
            loan = result.scalar_one_or_none()
            if not loan or loan.status == "active":
                return LoanResponse(
                    success=False, message="Loan not found or already disbursed"
                )

            loan.status = "active"
            loan.disbursed_at = datetime.now()

            # Fetch product
            product_result = await session.execute(
                select(PGLoanProduct).filter(PGLoanProduct.id == loan.product_id)
            )
            prod = product_result.scalar_one()

            loan_qty = loan.approved_principal or loan.principal
            rate_annual = loan.approved_rate or prod.interest_rate
            rate_monthly = rate_annual / Decimal(100) / Decimal(12)

            # --- Origination fee ---
            origination_fee = Decimal(0)
            if prod.origination_fee_rate and prod.origination_fee_rate > 0:
                origination_fee = round(
                    loan_qty * prod.origination_fee_rate / Decimal(100), 2
                )

            net_disbursement = loan_qty  # Amount actually released to borrower
            if origination_fee > 0 and prod.origination_fee_type == "upfront":
                net_disbursement = loan_qty - origination_fee

            # 1. Generate Amortization Schedule using the helper
            preview_rows = _build_schedule_preview(
                loan_qty,
                rate_annual,
                loan.term_months,
                prod.amortization_type,
                loan.disbursed_at,
            )
            for row in preview_rows:
                sched = AmortizationSchedule(
                    loan_id=loan.id,
                    installment_number=row.installment_number,
                    due_date=row.due_date,
                    principal_due=row.principal_due,
                    interest_due=row.interest_due,
                )
                session.add(sched)

            # 2. Add LoanTransaction record for disbursement
            txn = LoanTransaction(
                loan_id=loan.id,
                type="disbursement",
                amount=net_disbursement,
                receipt_number=f"DSB-{uuid.uuid4().hex[:6].upper()}",
                description=f"Net disbursement (origination fee: {origination_fee})"
                if origination_fee > 0
                else "Loan disbursement",
                processed_by=str(current_user.id),
            )
            session.add(txn)

            # 3. GL entries - Reverse Disbursement Payable from approval and record cash outflow
            # The Loans Receivable (1300) was already recognized on approval
            gl_lines = [
                {
                    "account_code": "2010",
                    "debit": loan_qty,
                    "credit": Decimal(0),
                    "description": "Reverse Disbursement Payable - Loan Approved",
                },
                {
                    "account_code": "1010",
                    "debit": Decimal(0),
                    "credit": net_disbursement,
                    "description": "Cash Disbursed to Customer",
                },
            ]
            if origination_fee > 0:
                gl_lines.append(
                    {
                        "account_code": "4200",
                        "debit": Decimal(0),
                        "credit": origination_fee,
                        "description": "Origination Fee Income",
                    }
                )
                # Record fee transaction
                fee_txn = LoanTransaction(
                    loan_id=loan.id,
                    type="fee",
                    amount=origination_fee,
                    receipt_number=f"FEE-{uuid.uuid4().hex[:6].upper()}",
                    description="Origination fee (upfront deduction)",
                    processed_by=str(current_user.id),
                )
                session.add(fee_txn)

            await create_journal_entry(
                session=session,
                reference_no=f"JNL-{txn.receipt_number}",
                description=f"Loan Disbursement for Loan {loan.id}",
                created_by=str(current_user.id),
                lines=gl_lines,
            )
            try:
                from .services.loan_accounting_service import post_loan_disbursement
                from .services.accounting_service import post_transaction as _post_tx
                principal_minor = int((loan_qty * Decimal(100)).to_integral_value())
                net_minor = int((net_disbursement * Decimal(100)).to_integral_value())
                fee_minor = int((origination_fee * Decimal(100)).to_integral_value())
                from .database import get_async_session_local
                bank_session_factory = get_async_session_local()
                async with bank_session_factory() as bank_session:
                    await post_loan_disbursement(
                        bank_session,
                        loan_id=loan.id,
                        principal_minor=principal_minor,
                        net_disbursement_minor=net_minor,
                        origination_fee_minor=fee_minor,
                        customer_id=str(loan.customer_id) if loan.customer_id is not None else None,
                        branch_code=loan.branch_code,
                        idempotency_key=f"DISB-{txn.receipt_number}",
                        created_by=str(current_user.id),
                        description=f"Bank-grade disbursement posting for loan {loan.id}",
                    )
            except Exception as bg_err:
                print(f"Warning: bank-grade disbursement posting failed: {bg_err}")

            await session.commit()

            # Get customer name for receipt
            from .database.pg_core_models import Customer
            if str(loan.customer_id).isdigit():
                customer_stmt = select(Customer).where(Customer.id == int(str(loan.customer_id)))
            else:
                customer_stmt = select(Customer).where(Customer.id == int(str(loan.customer_id)) if str(loan.customer_id).isdigit() else False)
            
            customer_res = await session.execute(customer_stmt)
            customer = customer_res.scalar_one_or_none()
            customer_name = customer.display_name if customer else "Customer"

            # Generate Official Receipt PDF
            receipt_data = {
                "receipt_number": txn.receipt_number,
                "date": datetime.now().strftime("%Y-%m-%d"),
                "customer_name": customer_name,
                "customer_id": loan.customer_id,
                "customer_address": "N/A",  # Would need customer details
                "loan_number": f"LOAN-{loan.id:06d}",
                "amount": net_disbursement,
                "description": f"Net disbursement (origination fee: {origination_fee})"
                if origination_fee > 0
                else "Loan disbursement",
                "payment_method": loan.disbursement_method or "Bank Transfer",
                "transaction_type": "Loan Disbursement",
                "breakdown": {
                    "principal": net_disbursement,
                    "total": net_disbursement,
                },
                "journal_entries": [
                    {
                        "account_code": "1300",
                        "account_name": "Loans Receivable",
                        "debit": loan_qty,
                        "credit": Decimal("0"),
                    },
                    {
                        "account_code": "1010",
                        "account_name": "Cash in Bank",
                        "debit": Decimal("0"),
                        "credit": net_disbursement,
                    },
                ],
                "processed_by": current_user.username if current_user else "system",
                "processed_date": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            }

            if origination_fee > 0:
                receipt_data["journal_entries"].append(
                    {
                        "account_code": "4200",
                        "account_name": "Origination Fee Income",
                        "debit": Decimal("0"),
                        "credit": origination_fee,
                    }
                )

            try:
                receipt_pdf = generate_receipt_pdf(receipt_data)
                receipt_path = f"/tmp/receipt_{txn.receipt_number}.pdf"
                with open(receipt_path, "wb") as f:
                    f.write(receipt_pdf)
            except Exception as e:
                print(f"Warning: Failed to generate receipt PDF: {e}")
                receipt_path = None

            msg = f"Loan disbursed — net release: {net_disbursement}"
            if origination_fee > 0:
                msg += f" (origination fee: {origination_fee} deducted upfront)"
            msg += f" | Receipt: {txn.receipt_number}"
            return LoanResponse(success=True, message=msg)

    @strawberry.mutation
    async def repay_loan(
        self,
        info: Info,
        id: strawberry.ID,
        amount: Decimal,
        paymentDate: Optional[str] = None,
    ) -> LoanResponse:
        """Process loan repayment with waterfall logic (Penalty -> Interest -> Principal).
        Enforces prepayment rules from the linked product.
        Handles overpayment by crediting remaining funds to next period.
        """
        # Parse payment date if provided
        from datetime import datetime

        transaction_date = datetime.now()
        if paymentDate:
            try:
                transaction_date = datetime.strptime(paymentDate, "%Y-%m-%d")
            except ValueError:
                pass  # Use current date if invalid
        current_user: UserInDB = info.context.get("current_user")
        if not current_user:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED, detail="Not authenticated"
            )

        async for session in get_db_session():
            result = await session.execute(
                select(LoanApplication).filter(LoanApplication.id == int(id))
            )
            loan = result.scalar_one_or_none()
            if not loan or loan.status != "active":
                return LoanResponse(
                    success=False, message="Loan not found or not active"
                )

            # --- Enforce prepayment rules ---
            product_result = await session.execute(
                select(PGLoanProduct).filter(PGLoanProduct.id == loan.product_id)
            )
            prod = product_result.scalar_one()

            # Find total remaining balance across all unpaid schedules
            remaining_q = await session.execute(
                select(
                    sa_func.coalesce(
                        sa_func.sum(
                            AmortizationSchedule.principal_due
                            - AmortizationSchedule.principal_paid
                        ),
                        0,
                    ),
                    sa_func.coalesce(
                        sa_func.sum(
                            AmortizationSchedule.interest_due
                            - AmortizationSchedule.interest_paid
                        ),
                        0,
                    ),
                    sa_func.coalesce(
                        sa_func.sum(
                            AmortizationSchedule.penalty_due
                            - AmortizationSchedule.penalty_paid
                        ),
                        0,
                    ),
                )
                .filter(AmortizationSchedule.loan_id == loan.id)
                .filter(
                    AmortizationSchedule.status.in_(["pending", "partial", "overdue"])
                )
            )
            remaining_row = remaining_q.one()
            total_remaining = remaining_row[0] + remaining_row[1] + remaining_row[2]

            # Find amount due for current period (first unpaid installment)
            first_unpaid_q = await session.execute(
                select(AmortizationSchedule)
                .filter(AmortizationSchedule.loan_id == loan.id)
                .filter(
                    AmortizationSchedule.status.in_(["pending", "partial", "overdue"])
                )
                .order_by(AmortizationSchedule.installment_number)
                .limit(1)
            )
            first_unpaid = first_unpaid_q.scalar_one_or_none()
            current_period_due = Decimal(0)
            if first_unpaid:
                current_period_due = (
                    (first_unpaid.principal_due - first_unpaid.principal_paid)
                    + (first_unpaid.interest_due - first_unpaid.interest_paid)
                    + (first_unpaid.penalty_due - first_unpaid.penalty_paid)
                )

            is_prepayment = amount > current_period_due and current_period_due > 0
            if is_prepayment and not prod.prepayment_allowed:
                return LoanResponse(
                    success=False,
                    message="Prepayment is not allowed for this loan product. Maximum payment: "
                    + str(current_period_due),
                )

            # Calculate prepayment penalty if applicable
            prepayment_penalty = Decimal(0)
            if (
                is_prepayment
                and prod.prepayment_penalty_rate
                and prod.prepayment_penalty_rate > 0
            ):
                excess = amount - current_period_due
                prepayment_penalty = round(
                    excess * prod.prepayment_penalty_rate / Decimal(100), 2
                )

            effective_amount = amount  # Amount applied to schedule

            funds_remaining = effective_amount

            # Fetch pending or partial schedules
            sched_result = await session.execute(
                select(AmortizationSchedule)
                .filter(AmortizationSchedule.loan_id == loan.id)
                .filter(
                    AmortizationSchedule.status.in_(["pending", "partial", "overdue"])
                )
                .order_by(AmortizationSchedule.installment_number)
            )
            schedules = sched_result.scalars().all()

            total_principal_paid = Decimal(0)
            total_interest_paid = Decimal(0)
            total_penalty_paid = Decimal(0)

            for sched in schedules:
                if funds_remaining <= 0:
                    break

                # 1. Pay Penalty
                penalty_shortfall = sched.penalty_due - sched.penalty_paid
                if penalty_shortfall > 0:
                    paid = min(funds_remaining, penalty_shortfall)
                    sched.penalty_paid += paid
                    funds_remaining -= paid
                    total_penalty_paid += paid

                # 2. Pay Interest
                if funds_remaining > 0:
                    interest_shortfall = sched.interest_due - sched.interest_paid
                    if interest_shortfall > 0:
                        paid = min(funds_remaining, interest_shortfall)
                        sched.interest_paid += paid
                        funds_remaining -= paid
                        total_interest_paid += paid

                # 3. Pay Principal
                if funds_remaining > 0:
                    principal_shortfall = sched.principal_due - sched.principal_paid
                    if principal_shortfall > 0:
                        paid = min(funds_remaining, principal_shortfall)
                        sched.principal_paid += paid
                        funds_remaining -= paid
                        total_principal_paid += paid

                # Update status
                if (
                    sched.principal_due == sched.principal_paid
                    and sched.interest_due == sched.interest_paid
                    and sched.penalty_due == sched.penalty_paid
                ):
                    sched.status = "paid"
                    sched.payment_date = transaction_date
                else:
                    sched.status = "partial"
                    if sched.principal_paid > 0 or sched.interest_paid > 0:
                        sched.payment_date = transaction_date

            # Check if entire loan is paid off
            check_unpaid = await session.execute(
                select(AmortizationSchedule)
                .filter(AmortizationSchedule.loan_id == loan.id)
                .filter(AmortizationSchedule.status != "paid")
            )
            if not check_unpaid.scalars().first():
                loan.status = "paid"

            # 4. Add LoanTransaction
            txn = LoanTransaction(
                loan_id=loan.id,
                type="repayment",
                amount=amount,
                receipt_number=f"REP-{uuid.uuid4().hex[:6].upper()}",
                description=f"Principal: {total_principal_paid}, Interest: {total_interest_paid}, Penalty: {total_penalty_paid}",
                processed_by=str(current_user.id),
            )
            session.add(txn)

            # If prepayment penalty applies, record it
            if prepayment_penalty > 0:
                penalty_txn = LoanTransaction(
                    loan_id=loan.id,
                    type="fee",
                    amount=prepayment_penalty,
                    receipt_number=f"PPF-{uuid.uuid4().hex[:6].upper()}",
                    description="Prepayment penalty fee",
                    processed_by=str(current_user.id),
                )
                session.add(penalty_txn)

            # 5. GL entries with proper principal/interest split
            gl_lines = [
                {
                    "account_code": "1010",
                    "debit": amount,
                    "credit": Decimal(0),
                    "description": "Cash in Bank",
                },
            ]
            if total_principal_paid > 0:
                gl_lines.append(
                    {
                        "account_code": "1300",
                        "debit": Decimal(0),
                        "credit": total_principal_paid,
                        "description": "Loans Receivable (principal)",
                    }
                )
            if total_interest_paid > 0:
                gl_lines.append(
                    {
                        "account_code": "4100",
                        "debit": Decimal(0),
                        "credit": total_interest_paid,
                        "description": "Interest Income",
                    }
                )
            if total_penalty_paid > 0:
                gl_lines.append(
                    {
                        "account_code": "4300",
                        "debit": Decimal(0),
                        "credit": total_penalty_paid,
                        "description": "Penalty Income",
                    }
                )
            if prepayment_penalty > 0:
                gl_lines.append(
                    {
                        "account_code": "4400",
                        "debit": Decimal(0),
                        "credit": prepayment_penalty,
                        "description": "Prepayment Penalty Income",
                    }
                )
            # Handle overpayment — credit remainder as advance/unapplied
            if funds_remaining > 0:
                gl_lines.append(
                    {
                        "account_code": "2100",
                        "debit": Decimal(0),
                        "credit": funds_remaining,
                        "description": "Customer Advance (overpayment)",
                    }
                )

            await create_journal_entry(
                session=session,
                reference_no=f"JNL-{txn.receipt_number}",
                description=f"Loan Repayment for Loan {loan.id}",
                created_by=str(current_user.id),
                lines=gl_lines,
            )
            try:
                from .services.loan_accounting_service import post_loan_repayment
                from .database import get_async_session_local
                bank_session_factory = get_async_session_local()
                total_minor = int((amount * Decimal(100)).to_integral_value())
                penalty_minor = int((total_penalty_paid * Decimal(100)).to_integral_value())
                fee_minor = int((prepayment_penalty * Decimal(100)).to_integral_value())
                interest_minor = int((total_interest_paid * Decimal(100)).to_integral_value())
                principal_minor = int((total_principal_paid * Decimal(100)).to_integral_value())
                overpay_minor = int((funds_remaining * Decimal(100)).to_integral_value())
                async with bank_session_factory() as bank_session:
                    await post_loan_repayment(
                        bank_session,
                        loan_id=loan.id,
                        total_minor=total_minor,
                        penalty_minor=penalty_minor,
                        fee_minor=fee_minor,
                        interest_minor=interest_minor,
                        principal_minor=principal_minor,
                        overpayment_minor=overpay_minor,
                        customer_id=str(loan.customer_id) if loan.customer_id is not None else None,
                        branch_code=loan.branch_code,
                        idempotency_key=f"REPAY-{txn.receipt_number}",
                        created_by=str(current_user.id),
                    )
            except Exception as bg_err:
                print(f"Warning: bank-grade repayment posting failed: {bg_err}")

            await session.commit()
            msg = f"Repayment of {amount} processed. Principal: {total_principal_paid}, Interest: {total_interest_paid}"
            if total_penalty_paid > 0:
                msg += f", Penalty: {total_penalty_paid}"
            if prepayment_penalty > 0:
                msg += f", Prepayment fee: {prepayment_penalty}"
            if funds_remaining > 0:
                msg += f", Overpayment credited: {funds_remaining}"
            return LoanResponse(success=True, message=msg)

    # ── Phase 2.2 — Multi-stage Approval Workflow ────────────────────────

    @strawberry.mutation
    async def submit_loan(self, info: Info, id: strawberry.ID) -> LoanResponse:
        """Borrower or officer submits a draft loan for review (draft → submitted)."""
        current_user: UserInDB = info.context.get("current_user")
        if not current_user:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED, detail="Not authenticated"
            )

        async for session in get_db_session():
            result = await session.execute(
                select(LoanApplication).filter(LoanApplication.id == int(id))
            )
            loan = result.scalar_one_or_none()
            if not loan:
                return LoanResponse(success=False, message="Loan not found")
            if loan.status != "draft":
                return LoanResponse(
                    success=False,
                    message=f"Cannot submit a loan in '{loan.status}' status",
                )

            loan.status = "submitted"
            await session.commit()
            return LoanResponse(success=True, message="Loan submitted for review")

    @strawberry.mutation
    async def review_loan(
        self, info: Info, id: strawberry.ID, note: Optional[str] = None
    ) -> LoanResponse:
        """Loan officer picks up a submitted loan for review (submitted → reviewing)."""
        current_user: UserInDB = info.context.get("current_user")
        if not current_user or current_user.role in ["customer"]:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Only staff can review loans",
            )

        async for session in get_db_session():
            result = await session.execute(
                select(LoanApplication).filter(LoanApplication.id == int(id))
            )
            loan = result.scalar_one_or_none()
            if not loan:
                return LoanResponse(success=False, message="Loan not found")
            if loan.status != "submitted":
                return LoanResponse(
                    success=False,
                    message=f"Cannot review a loan in '{loan.status}' status",
                )

            loan.status = "reviewing"
            loan.reviewed_by = str(current_user.id)
            if note:
                loan.review_note = note
            await session.commit()
            return LoanResponse(success=True, message="Loan is now under review")

    @strawberry.mutation
    async def approve_loan(
        self,
        info: Info,
        id: strawberry.ID,
        approved_principal: Optional[Decimal] = None,
        approved_rate: Optional[Decimal] = None,
    ) -> LoanResponse:
        """Branch manager or admin approves a reviewed loan (reviewing → approved).
        Creates journal entries following GAAP:
        - Dr. Loans Receivable (1300) - recognizes the loan asset
        - Cr. Disbursement Payable (2000) - recognizes liability to disburse funds
        """
        current_user: UserInDB = info.context.get("current_user")
        if not current_user or current_user.role not in ["admin", "staff"]:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Only admin or staff can approve loans",
            )

        async for session in get_db_session():
            result = await session.execute(
                select(LoanApplication).filter(LoanApplication.id == int(id))
            )
            loan = result.scalar_one_or_none()
            if not loan:
                return LoanResponse(success=False, message="Loan not found")
            if loan.status != "reviewing":
                return LoanResponse(
                    success=False,
                    message=f"Cannot approve a loan in '{loan.status}' status",
                )

            # Determine approved amount
            approved_amount = approved_principal if approved_principal is not None else (loan.approved_principal or loan.principal)
            
            # Get customer name for journal entries
            from .database.pg_core_models import Customer
            if str(loan.customer_id).isdigit():
                customer_stmt = select(Customer).where(Customer.id == int(str(loan.customer_id)))
            else:
                customer_stmt = select(Customer).where(Customer.id == int(str(loan.customer_id)) if str(loan.customer_id).isdigit() else False)
            
            customer_res = await session.execute(customer_stmt)
            customer = customer_res.scalar_one_or_none()
            customer_name = customer.display_name if customer else "Customer"
            
            loan.status = "approved"
            loan.approved_by = str(current_user.id)
            if approved_principal is not None:
                loan.approved_principal = approved_principal
            if approved_rate is not None:
                loan.approved_rate = approved_rate

            # Create GAAP-compliant journal entry for loan approval
            # Dr. Loans Receivable (1300) - recognizes the loan as an asset
            # Cr. Disbursement Payable (2010) - recognizes liability to disburse funds
            reference_no = f"JNL-APRV-{loan.id:06d}"
            gl_lines = [
                {
                    "account_code": "1300",
                    "debit": approved_amount,
                    "credit": Decimal(0),
                    "description": f"Loan Approval - {customer_name}",
                },
                {
                    "account_code": "2010",
                    "debit": Decimal(0),
                    "credit": approved_amount,
                    "description": f"Disbursement Payable - {customer_name}",
                },
            ]
            
            try:
                await create_journal_entry(
                    session=session,
                    reference_no=reference_no,
                    description=f"Loan Approval - Customer {loan.customer_id} - Principal {approved_amount}",
                    created_by=str(current_user.id),
                    lines=gl_lines,
                )
            except Exception as e:
                import logging
                logging.error(f"Failed to create journal entry for loan approval: {e}")

            await session.commit()
            return LoanResponse(
                success=True, message="Loan approved — ready for disbursement"
            )

    @strawberry.mutation
    async def reject_loan(
        self, info: Info, id: strawberry.ID, reason: str
    ) -> LoanResponse:
        """Reject a loan that is under review (reviewing → rejected)."""
        current_user: UserInDB = info.context.get("current_user")
        if not current_user or current_user.role in ["customer"]:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN, detail="Not authorized"
            )

        async for session in get_db_session():
            result = await session.execute(
                select(LoanApplication).filter(LoanApplication.id == int(id))
            )
            loan = result.scalar_one_or_none()
            if not loan:
                return LoanResponse(success=False, message="Loan not found")
            if loan.status not in ["submitted", "reviewing"]:
                return LoanResponse(
                    success=False,
                    message=f"Cannot reject a loan in '{loan.status}' status",
                )

            loan.status = "rejected"
            loan.rejected_reason = reason
            await session.commit()
            return LoanResponse(success=True, message="Loan rejected")

    # ── Phase 2.4 — Write-off ────────────────────────────────────────────

    @strawberry.mutation
    async def write_off_loan(
        self, info: Info, id: strawberry.ID, reason: str
    ) -> LoanResponse:
        """Write off a defaulted/non-performing loan. Creates provision GL entries."""
        current_user: UserInDB = info.context.get("current_user")
        if not current_user or current_user.role != "admin":
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Only admin can write off loans",
            )

        async for session in get_db_session():
            result = await session.execute(
                select(LoanApplication).filter(LoanApplication.id == int(id))
            )
            loan = result.scalar_one_or_none()
            if not loan or loan.status not in ["active", "defaulted"]:
                return LoanResponse(
                    success=False,
                    message="Loan not found or not eligible for write-off",
                )

            # Calculate outstanding balance
            sched_result = await session.execute(
                select(
                    sa_func.coalesce(
                        sa_func.sum(
                            AmortizationSchedule.principal_due
                            - AmortizationSchedule.principal_paid
                        ),
                        0,
                    ),
                    sa_func.coalesce(
                        sa_func.sum(
                            AmortizationSchedule.interest_due
                            - AmortizationSchedule.interest_paid
                        ),
                        0,
                    ),
                )
                .filter(AmortizationSchedule.loan_id == loan.id)
                .filter(AmortizationSchedule.status != "paid")
            )
            row = sched_result.one()
            outstanding_principal = row[0]
            outstanding_interest = row[1]
            total_writeoff = outstanding_principal + outstanding_interest

            loan.status = "written_off"

            # GL: Dr Loan Loss Expense (5200), Cr Loans Receivable (1300)
            txn = LoanTransaction(
                loan_id=loan.id,
                type="write_off",
                amount=total_writeoff,
                receipt_number=f"WOF-{uuid.uuid4().hex[:6].upper()}",
                description=f"Write-off: {reason}. Principal: {outstanding_principal}, Interest: {outstanding_interest}",
                processed_by=str(current_user.id),
            )
            session.add(txn)

            await create_journal_entry(
                session=session,
                reference_no=f"JNL-{txn.receipt_number}",
                description=f"Loan Write-off for Loan {loan.id} — {reason}",
                created_by=str(current_user.id),
                lines=[
                    {
                        "account_code": "5200",
                        "debit": total_writeoff,
                        "credit": Decimal(0),
                        "description": "Loan Loss Expense",
                    },
                    {
                        "account_code": "1300",
                        "debit": Decimal(0),
                        "credit": total_writeoff,
                        "description": "Loans Receivable (written off)",
                    },
                ],
            )

            # Mark all remaining schedules as written off
            for_update = await session.execute(
                select(AmortizationSchedule)
                .filter(AmortizationSchedule.loan_id == loan.id)
                .filter(AmortizationSchedule.status != "paid")
            )
            for sched in for_update.scalars().all():
                sched.status = "written_off"

            await session.commit()
            return LoanResponse(
                success=True, message=f"Loan written off — total: {total_writeoff}"
            )


# ── Phase 2.4 — Collections Dashboard Types & Query ──────────────────────


@strawberry.type
class AgingBucket:
    label: str  # e.g. "Current", "1-30 DPD"
    loan_count: int
    total_outstanding: Decimal
    loans: List[LoanType]


@strawberry.type
class CollectionsDashboardResponse:
    success: bool
    message: str
    buckets: List[AgingBucket]
    total_outstanding: Decimal
    total_loans: int


@strawberry.type
class AmortizationRow:
    installment_number: int
    due_date: datetime
    principal_due: Decimal
    interest_due: Decimal
    penalty_due: Decimal
    principal_paid: Decimal
    interest_paid: Decimal
    penalty_paid: Decimal
    status: str
    total_due: Decimal
    total_paid: Decimal
    payment_date: Optional[datetime] = None


@strawberry.type
class LoanAmortizationResponse:
    success: bool
    message: str
    rows: List[AmortizationRow]


@strawberry.type
class AmortizationUpdateResponse:
    success: bool
    message: str


@strawberry.type
class CollectionsQuery:
    @strawberry.field
    async def collections_dashboard(self, info: Info) -> CollectionsDashboardResponse:
        """Returns loan aging buckets for the collections dashboard."""
        current_user: UserInDB = info.context.get("current_user")
        if not current_user or current_user.role in ["customer"]:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN, detail="Not authorized"
            )

        from datetime import date

        today = date.today()

        async for session in get_db_session():
            # Fetch all active loans
            result = await session.execute(
                select(LoanApplication).filter(
                    LoanApplication.status.in_(["active", "defaulted"])
                )
            )
            active_loans = result.scalars().all()

            bucket_defs = [
                ("Current", 0, 0),
                ("1-30 DPD", 1, 30),
                ("31-60 DPD", 31, 60),
                ("61-90 DPD", 61, 90),
                ("90+ DPD", 91, 9999),
            ]
            buckets = {
                label: {"loans": [], "total": Decimal(0)} for label, _, _ in bucket_defs
            }

            for loan_app in active_loans:
                # Find the oldest overdue installment
                overdue_q = await session.execute(
                    select(AmortizationSchedule)
                    .filter(AmortizationSchedule.loan_id == loan_app.id)
                    .filter(AmortizationSchedule.status.in_(["pending", "partial"]))
                    .filter(AmortizationSchedule.due_date < today)
                    .order_by(AmortizationSchedule.due_date)
                    .limit(1)
                )
                oldest_overdue = overdue_q.scalar_one_or_none()

                if oldest_overdue:
                    dpd = (today - oldest_overdue.due_date).days
                else:
                    dpd = 0

                # Calculate outstanding
                outstanding_q = await session.execute(
                    select(
                        sa_func.coalesce(
                            sa_func.sum(
                                (
                                    AmortizationSchedule.principal_due
                                    - AmortizationSchedule.principal_paid
                                )
                                + (
                                    AmortizationSchedule.interest_due
                                    - AmortizationSchedule.interest_paid
                                )
                                + (
                                    AmortizationSchedule.penalty_due
                                    - AmortizationSchedule.penalty_paid
                                )
                            ),
                            0,
                        )
                    )
                    .filter(AmortizationSchedule.loan_id == loan_app.id)
                    .filter(AmortizationSchedule.status != "paid")
                )
                outstanding = outstanding_q.scalar() or Decimal(0)

                loan_type = LoanType(
                    id=strawberry.ID(str(loan_app.id)),
                    customer_id=loan_app.customer_id,
                    product_id=loan_app.product_id,
                    principal=loan_app.principal,
                    term_months=loan_app.term_months,
                    approved_principal=loan_app.approved_principal,
                    approved_rate=loan_app.approved_rate,
                    status=loan_app.status,
                    created_at=loan_app.created_at,
                    updated_at=loan_app.updated_at,
                    disbursed_at=loan_app.disbursed_at,
                )

                for label, lo, hi in bucket_defs:
                    if lo <= dpd <= hi:
                        buckets[label]["loans"].append(loan_type)
                        buckets[label]["total"] += outstanding
                        break

            aging_buckets = []
            grand_total = Decimal(0)
            total_loans = 0
            for label, _, _ in bucket_defs:
                b = buckets[label]
                aging_buckets.append(
                    AgingBucket(
                        label=label,
                        loan_count=len(b["loans"]),
                        total_outstanding=b["total"],
                        loans=b["loans"],
                    )
                )
                grand_total += b["total"]
                total_loans += len(b["loans"])

            return CollectionsDashboardResponse(
                success=True,
                message="OK",
                buckets=aging_buckets,
                total_outstanding=grand_total,
                total_loans=total_loans,
            )

    @strawberry.field
    async def loan_amortization(
        self, info: Info, loan_id: int
    ) -> LoanAmortizationResponse:
        """Fetch the actual amortization schedule for a loan (post-disbursement)."""
        current_user: UserInDB = info.context.get("current_user")
        if not current_user:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED, detail="Not authenticated"
            )

        async for session in get_db_session():
            result = await session.execute(
                select(AmortizationSchedule)
                .filter(AmortizationSchedule.loan_id == loan_id)
                .order_by(AmortizationSchedule.installment_number)
            )
            schedules = result.scalars().all()
            rows = []
            for s in schedules:
                total_due = s.principal_due + s.interest_due + s.penalty_due
                total_paid = s.principal_paid + s.interest_paid + s.penalty_paid
                rows.append(
                    AmortizationRow(
                        installment_number=s.installment_number,
                        due_date=datetime.combine(s.due_date, datetime.min.time())
                        if hasattr(s.due_date, "year")
                        else s.due_date,
                        principal_due=s.principal_due,
                        interest_due=s.interest_due,
                        penalty_due=s.penalty_due,
                        principal_paid=s.principal_paid,
                        interest_paid=s.interest_paid,
                        penalty_paid=s.penalty_paid,
                        status=s.status,
                        total_due=total_due,
                        total_paid=total_paid,
                        payment_date=s.payment_date,
                    )
                )
            return LoanAmortizationResponse(success=True, message="OK", rows=rows)


# ── Phase 2.2 — Credit Scoring Types ───────────────────────────────────────────


@strawberry.type
@strawberry.type
class CreditScoreType:
    id: int
    loan_id: int
    character_score: Optional[Decimal]
    character_notes: Optional[str]
    capacity_score: Optional[Decimal]
    capacity_notes: Optional[str]
    capital_score: Optional[Decimal]
    capital_notes: Optional[str]
    collateral_score: Optional[Decimal]
    collateral_notes: Optional[str]
    conditions_score: Optional[Decimal]
    conditions_notes: Optional[str]
    overall_score: Optional[Decimal]
    recommendation: Optional[str]
    dti_ratio: Optional[Decimal]
    dti_score: Optional[Decimal]
    assessed_by: Optional[str]
    assessed_at: Optional[datetime]


@strawberry.type
class CreditScoreResponse:
    success: bool
    message: str
    credit_score: Optional[CreditScoreType] = None


@strawberry.input
class CreditScoreInput:
    character_score: Optional[Decimal] = None
    character_notes: Optional[str] = None
    capacity_score: Optional[Decimal] = None
    capacity_notes: Optional[str] = None
    capital_score: Optional[Decimal] = None
    capital_notes: Optional[str] = None
    collateral_score: Optional[Decimal] = None
    collateral_notes: Optional[str] = None
    conditions_score: Optional[Decimal] = None
    conditions_notes: Optional[str] = None


# ── Phase 2.2 — Loan Application Documents Types ─────────────────────────────


@strawberry.type
class LoanDocumentType:
    id: int
    loan_id: int
    doc_type: str
    file_name: str
    status: str
    rejection_reason: Optional[str]
    created_at: datetime


@strawberry.type
class LoanDocumentsResponse:
    success: bool
    message: str
    documents: List[LoanDocumentType]


@strawberry.input
class LoanDocumentUploadInput:
    loan_id: int
    doc_type: str
    file_name: str
    file_base64: str


# ── Phase 2.3 — Disbursement Checklist Types ─────────────────────────────────


@strawberry.type
class DisbursementChecklistType:
    id: int
    loan_id: int
    item_name: str
    item_description: Optional[str]
    is_required: bool
    status: str
    notes: Optional[str]
    satisfied_by: Optional[str]
    satisfied_at: Optional[datetime]


@strawberry.type
class DisbursementChecklistResponse:
    success: bool
    message: str
    items: List[DisbursementChecklistType]


@strawberry.input
class DisbursementChecklistInput:
    item_name: str
    item_description: Optional[str] = None
    is_required: bool = True


@strawberry.input
class DisbursementChecklistUpdateInput:
    item_id: int
    status: str
    notes: Optional[str] = None


# ── Phase 2.3 — Tranche Types ─────────────────────────────────────────────────


@strawberry.type
class LoanTrancheType:
    id: int
    loan_id: int
    tranche_number: int
    amount: Decimal
    release_date: Optional[datetime]
    status: str
    released_by: Optional[str]
    released_at: Optional[datetime]
    notes: Optional[str]


@strawberry.type
class LoanTranchesResponse:
    success: bool
    message: str
    tranches: List[LoanTrancheType]


@strawberry.input
class LoanTrancheInput:
    amount: Decimal
    release_date: Optional[datetime] = None
    notes: Optional[str] = None


# ── Phase 2.4 — PTP Types ───────────────────────────────────────────────────


@strawberry.type
class PromiseToPayType:
    id: int
    loan_id: int
    ptp_date: date
    ptp_amount: Decimal
    contact_method: Optional[str]
    contact_attempted: int
    contact_result: Optional[str]
    status: str
    fulfilled_at: Optional[datetime]
    broken_reason: Optional[str]
    created_by: Optional[str]
    created_at: datetime


@strawberry.type
class PromiseToPayResponse:
    success: bool
    message: str
    ptp: Optional[PromiseToPayType] = None


@strawberry.type
class PromiseToPaysResponse:
    success: bool
    message: str
    ptps: List[PromiseToPayType]


@strawberry.input
class PromiseToPayInput:
    ptp_date: date
    ptp_amount: Decimal
    contact_method: Optional[str] = None
    contact_result: Optional[str] = None


@strawberry.input
class AmortizationRowUpdateInput:
    loan_id: int
    installment_number: int
    due_date: Optional[str] = None
    principal_due: Optional[Decimal] = None
    interest_due: Optional[Decimal] = None
    penalty_due: Optional[Decimal] = None
    principal_paid: Optional[Decimal] = None
    interest_paid: Optional[Decimal] = None
    penalty_paid: Optional[Decimal] = None
    status: Optional[str] = None
    payment_date: Optional[str] = None


# ── Extended Mutation for new Phase 2 features ───────────────────────────────


@strawberry.type
class ExtendedLoanMutation:
    @strawberry.mutation
    async def update_amortization_row(
        self, info: Info, input: AmortizationRowUpdateInput
    ) -> AmortizationUpdateResponse:
        """Update any field in a specific amortization schedule installment.
        Only admin users can modify amortization rows.
        Records journal entries if payment amounts are changed.
        """
        current_user: UserInDB = info.context.get("current_user")
        if not current_user or current_user.role != "admin":
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Only admins can update amortization rows",
            )

        async for session in get_db_session():
            result = await session.execute(
                select(AmortizationSchedule)
                .filter(AmortizationSchedule.loan_id == input.loan_id)
                .filter(AmortizationSchedule.installment_number == input.installment_number)
            )
            sched = result.scalar_one_or_none()

            if not sched:
                return AmortizationUpdateResponse(
                    success=False, message="Amortization schedule row not found"
                )

            # Store old values for accounting adjustments
            old_principal_paid = sched.principal_paid or Decimal("0")
            old_interest_paid = sched.interest_paid or Decimal("0")
            old_penalty_paid = sched.penalty_paid or Decimal("0")

            if input.due_date:
                try:
                    sched.due_date = datetime.strptime(input.due_date, "%Y-%m-%d").date()
                except ValueError:
                    return AmortizationUpdateResponse(
                        success=False, message="Invalid due_date format. Use YYYY-MM-DD"
                    )

            if input.payment_date:
                try:
                    sched.payment_date = datetime.strptime(input.payment_date, "%Y-%m-%d")
                except ValueError:
                    return AmortizationUpdateResponse(
                        success=False, message="Invalid payment_date format. Use YYYY-MM-DD"
                    )

            if input.principal_due is not None:
                sched.principal_due = input.principal_due
            if input.interest_due is not None:
                sched.interest_due = input.interest_due
            if input.penalty_due is not None:
                sched.penalty_due = input.penalty_due
            if input.principal_paid is not None:
                sched.principal_paid = input.principal_paid
            if input.interest_paid is not None:
                sched.interest_paid = input.interest_paid
            if input.penalty_paid is not None:
                sched.penalty_paid = input.penalty_paid
            if input.status is not None:
                sched.status = input.status

            # Calculate differences for accounting
            diff_principal = (sched.principal_paid or Decimal("0")) - old_principal_paid
            diff_interest = (sched.interest_paid or Decimal("0")) - old_interest_paid
            diff_penalty = (sched.penalty_paid or Decimal("0")) - old_penalty_paid
            total_diff = diff_principal + diff_interest + diff_penalty

            if total_diff != 0:
                # Record as an adjustment transaction
                txn = LoanTransaction(
                    loan_id=sched.loan_id,
                    type="repayment",  # Admin adjustment is still a repayment correction
                    amount=total_diff,
                    receipt_number=f"ADJ-{uuid.uuid4().hex[:6].upper()}",
                    description=f"Admin Adjustment for installment {sched.installment_number}. Principal: {diff_principal}, Interest: {diff_interest}, Penalty: {diff_penalty}",
                    processed_by=str(current_user.id),
                )
                session.add(txn)

                # GL entries
                gl_lines = []
                
                # Cash Adjustment (1010)
                if total_diff > 0:
                    gl_lines.append({
                        "account_code": "1010",
                        "debit": total_diff,
                        "credit": Decimal("0"),
                        "description": f"Cash Adjustment (Increase) - Loan {sched.loan_id} Inst {sched.installment_number}",
                    })
                else:
                    gl_lines.append({
                        "account_code": "1010",
                        "debit": Decimal("0"),
                        "credit": abs(total_diff),
                        "description": f"Cash Adjustment (Decrease) - Loan {sched.loan_id} Inst {sched.installment_number}",
                    })

                # Loans Receivable Adjustment (1300) - Normal balance is Debit. Credit increases (repayment), Debit decreases.
                # Wait, if principal_paid increases, diff_principal > 0, we should Credit 1300.
                if diff_principal > 0:
                    gl_lines.append({
                        "account_code": "1300",
                        "debit": Decimal("0"),
                        "credit": diff_principal,
                        "description": "Loans Receivable Adjustment (Credit)",
                    })
                elif diff_principal < 0:
                    gl_lines.append({
                        "account_code": "1300",
                        "debit": abs(diff_principal),
                        "credit": Decimal("0"),
                        "description": "Loans Receivable Adjustment (Debit)",
                    })

                # Interest Income Adjustment (4100) - Normal balance is Credit.
                if diff_interest > 0:
                    gl_lines.append({
                        "account_code": "4100",
                        "debit": Decimal("0"),
                        "credit": diff_interest,
                        "description": "Interest Income Adjustment (Credit)",
                    })
                elif diff_interest < 0:
                    gl_lines.append({
                        "account_code": "4100",
                        "debit": abs(diff_interest),
                        "credit": Decimal("0"),
                        "description": "Interest Income Adjustment (Debit)",
                    })

                # Penalty Income Adjustment (4300) - Normal balance is Credit.
                if diff_penalty > 0:
                    gl_lines.append({
                        "account_code": "4300",
                        "debit": Decimal("0"),
                        "credit": diff_penalty,
                        "description": "Penalty Income Adjustment (Credit)",
                    })
                elif diff_penalty < 0:
                    gl_lines.append({
                        "account_code": "4300",
                        "debit": abs(diff_penalty),
                        "credit": Decimal("0"),
                        "description": "Penalty Income Adjustment (Debit)",
                    })

                await create_journal_entry(
                    session=session,
                    reference_no=f"JNL-{txn.receipt_number}",
                    description=f"Manual Payment Adjustment - Loan {sched.loan_id}",
                    created_by=str(current_user.id),
                    lines=gl_lines,
                )

            await session.commit()

            return AmortizationUpdateResponse(
                success=True, message="Amortization row and accounting records updated successfully"
            )

        return AmortizationUpdateResponse(
            success=False, message="Failed to update amortization row"
        )

    # ── Credit Scoring ────────────────────────────────────────────────────────
    @strawberry.mutation
    async def assess_credit_score(
        self, info: Info, loan_id: int, input: CreditScoreInput
    ) -> CreditScoreResponse:
        """Assess loan using 5 Cs of credit scoring."""
        current_user: UserInDB = info.context.get("current_user")
        if not current_user or current_user.role not in [
            "admin",
            "staff",
            "loan_officer",
        ]:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN, detail="Not authorized"
            )

        async for session in get_db_session():
            # Calculate overall score (weighted average)
            scores = []
            weights = []

            if input.character_score is not None:
                scores.append(input.character_score)
                weights.append(0.20)
            if input.capacity_score is not None:
                scores.append(input.capacity_score)
                weights.append(0.30)
            if input.capital_score is not None:
                scores.append(input.capital_score)
                weights.append(0.15)
            if input.collateral_score is not None:
                scores.append(input.collateral_score)
                weights.append(0.20)
            if input.conditions_score is not None:
                scores.append(input.conditions_score)
                weights.append(0.15)

            overall_score = None
            if scores and weights:
                total_weight = sum(weights)
                overall_score = (
                    sum(s * w for s, w in zip(scores, weights)) / total_weight
                )
                overall_score = round(overall_score, 2)

            recommendation = "review"
            if overall_score is not None:
                if overall_score >= 70:
                    recommendation = "approve"
                elif overall_score < 40:
                    recommendation = "reject"

            credit_score = CreditScore(
                loan_id=loan_id,
                character_score=input.character_score,
                character_notes=input.character_notes,
                capacity_score=input.capacity_score,
                capacity_notes=input.capacity_notes,
                capital_score=input.capital_score,
                capital_notes=input.capital_notes,
                collateral_score=input.collateral_score,
                collateral_notes=input.collateral_notes,
                conditions_score=input.conditions_score,
                conditions_notes=input.conditions_notes,
                overall_score=overall_score,
                recommendation=recommendation,
                assessed_by=str(current_user.id),
                assessed_at=datetime.now(),
            )
            session.add(credit_score)
            await session.commit()
            await session.refresh(credit_score)

            return CreditScoreResponse(
                success=True,
                message=f"Credit score assessed. Recommendation: {recommendation}",
                credit_score=CreditScoreType(
                    id=credit_score.id,
                    loan_id=credit_score.loan_id,
                    character_score=credit_score.character_score,
                    character_notes=credit_score.character_notes,
                    capacity_score=credit_score.capacity_score,
                    capacity_notes=credit_score.capacity_notes,
                    capital_score=credit_score.capital_score,
                    capital_notes=credit_score.capital_notes,
                    collateral_score=credit_score.collateral_score,
                    collateral_notes=credit_score.collateral_notes,
                    conditions_score=credit_score.conditions_score,
                    conditions_notes=credit_score.conditions_notes,
                    overall_score=credit_score.overall_score,
                    recommendation=credit_score.recommendation,
                    dti_ratio=credit_score.dti_ratio,
                    dti_score=credit_score.dti_score,
                    assessed_by=credit_score.assessed_by,
                    assessed_at=credit_score.assessed_at,
                ),
            )

    # ── DTI Calculation ─────────────────────────────────────────────────────
    @strawberry.mutation
    async def calculate_dti(
        self,
        info: Info,
        loan_id: int,
        monthly_income: Decimal,
        existing_debt_payments: Decimal,
    ) -> CreditScoreResponse:
        """Calculate Debt-to-Income ratio for a loan application."""
        current_user: UserInDB = info.context.get("current_user")
        if not current_user:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED, detail="Not authenticated"
            )

        async for session in get_db_session():
            result = await session.execute(
                select(LoanApplication).filter(LoanApplication.id == loan_id)
            )
            loan = result.scalar_one_or_none()
            if not loan:
                return CreditScoreResponse(success=False, message="Loan not found")

            # Get monthly payment estimate
            monthly_payment = Decimal(0)
            if loan.approved_principal and loan.approved_rate:
                rate_monthly = (loan.approved_rate / Decimal(100)) / Decimal(12)
                if rate_monthly > 0:
                    pmt = (loan.approved_principal * rate_monthly) / (
                        Decimal(1)
                        - (Decimal(1) + rate_monthly) ** Decimal(-loan.term_months)
                    )
                    monthly_payment = pmt

            total_monthly_debt = existing_debt_payments + monthly_payment

            dti_ratio = None
            dti_score = None
            if monthly_income > 0:
                dti_ratio = (total_monthly_debt / monthly_income) * Decimal(100)
                dti_ratio = round(dti_ratio, 4)

                # Score based on DTI
                if dti_ratio <= 15:
                    dti_score = Decimal("100")
                elif dti_ratio <= 28:
                    dti_score = Decimal("80")
                elif dti_ratio <= 36:
                    dti_score = Decimal("60")
                elif dti_ratio <= 43:
                    dti_score = Decimal("40")
                else:
                    dti_score = Decimal("20")

            # Find or create credit score record
            existing_score = await session.execute(
                select(CreditScore).filter(CreditScore.loan_id == loan_id)
            )
            score_record = existing_score.scalar_one_or_none()

            if score_record:
                score_record.dti_ratio = dti_ratio
                score_record.dti_score = dti_score
            else:
                score_record = CreditScore(
                    loan_id=loan_id,
                    dti_ratio=dti_ratio,
                    dti_score=dti_score,
                    assessed_by=str(current_user.id),
                    assessed_at=datetime.now(),
                )
                session.add(score_record)

            await session.commit()

            return CreditScoreResponse(
                success=True,
                message=f"DTI calculated: {dti_ratio}%",
                credit_score=CreditScoreType(
                    id=score_record.id,
                    loan_id=score_record.loan_id,
                    dti_ratio=dti_ratio,
                    dti_score=dti_score,
                    overall_score=score_record.overall_score,
                    recommendation=score_record.recommendation,
                    assessed_by=score_record.assessed_by,
                    assessed_at=score_record.assessed_at,
                    character_score=None,
                    character_notes=None,
                    capacity_score=None,
                    capacity_notes=None,
                    capital_score=None,
                    capital_notes=None,
                    collateral_score=None,
                    collateral_notes=None,
                    conditions_score=None,
                    conditions_notes=None,
                ),
            )

    # ── Loan Application Documents ─────────────────────────────────────────
    @strawberry.mutation
    async def upload_loan_document(
        self, info: Info, input: LoanDocumentUploadInput
    ) -> LoanDocumentsResponse:
        """Upload supporting documents for loan application."""
        current_user: UserInDB = info.context.get("current_user")
        if not current_user:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED, detail="Not authenticated"
            )

        import base64

        try:
            file_bytes = base64.b64decode(input.file_base64)
        except Exception:
            return LoanDocumentsResponse(
                success=False, message="Invalid base64", documents=[]
            )

        # Save file
        os.makedirs(settings.UPLOAD_DIR, exist_ok=True)
        safe_name = f"loan_{input.loan_id}_{input.doc_type}_{input.file_name}".replace(
            "/", "_"
        )
        file_path = os.path.join(settings.UPLOAD_DIR, safe_name)

        async with aiofiles.open(file_path, "wb") as f:
            await f.write(file_bytes)

        async for session in get_db_session():
            doc = LoanApplicationDocument(
                loan_id=input.loan_id,
                doc_type=input.doc_type,
                file_name=input.file_name,
                file_path=file_path,
                file_size_bytes=len(file_bytes),
                uploaded_by=str(current_user.id),
            )
            session.add(doc)
            await session.commit()
            await session.refresh(doc)

            return LoanDocumentsResponse(
                success=True,
                message="Document uploaded",
                documents=[
                    LoanDocumentType(
                        id=doc.id,
                        loan_id=doc.loan_id,
                        doc_type=doc.doc_type,
                        file_name=doc.file_name,
                        status=doc.status,
                        rejection_reason=doc.rejection_reason,
                        created_at=doc.created_at,
                    )
                ],
            )

    @strawberry.mutation
    async def verify_loan_document(
        self,
        info: Info,
        document_id: int,
        status: str,
        rejection_reason: Optional[str] = None,
    ) -> LoanDocumentsResponse:
        """Verify or reject a loan document."""
        current_user: UserInDB = info.context.get("current_user")
        if not current_user or current_user.role not in [
            "admin",
            "staff",
            "loan_officer",
        ]:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN, detail="Not authorized"
            )

        async for session in get_db_session():
            doc = await session.get(LoanApplicationDocument, document_id)
            if not doc:
                return LoanDocumentsResponse(
                    success=False, message="Document not found", documents=[]
                )

            doc.status = status
            doc.verified_by = str(current_user.id)
            doc.verified_at = datetime.now()
            if status == "rejected" and rejection_reason:
                doc.rejection_reason = rejection_reason

            await session.commit()

            return LoanDocumentsResponse(
                success=True,
                message=f"Document {status}",
                documents=[
                    LoanDocumentType(
                        id=doc.id,
                        loan_id=doc.loan_id,
                        doc_type=doc.doc_type,
                        file_name=doc.file_name,
                        status=doc.status,
                        rejection_reason=doc.rejection_reason,
                        created_at=doc.created_at,
                    )
                ],
            )

    # ── Disbursement Checklist ───────────────────────────────────────────────
    @strawberry.mutation
    async def add_disbursement_checklist_item(
        self, info: Info, loan_id: int, input: DisbursementChecklistInput
    ) -> DisbursementChecklistResponse:
        """Add item to disbursement checklist."""
        current_user: UserInDB = info.context.get("current_user")
        if not current_user or current_user.role not in ["admin", "staff"]:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN, detail="Not authorized"
            )

        async for session in get_db_session():
            item = DisbursementChecklist(
                loan_id=loan_id,
                item_name=input.item_name,
                item_description=input.item_description,
                is_required=input.is_required,
            )
            session.add(item)
            await session.commit()
            await session.refresh(item)

            return DisbursementChecklistResponse(
                success=True,
                message="Checklist item added",
                items=[
                    DisbursementChecklistType(
                        id=item.id,
                        loan_id=item.loan_id,
                        item_name=item.item_name,
                        item_description=item.item_description,
                        is_required=item.is_required,
                        status=item.status,
                        notes=item.notes,
                        satisfied_by=item.satisfied_by,
                        satisfied_at=item.satisfied_at,
                    )
                ],
            )

    @strawberry.mutation
    async def update_disbursement_checklist_item(
        self, info: Info, input: DisbursementChecklistUpdateInput
    ) -> DisbursementChecklistResponse:
        """Update disbursement checklist item status."""
        current_user: UserInDB = info.context.get("current_user")
        if not current_user or current_user.role not in ["admin", "staff"]:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN, detail="Not authorized"
            )

        async for session in get_db_session():
            item = await session.get(DisbursementChecklist, input.item_id)
            if not item:
                return DisbursementChecklistResponse(
                    success=False, message="Item not found", items=[]
                )

            item.status = input.status
            if input.notes:
                item.notes = input.notes
            item.satisfied_by = str(current_user.id)
            item.satisfied_at = datetime.now()

            await session.commit()

            return DisbursementChecklistResponse(
                success=True,
                message="Checklist item updated",
                items=[
                    DisbursementChecklistType(
                        id=item.id,
                        loan_id=item.loan_id,
                        item_name=item.item_name,
                        item_description=item.item_description,
                        is_required=item.is_required,
                        status=item.status,
                        notes=item.notes,
                        satisfied_by=item.satisfied_by,
                        satisfied_at=item.satisfied_at,
                    )
                ],
            )

    @strawberry.field
    async def get_disbursement_checklist(
        self, info: Info, loan_id: int
    ) -> DisbursementChecklistResponse:
        """Get disbursement checklist for a loan."""
        current_user: UserInDB = info.context.get("current_user")
        if not current_user:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED, detail="Not authenticated"
            )

        async for session in get_db_session():
            result = await session.execute(
                select(DisbursementChecklist).filter(
                    DisbursementChecklist.loan_id == loan_id
                )
            )
            items = result.scalars().all()

            return DisbursementChecklistResponse(
                success=True,
                message="OK",
                items=[
                    DisbursementChecklistType(
                        id=item.id,
                        loan_id=item.loan_id,
                        item_name=item.item_name,
                        item_description=item.item_description,
                        is_required=item.is_required,
                        status=item.status,
                        notes=item.notes,
                        satisfied_by=item.satisfied_by,
                        satisfied_at=item.satisfied_at,
                    )
                    for item in items
                ],
            )

    # ── Partial Disbursement (Tranches) ─────────────────────────────────────
    @strawberry.mutation
    async def create_loan_tranche(
        self, info: Info, loan_id: int, input: LoanTrancheInput
    ) -> LoanTranchesResponse:
        """Create a new tranche for partial disbursement."""
        current_user: UserInDB = info.context.get("current_user")
        if not current_user or current_user.role not in ["admin", "staff"]:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN, detail="Not authorized"
            )

        async for session in get_db_session():
            # Get next tranche number
            result = await session.execute(
                select(func.max(LoanTranche.tranche_number)).filter(
                    LoanTranche.loan_id == loan_id
                )
            )
            max_tranche = result.scalar() or 0

            tranche = LoanTranche(
                loan_id=loan_id,
                tranche_number=max_tranche + 1,
                amount=input.amount,
                release_date=input.release_date,
                notes=input.notes,
            )
            session.add(tranche)
            await session.commit()
            await session.refresh(tranche)

            return LoanTranchesResponse(
                success=True,
                message="Tranche created",
                tranches=[
                    LoanTrancheType(
                        id=tranche.id,
                        loan_id=tranche.loan_id,
                        tranche_number=tranche.tranche_number,
                        amount=tranche.amount,
                        release_date=tranche.release_date,
                        status=tranche.status,
                        released_by=tranche.released_by,
                        released_at=tranche.released_at,
                        notes=tranche.notes,
                    )
                ],
            )

    @strawberry.mutation
    async def release_loan_tranche(
        self, info: Info, tranche_id: int
    ) -> LoanTranchesResponse:
        """Release a tranche (partial disbursement)."""
        current_user: UserInDB = info.context.get("current_user")
        if not current_user or current_user.role not in ["admin", "staff"]:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN, detail="Not authorized"
            )

        async for session in get_db_session():
            tranche = await session.get(LoanTranche, tranche_id)
            if not tranche:
                return LoanTranchesResponse(
                    success=False, message="Tranche not found", tranches=[]
                )

            if tranche.status != "pending":
                return LoanTranchesResponse(
                    success=False,
                    message="Tranche already released or cancelled",
                    tranches=[],
                )

            tranche.status = "released"
            tranche.released_by = str(current_user.id)
            tranche.released_at = datetime.now()

            await session.commit()

            return LoanTranchesResponse(
                success=True,
                message=f"Tranche {tranche.tranche_number} released",
                tranches=[
                    LoanTrancheType(
                        id=tranche.id,
                        loan_id=tranche.loan_id,
                        tranche_number=tranche.tranche_number,
                        amount=tranche.amount,
                        release_date=tranche.release_date,
                        status=tranche.status,
                        released_by=tranche.released_by,
                        released_at=tranche.released_at,
                        notes=tranche.notes,
                    )
                ],
            )

    @strawberry.field
    async def get_loan_tranches(self, info: Info, loan_id: int) -> LoanTranchesResponse:
        """Get all tranches for a loan."""
        current_user: UserInDB = info.context.get("current_user")
        if not current_user:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED, detail="Not authenticated"
            )

        async for session in get_db_session():
            result = await session.execute(
                select(LoanTranche)
                .filter(LoanTranche.loan_id == loan_id)
                .order_by(LoanTranche.tranche_number)
            )
            tranches = result.scalars().all()

            return LoanTranchesResponse(
                success=True,
                message="OK",
                tranches=[
                    LoanTrancheType(
                        id=t.id,
                        loan_id=t.loan_id,
                        tranche_number=t.tranche_number,
                        amount=t.amount,
                        release_date=t.release_date,
                        status=t.status,
                        released_by=t.released_by,
                        released_at=t.released_at,
                        notes=t.notes,
                    )
                    for t in tranches
                ],
            )

    # ── Promise-to-Pay (PTP) ─────────────────────────────────────────────────
    @strawberry.mutation
    async def create_promise_to_pay(
        self, info: Info, loan_id: int, input: PromiseToPayInput
    ) -> PromiseToPayResponse:
        """Create a Promise-to-Pay record."""
        current_user: UserInDB = info.context.get("current_user")
        if not current_user or current_user.role not in [
            "admin",
            "staff",
            "loan_officer",
        ]:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN, detail="Not authorized"
            )

        async for session in get_db_session():
            ptp = PromiseToPay(
                loan_id=loan_id,
                ptp_date=input.ptp_date,
                ptp_amount=input.ptp_amount,
                contact_method=input.contact_method,
                contact_result=input.contact_result,
                contact_attempted=1,
                created_by=str(current_user.id),
            )
            session.add(ptp)
            await session.commit()
            await session.refresh(ptp)

            return PromiseToPayResponse(
                success=True,
                message="Promise-to-Pay created",
                ptp=PromiseToPayType(
                    id=ptp.id,
                    loan_id=ptp.loan_id,
                    ptp_date=ptp.ptp_date,
                    ptp_amount=ptp.ptp_amount,
                    contact_method=ptp.contact_method,
                    contact_attempted=ptp.contact_attempted,
                    contact_result=ptp.contact_result,
                    status=ptp.status,
                    fulfilled_at=ptp.fulfilled_at,
                    broken_reason=ptp.broken_reason,
                    created_by=ptp.created_by,
                    created_at=ptp.created_at,
                ),
            )

    @strawberry.mutation
    async def update_ptp_status(
        self, info: Info, ptp_id: int, status: str, broken_reason: Optional[str] = None
    ) -> PromiseToPayResponse:
        """Update PTP status (fulfilled, broken, cancelled)."""
        current_user: UserInDB = info.context.get("current_user")
        if not current_user or current_user.role not in [
            "admin",
            "staff",
            "loan_officer",
        ]:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN, detail="Not authorized"
            )

        async for session in get_db_session():
            ptp = await session.get(PromiseToPay, ptp_id)
            if not ptp:
                return PromiseToPayResponse(success=False, message="PTP not found")

            ptp.status = status
            if status == "fulfilled":
                ptp.fulfilled_at = datetime.now()
            elif status == "broken" and broken_reason:
                ptp.broken_reason = broken_reason

            await session.commit()

            return PromiseToPayResponse(
                success=True,
                message=f"PTP marked as {status}",
                ptp=PromiseToPayType(
                    id=ptp.id,
                    loan_id=ptp.loan_id,
                    ptp_date=ptp.ptp_date,
                    ptp_amount=ptp.ptp_amount,
                    contact_method=ptp.contact_method,
                    contact_attempted=ptp.contact_attempted,
                    contact_result=ptp.contact_result,
                    status=ptp.status,
                    fulfilled_at=ptp.fulfilled_at,
                    broken_reason=ptp.broken_reason,
                    created_by=ptp.created_by,
                    created_at=ptp.created_at,
                ),
            )

    @strawberry.field
    async def get_loan_ptps(self, info: Info, loan_id: int) -> PromiseToPaysResponse:
        """Get all PTPs for a loan."""
        current_user: UserInDB = info.context.get("current_user")
        if not current_user:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED, detail="Not authenticated"
            )

        async for session in get_db_session():
            result = await session.execute(
                select(PromiseToPay)
                .filter(PromiseToPay.loan_id == loan_id)
                .order_by(PromiseToPay.created_at.desc())
            )
            ptps = result.scalars().all()

            return PromiseToPaysResponse(
                success=True,
                message="OK",
                ptps=[
                    PromiseToPayType(
                        id=p.id,
                        loan_id=p.loan_id,
                        ptp_date=p.ptp_date,
                        ptp_amount=p.ptp_amount,
                        contact_method=p.contact_method,
                        contact_attempted=p.contact_attempted,
                        contact_result=p.contact_result,
                        status=p.status,
                        fulfilled_at=p.fulfilled_at,
                        broken_reason=p.broken_reason,
                        created_by=p.created_by,
                        created_at=p.created_at,
                    )
                    for p in ptps
                ],
            )

    # ── Loan Restructuring/Refinancing ────────────────────────────────────────
    @strawberry.mutation
    async def restructure_loan(
        self, info: Info, loan_id: int, input: "LoanRestructureInput"
    ) -> LoanResponse:
        """Restructure a loan - extend term, adjust rate, or capitalize arrears."""
        current_user: UserInDB = info.context.get("current_user")
        if not current_user or current_user.role not in [
            "admin",
            "staff",
            "branch_manager",
        ]:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN, detail="Not authorized"
            )

        async for session in get_db_session():
            result = await session.execute(
                select(LoanApplication).filter(LoanApplication.id == loan_id)
            )
            loan = result.scalar_one_or_none()

            if not loan or loan.status not in ["active", "past_due"]:
                return LoanResponse(
                    success=False, message="Loan not found or cannot be restructured"
                )

            # Calculate new schedule based on restructuring input
            current_principal = loan.approved_principal or loan.principal
            current_rate = loan.approved_rate or 0

            # Apply restructuring changes
            new_term_months = input.term_months or loan.term_months
            new_rate = input.interest_rate or current_rate
            new_principal = current_principal

            # Capitalize arrears if specified
            if input.capitalize_arrears:
                arrears_amount = input.arrears_amount or Decimal("0")
                new_principal += arrears_amount

            # Update loan
            loan.term_months = new_term_months
            loan.approved_rate = new_rate

            # Create restructuring record
            restructure_log = LoanRestructureLog(
                loan_id=loan.id,
                old_term_months=loan.term_months,
                old_interest_rate=current_rate,
                old_principal=current_principal,
                new_term_months=new_term_months,
                new_interest_rate=new_rate,
                new_principal=new_principal,
                capitalize_arrears=input.capitalize_arrears or False,
                arrears_amount=input.arrears_amount or Decimal("0"),
                reason=input.reason or "Customer request",
                created_by=str(current_user.id),
                created_at=datetime.now(),
            )
            session.add(restructure_log)

            # Generate new amortization schedule
            rate_monthly = new_rate / Decimal(100) / Decimal(12)

            # Clear old schedule
            old_sched_result = await session.execute(
                select(AmortizationSchedule).filter(
                    AmortizationSchedule.loan_id == loan.id
                )
            )
            old_schedules = old_sched_result.scalars().all()
            for sched in old_schedules:
                session.delete(sched)

            # Generate new schedule
            preview_rows = _build_schedule_preview(
                new_principal,
                new_rate,
                new_term_months,
                loan.amortization_type or "declining_balance",
                datetime.now(),
            )

            for row in preview_rows:
                new_sched = AmortizationSchedule(
                    loan_id=loan.id,
                    installment_number=row.installment_number,
                    due_date=row.due_date,
                    principal_due=row.principal_due,
                    interest_due=row.interest_due,
                )
                session.add(new_sched)

            await session.commit()

            return LoanResponse(
                success=True,
                message=f"Loan restructured successfully. New term: {new_term_months} months, Rate: {new_rate}%",
            )

    @strawberry.mutation
    async def update_amortization_payment_date(
        self, info: Info, loanId: int, installmentNumber: int, paymentDate: str
    ) -> "AmortizationUpdateResponse":
        """Update the payment date for a specific amortization schedule installment.
        Only admin users can modify payment dates.
        """
        current_user: UserInDB = info.context.get("current_user")
        if not current_user or current_user.role != "admin":
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN, detail="Only admins can update payment dates"
            )

        try:
            payment_date_parsed = datetime.strptime(paymentDate, "%Y-%m-%d")
        except ValueError:
            return AmortizationUpdateResponse(
                success=False, message="Invalid date format. Use YYYY-MM-DD"
            )

        async for session in get_db_session():
            result = await session.execute(
                select(AmortizationSchedule)
                .filter(AmortizationSchedule.loan_id == loanId)
                .filter(AmortizationSchedule.installment_number == installmentNumber)
            )
            sched = result.scalar_one_or_none()

            if not sched:
                return AmortizationUpdateResponse(
                    success=False, message="Amortization schedule not found"
                )

            sched.payment_date = payment_date_parsed
            await session.commit()

            return AmortizationUpdateResponse(
                success=True, message="Payment date updated successfully"
            )

        return AmortizationUpdateResponse(success=False, message="Failed to update payment date")


@strawberry.type
class LoanRestructureLog:
    id: strawberry.ID
    loan_id: int
    old_term_months: int
    old_interest_rate: Decimal
    old_principal: Decimal
    new_term_months: int
    new_interest_rate: Decimal
    new_principal: Decimal
    capitalize_arrears: bool
    arrears_amount: Decimal
    reason: str
    created_by: str
    created_at: datetime


@strawberry.input
class LoanRestructureInput:
    term_months: Optional[int] = None
    interest_rate: Optional[Decimal] = None
    capitalize_arrears: Optional[bool] = None
    arrears_amount: Optional[Decimal] = None
    reason: Optional[str] = None
