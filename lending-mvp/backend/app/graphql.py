from __future__ import annotations

"""
GraphQL server for Lending MVP using Strawberry
"""

import strawberry
import uuid
from fastapi import Request
from typing import List, Optional
from sqlalchemy import select, func, and_
from sqlalchemy.ext.asyncio import AsyncSession
from strawberry.types import Info
from decimal import Decimal
from datetime import datetime, date

from .database import get_async_session_local
from .database.pg_core_models import (
    User,
    Customer,
    SavingsAccount,
    SavingsTransaction,
)
from .database.pg_loan_models import (
    LoanTransaction,
    LoanApplication,
    AmortizationSchedule,
    PGLoanProduct,
)
from .database.pg_accounting_models import GLAccount, JournalEntry, JournalLine
from .chart_of_accounts import (
    JournalEntryCreateInput,
    JournalEntryResponse,
    GLAccountCreateInput,
    GLAccountResponse,
)
from .graphql_collections_schema import (
    CollectionsDueReport as CollectionsDueReportType,
    CollectionsDueSummary as CollectionsDueSummaryType,
    AgingReport as AgingReportType,
)
from .loan_product import (
    LoanProductType,
    LoanProductCreateInput,
    LoanProductUpdateInput,
)
from .graphql_collections_resolvers import (
    resolve_collections_due,
    resolve_collections_due_summary,
    resolve_aging_report,
)
from .financial_reports import (
    TrialBalanceReport,
    TrialBalanceRow,
    IncomeStatementReport,
    IncomeStatementRow,
    BalanceSheetReport,
    BalanceSheetRow,
    BalanceSheetSection,
    ARAgingReport,
    ARAgingCustomerRow,
    ARAgingBucket,
    APAgingReport,
    APAgingRow,
    resolve_trial_balance,
    resolve_income_statement,
    resolve_balance_sheet,
    resolve_ar_aging,
    resolve_ap_aging,
)
from .delinquency_report import (
    DelinquencyReport,
    DelinquencySummary,
    DelinquencyAgingBucketSummary,
    DelinquentLoanNode,
    DelinquentLoanConnection,
    resolve_delinquency_report,
)
from .database.pg_models import (
    CustomerActivity,
    Collection,
    Branch,
    UserBranchAssignment,
    AuditLog,
)


from .auth.security import get_password_hash, verify_token
from .database.pg_user_crud import UserCRUD


async def get_context(request: Request = None):
    """
    GraphQL context provider.
    Extracts current user from JWT token in Authorization header.
    """
    context = {"current_user": None}
    if not request:
        return context

    auth_header = request.headers.get("Authorization")
    if auth_header and auth_header.startswith("Bearer "):
        token = auth_header.split(" ")[1]
        try:
            payload = verify_token(token)
            user_id = payload.get("sub")
            if user_id:
                session_factory = get_async_session_local()
                async with session_factory() as session:
                    user_crud = UserCRUD(session)
                    # Check if user_id is a UUID or an integer ID
                    from sqlalchemy import or_

                    stmt = select(User).where(
                        or_(
                            User.uuid == str(user_id),
                            User.id == int(user_id)
                            if str(user_id).isdigit()
                            else False,
                        )
                    )
                    res = await session.execute(stmt)
                    user = res.scalar_one_or_none()
                    if user:
                        context["current_user"] = user
        except Exception:
            pass
    return context


@strawberry.type
class Health:
    status: str
    message: str


@strawberry.type
class DashboardStats:
    customersTotal: int
    loansTotal: int
    activeLoans: int
    activeSavingsAccounts: int
    totalPortfolio: Decimal
    overdueLoans: int
    totalCollections: Decimal
    collectedThisMonth: Decimal
    totalOutstanding: Decimal


@strawberry.type
class UserNode:
    id: str
    email: str
    username: str
    fullName: str
    isActive: bool
    role: str
    branchId: Optional[int] = None
    branchCode: Optional[str] = None


@strawberry.input
class UserCreateInput:
    email: str
    username: str
    fullName: str
    password: str
    role: Optional[str] = "customer"
    branchId: Optional[int] = None
    branchCode: Optional[str] = None


@strawberry.input
class UserUpdateInput:
    email: Optional[str] = None
    username: Optional[str] = None
    fullName: Optional[str] = None
    isActive: Optional[bool] = None
    role: Optional[str] = None
    password: Optional[str] = None
    branchId: Optional[int] = None
    branchCode: Optional[str] = None


@strawberry.type
class UserResponse:
    success: bool
    message: str
    user: Optional[UserNode] = None


@strawberry.input
class CustomerInput:
    displayName: str
    customerType: str
    branchCode: str
    emailAddress: Optional[str] = None
    mobileNumber: Optional[str] = None


@strawberry.type
class CustomerResponse:
    success: bool
    message: str
    customer: Optional[CustomerNode] = None


@strawberry.input
class BranchInput:
    code: str
    name: str
    address: Optional[str] = None
    city: Optional[str] = None
    contactNumber: Optional[str] = None


@strawberry.type
class BranchResponse:
    success: bool
    message: str
    branch: Optional[BranchNode] = None


@strawberry.input
class CollectionCreateInput:
    customerId: str
    amount: Decimal
    dueDate: date
    referenceNumber: Optional[str] = None
    collectionType: Optional[str] = None
    notes: Optional[str] = None


@strawberry.type
class CustomerNode:
    id: str
    displayName: str
    customerType: str
    branchCode: str
    isActive: bool
    firstName: Optional[str] = None
    lastName: Optional[str] = None
    emailAddress: Optional[str] = None
    mobileNumber: Optional[str] = None
    customerCategory: Optional[str] = None
    kycStatus: Optional[str] = None
    riskScore: Optional[float] = None
    branch: Optional[str] = None
    createdAt: datetime = strawberry.field(default_factory=datetime.now)


@strawberry.type
class CustomerConnection:
    customers: List[CustomerNode]
    total: int


@strawberry.type
class SavingsAccountNode:
    id: str
    accountNumber: str
    balance: Decimal
    customerId: str
    accountType: str
    status: str
    openedAt: datetime
    createdAt: datetime = strawberry.field(default_factory=datetime.now)
    
    # Ported from master
    currency: str = "PHP"
    interestRate: Optional[Decimal] = None
    maturityDate: Optional[datetime] = None
    principal: Optional[Decimal] = None
    termDays: Optional[int] = None
    interestPaidFrequency: Optional[str] = None
    targetAmount: Optional[Decimal] = None
    targetDate: Optional[datetime] = None
    goalName: Optional[str] = None
    guardianId: Optional[str] = None
    guardianName: Optional[str] = None
    minorDateOfBirth: Optional[datetime] = None
    secondaryOwnerId: Optional[str] = None
    secondaryOwnerName: Optional[str] = None
    operationMode: Optional[str] = "EITHER"

    @strawberry.field
    async def customer(self) -> Optional[CustomerNode]:
        session_factory = get_async_session_local()
        async with session_factory() as session:
            stmt = select(Customer).filter(Customer.id == int(self.customerId))
            result = await session.execute(stmt)
            customer = result.scalar_one_or_none()
            if not customer:
                return None
            return CustomerNode(
                id=str(customer.id),
                displayName=customer.display_name,
                customerType=customer.customer_type,
                branchCode=customer.branch_code,
                isActive=customer.is_active,
                emailAddress=customer.email_address,
                mobileNumber=customer.mobile_number,
                createdAt=customer.created_at,
            )


@strawberry.input
class SavingsAccountCreateInput:
    customerId: str
    accountNumber: str
    accountType: str
    balance: Decimal = Decimal("0.00")
    currency: str = "PHP"
    status: str = "active"
    openedAt: Optional[datetime] = None
    
    # Ported from master
    interestRate: Optional[Decimal] = None
    interestPaidFrequency: Optional[str] = None
    principal: Optional[Decimal] = None
    termDays: Optional[int] = None
    targetAmount: Optional[Decimal] = None
    targetDate: Optional[datetime] = None
    goalName: Optional[str] = None
    guardianId: Optional[str] = None
    guardianName: Optional[str] = None
    minorDateOfBirth: Optional[datetime] = None
    secondaryOwnerId: Optional[str] = None
    secondaryOwnerName: Optional[str] = None
    operationMode: Optional[str] = "EITHER"


@strawberry.type
class SavingsAccountResponse:
    success: bool
    message: str
    account: Optional[SavingsAccountNode] = None


@strawberry.type
class SavingsAccountConnection:
    accounts: List[SavingsAccountNode]
    total: int


@strawberry.type
class SavingsTransactionNode:
    id: str
    accountId: str
    amount: Decimal
    accountType: str
    reference: Optional[str] = None
    description: Optional[str] = None
    balanceBefore: Optional[Decimal] = None
    balanceAfter: Optional[Decimal] = None
    createdAt: datetime


@strawberry.input
class SavingsTransactionCreateInput:
    accountId: str
    amount: Decimal
    transactionType: str  # "deposit" | "withdrawal"
    description: Optional[str] = None
    reference: Optional[str] = None


@strawberry.type
class SavingsTransactionResponse:
    success: bool
    message: str
    transaction: Optional[SavingsTransactionNode] = None


@strawberry.type
class CustomerActivityNode:
    id: str
    customerId: str
    activityType: str
    description: Optional[str] = None
    timestamp: datetime
    createdBy: Optional[str] = None


@strawberry.type
class LoanNode:
    id: str
    principal: Decimal
    status: str
    customerId: str
    productId: Optional[int] = None
    termMonths: int = 12
    approvedPrincipal: Optional[Decimal] = None
    approvedRate: Optional[Decimal] = None
    outstandingBalance: Optional[Decimal] = None
    collectionsOfficer: Optional[str] = None
    assignedCollectionsBranch: Optional[str] = None
    createdAt: datetime = strawberry.field(default_factory=datetime.now)
    updatedAt: datetime = strawberry.field(default_factory=datetime.now)
    disbursedAt: Optional[datetime] = None
    
    @strawberry.field
    async def borrowerName(self) -> str:
        session_factory = get_async_session_local()
        async with session_factory() as session:
            # Check if customerId is numeric (PG ID)
            if str(self.customerId).isdigit():
                stmt = select(Customer).where(Customer.id == int(str(self.customerId)))
                result = await session.execute(stmt)
                customer = result.scalar_one_or_none()
                return customer.display_name if customer else f"Customer {self.customerId}"
            else:
                # If it's a string (e.g. Mongo ID), we can't easily find it in PG without a mapping column
                # For now, return a placeholder or just the ID
                return f"Customer {self.customerId}"

    @strawberry.field
    async def productName(self) -> str:
        if not self.productId:
            return "N/A"
        session_factory = get_async_session_local()
        async with session_factory() as session:
            stmt = select(PGLoanProduct).where(PGLoanProduct.id == self.productId)
            result = await session.execute(stmt)
            product = result.scalar_one_or_none()
            return product.name if product else "Unknown Product"

    @strawberry.field
    def referenceNo(self) -> str:
        return f"LOAN-{self.id}"

    @strawberry.field
    def startDate(self) -> datetime:
        return self.disbursedAt or self.createdAt

    @strawberry.field
    def endDate(self) -> Optional[datetime]:
        from dateutil.relativedelta import relativedelta
        start = self.disbursedAt or self.createdAt
        if not start:
            return None
        return start + relativedelta(months=int(self.termMonths))


@strawberry.input
class LoanInput:
    customerId: str
    productId: int
    principal: Decimal
    termMonths: int
    disbursementMethod: Optional[str] = None


@strawberry.type
class LoanResponse:
    success: bool
    message: str
    loan: Optional[LoanNode] = None


@strawberry.type
class LoanConnection:
    loans: List[LoanNode]
    total: int


@strawberry.type
@strawberry.type
class LoanConnection:
    loans: List[LoanNode]
    total: int


@strawberry.type
class LoanTransactionNode:
    id: str
    loanId: str
    amount: Decimal
    transactionType: str
    description: Optional[str] = None
    status: str = "success"
    reference: Optional[str] = None
    createdAt: datetime
    
    # Ported from master
    commercialBank: Optional[str] = None
    servicingBranch: Optional[str] = None
    region: Optional[str] = None
    loanProductId: Optional[str] = None
    debitAccount: Optional[str] = None
    creditAccount: Optional[str] = None
    disbursementMethod: Optional[str] = None
    disbursementStatus: Optional[str] = "pending"
    chequeNumber: Optional[str] = None
    beneficiaryBank: Optional[str] = None
    beneficiaryAccount: Optional[str] = None
    approvedBy: Optional[str] = None
    processedBy: Optional[str] = None
    createdBy: Optional[str] = None
    updatedBy: Optional[str] = None
    borrowerName: Optional[str] = "N/A"
    updatedAt: datetime = strawberry.field(default_factory=datetime.now)

    @strawberry.field
    async def loanProduct(self) -> Optional[LoanProductNode]:
        if not self.loanProductId:
            return None
        session_factory = get_async_session_local()
        async with session_factory() as session:
            try:
                # loanProductId might be numeric or legacy string
                if str(self.loanProductId).isdigit():
                    stmt = select(PGLoanProduct).filter(PGLoanProduct.id == int(self.loanProductId))
                    result = await session.execute(stmt)
                    lp = result.scalar_one_or_none()
                    if lp:
                        return LoanProductNode(
                            id=str(lp.id),
                            productCode=lp.product_code,
                            name=lp.name,
                            interestRate=lp.interest_rate,
                            penaltyRate=lp.penalty_rate,
                            amortizationType=lp.amortization_type,
                            repaymentFrequency=lp.repayment_frequency,
                        )
            except:
                pass
        return None

    @strawberry.field
    async def borrower(self) -> Optional[CustomerNode]:
        session_factory = get_async_session_local()
        async with session_factory() as session:
            try:
                # First get the loan to get the customer_id
                loan_stmt = select(LoanApplication).filter(LoanApplication.id == int(self.loanId))
                loan_res = await session.execute(loan_stmt)
                loan = loan_res.scalar_one_or_none()
                if loan:
                    # Now get the customer (customer_id in LoanApplication is a string currently, might need casting)
                    cust_id_str = str(loan.customer_id)
                    if cust_id_str.isdigit():
                        cust_stmt = select(Customer).filter(Customer.id == int(cust_id_str))
                        cust_res = await session.execute(cust_stmt)
                        customer = cust_res.scalar_one_or_none()
                        if customer:
                            return CustomerNode(
                                id=str(customer.id),
                                displayName=customer.display_name,
                                customerType=customer.customer_type,
                                branchCode=customer.branch_code,
                                isActive=customer.is_active,
                                createdAt=customer.created_at,
                            )
            except:
                pass
        return None


@strawberry.input
class LoanTransactionCreateInput:
    loanId: str
    transactionType: str
    amount: Decimal
    description: Optional[str] = None
    receiptNumber: Optional[str] = None
    
    # Ported from master
    commercialBank: Optional[str] = None
    servicingBranch: Optional[str] = None
    region: Optional[str] = None
    loanProductId: Optional[str] = None
    debitAccount: Optional[str] = None
    creditAccount: Optional[str] = None
    disbursementMethod: Optional[str] = None
    disbursementStatus: Optional[str] = "pending"
    chequeNumber: Optional[str] = None
    beneficiaryBank: Optional[str] = None
    beneficiaryAccount: Optional[str] = None
    approvedBy: Optional[str] = None
    borrowerName: Optional[str] = None


@strawberry.input
class LoanTransactionUpdateInput:
    transactionType: Optional[str] = None
    amount: Optional[Decimal] = None
    description: Optional[str] = None
    receiptNumber: Optional[str] = None
    
    # Ported from master
    commercialBank: Optional[str] = None
    servicingBranch: Optional[str] = None
    region: Optional[str] = None
    loanProductId: Optional[str] = None
    debitAccount: Optional[str] = None
    creditAccount: Optional[str] = None
    disbursementMethod: Optional[str] = None
    disbursementStatus: Optional[str] = None
    chequeNumber: Optional[str] = None
    beneficiaryBank: Optional[str] = None
    beneficiaryAccount: Optional[str] = None
    approvedBy: Optional[str] = None
    borrowerName: Optional[str] = None


@strawberry.type
class LoanTransactionResponse:
    success: bool
    message: str
    transaction: Optional[LoanTransactionNode] = None


@strawberry.type
class GLAccountNode:
    id: str
    code: str
    name: str
    type: str  # asset, liability, equity, income, expense
    balance: Decimal
    createdAt: datetime


@strawberry.type
class JournalLineNode:
    id: str
    accountCode: str
    accountName: Optional[str]
    debit: Decimal
    credit: Decimal
    description: Optional[str]


@strawberry.type
class JournalEntryNode:
    id: strawberry.ID
    referenceNo: str
    description: Optional[str]
    timestamp: datetime
    createdBy: Optional[str]
    lines: List[JournalLineNode]


@strawberry.type
class JournalEntriesResponse:
    success: bool
    message: str
    entries: List[JournalEntryNode]
    total: int


@strawberry.type
class GLTransactionNode:
    id: str
    accountId: str
    amount: Decimal
    accountType: str  # debit or credit
    reference: str
    createdAt: datetime


@strawberry.type
class CollectionBucket:
    label: str
    loanCount: int
    totalOutstanding: Decimal


@strawberry.type
class CollectionsDashboardNode:
    totalLoans: int
    totalOutstanding: Decimal
    buckets: List[CollectionBucket]
    totalCollections: Decimal = Decimal("0.00")
    pendingCollections: Decimal = Decimal("0.00")
    overdueCollections: Decimal = Decimal("0.00")
    collectedThisMonth: Decimal = Decimal("0.00")


@strawberry.type
class CollectionNode:
    id: str
    customerId: str
    borrowerName: Optional[str] = None
    amount: Decimal
    status: str
    dueDate: date
    daysPastDue: int = 0
    agingBucket: str = "current"
    collectionDate: Optional[date] = None
    collectedBy: Optional[str] = None
    referenceNumber: Optional[str] = None
    collectionType: Optional[str] = None
    notes: Optional[str] = None
    createdAt: datetime


@strawberry.type
class CollectionConnection:
    collections: List[CollectionNode]
    total: int


@strawberry.type
class AuditLogNode:
    id: str
    userId: str
    action: str
    resource: str
    timestamp: datetime


@strawberry.type
class AmortizationScheduleRow:
    installmentNumber: int
    dueDate: date
    principalDue: Decimal
    interestDue: Decimal
    penaltyDue: Decimal
    principalPaid: Decimal
    interestPaid: Decimal
    penaltyPaid: Decimal
    status: str
    totalDue: Decimal
    totalPaid: Decimal
    paymentDate: Optional[date] = None


@strawberry.type
class LoanAmortizationNode:
    id: str
    loanId: str
    principal: Decimal
    interestRate: Decimal
    termMonths: int
    repaymentFrequency: Optional[str] = None
    rows: List[AmortizationScheduleRow]


@strawberry.type
class LoanProductNode:
    id: str
    name: str
    productCode: str
    description: Optional[str]
    interestRate: Decimal
    termMonths: int
    amortizationType: Optional[str] = None
    repaymentFrequency: Optional[str] = None
    minLoanAmount: Decimal = Decimal("1000.00")
    maxLoanAmount: Decimal = Decimal("1000000.00")
    createdAt: datetime = strawberry.field(default_factory=datetime.now)


@strawberry.type
class FinancialMetricsNode:
    averageCollectionDays: float = 0.0
    collectionEfficiency: float = 100.0
    totalOutstanding: Decimal = Decimal("0.00")
    totalCollected: Decimal = Decimal("0.00")
    totalNPL: Decimal = Decimal("0.00")
    nplRatio: float = 0.0
    totalLLR: Decimal = Decimal("0.00")
    llrRatio: float = 0.0
    provisionedAmount: Decimal = Decimal("0.00")


@strawberry.type
class FinancialStatementNode:
    revenue: Decimal = Decimal("0.00")
    expenses: Decimal = Decimal("0.00")
    profit: Decimal = Decimal("0.00")
    assets: Decimal = Decimal("0.00")
    liabilities: Decimal = Decimal("0.00")
    equity: Decimal = Decimal("0.00")
    createdAt: datetime = strawberry.field(default_factory=datetime.now)


@strawberry.type
@strawberry.type
class BranchNode:
    id: int
    code: str
    name: str
    address: Optional[str] = None
    city: Optional[str] = None
    contactNumber: Optional[str] = None
    isActive: bool = True
    createdAt: datetime = strawberry.field(default_factory=datetime.now)
    updatedAt: datetime = strawberry.field(default_factory=datetime.now)


@strawberry.type
class Query:
    @strawberry.field
    async def users(self, skip: int = 0, limit: int = 100) -> List[UserNode]:
        session_factory = get_async_session_local()
        async with session_factory() as session:
            result = await session.execute(select(User).offset(skip).limit(limit))
            users = result.scalars().all()
            return [
                UserNode(
                    id=str(u.uuid if u.uuid is not None else u.id),
                    email=u.email,
                    username=u.username,
                    fullName=u.full_name,
                    isActive=u.is_active,
                    role=u.role,
                    branchId=u.branch_id,
                    branchCode=u.branch_code,
                )
                for u in users
            ]

    @strawberry.field
    async def branches(self) -> List[BranchNode]:
        session_factory = get_async_session_local()
        async with session_factory() as session:
            stmt = select(Branch)
            result = await session.execute(stmt)
            branches = result.scalars().all()
            return [
                BranchNode(
                    id=b.id,
                    code=b.code,
                    name=b.name,
                    address=b.address,
                    city=b.city,
                    contactNumber=b.contact_number,
                    isActive=b.is_active,
                    createdAt=b.created_at,
                    updatedAt=b.updated_at,
                )
                for b in branches
            ]

    @strawberry.field
    async def health(self) -> Health:
        return Health(status="ok", message="Lending MVP GraphQL API is running")

    @strawberry.field
    async def users_by_role(
        self,
        info: Info,
        role: str,
    ) -> List[UserNode]:
        from .auth.rbac import require_any_staff
        from .database.pg_core_models import User

        require_any_staff(info)
        session_factory = get_async_session_local()
        async with session_factory() as session:
            result = await session.execute(
                select(User).where(User.role == role, User.is_active == True)
            )
            users = result.scalars().all()
            return [
                UserNode(
                    id=strawberry.ID(str(u.id)),
                    email=u.email or "",
                    username=u.username or "",
                    fullName=u.full_name or "",
                    isActive=u.is_active,
                    role=u.role,
                    branchId=u.branch_id,
                    branchCode=u.branch_code,
                )
                for u in users
            ]

    @strawberry.field
    async def branches(self) -> List[BranchNode]:
        session_factory = get_async_session_local()
        async with session_factory() as session:
            stmt = select(Branch)
            result = await session.execute(stmt)
            branches = result.scalars().all()
            return [
                BranchNode(
                    id=b.id,
                    code=b.code,
                    name=b.name,
                    address=b.address,
                    city=b.city,
                    contactNumber=b.contact_number,
                    isActive=b.is_active,
                    createdAt=b.created_at,
                    updatedAt=b.updated_at,
                )
                for b in branches
            ]

    @strawberry.field
    async def branches(self) -> List[BranchNode]:
        session_factory = get_async_session_local()
        async with session_factory() as session:
            stmt = select(Branch)
            result = await session.execute(stmt)
            branches = result.scalars().all()
            return [
                BranchNode(
                    id=b.id,
                    code=b.code,
                    name=b.name,
                    address=b.address,
                    city=b.city,
                    contactNumber=b.contact_number,
                    isActive=b.is_active,
                    createdAt=b.created_at,
                    updatedAt=b.updated_at,
                )
                for b in branches
            ]
        return Health(status="ok", message="Lending MVP GraphQL API is running")

    @strawberry.field
    async def customers(
        self, skip: int = 0, limit: int = 100, searchTerm: Optional[str] = None
    ) -> CustomerConnection:
        session_factory = get_async_session_local()
        async with session_factory() as session:
            query = select(Customer).offset(skip).limit(limit)
            if searchTerm:
                query = query.where(Customer.display_name.ilike(f"%{searchTerm}%"))

            result = await session.execute(query)
            customers = result.scalars().all()

            customer_count = await session.execute(
                select(func.count()).select_from(Customer)
            )
            total = customer_count.scalar()

            return CustomerConnection(
                customers=[
                    CustomerNode(
                        id=str(c.id),
                        displayName=c.display_name,
                        customerType=c.customer_type,
                        branchCode=c.branch_code,
                        isActive=c.is_active,
                        firstName=c.first_name,
                        lastName=c.last_name,
                        emailAddress=c.email_address,
                        mobileNumber=c.mobile_number,
                        createdAt=c.created_at,
                    )
                    for c in customers
                ],
                total=total,
            )

    @strawberry.field
    async def customer(self, id: strawberry.ID) -> Optional[CustomerNode]:
        session_factory = get_async_session_local()
        async with session_factory() as session:
            result = await session.execute(
                select(Customer).where(Customer.id == str(id))
            )
            c = result.scalar_one_or_none()
            if not c:
                return None
            return CustomerNode(
                id=str(c.id),
                displayName=c.display_name,
                customerType=c.customer_type,
                branchCode=c.branch_code,
                isActive=c.is_active,
                firstName=c.first_name,
                lastName=c.last_name,
                emailAddress=c.email_address,
                mobileNumber=c.mobile_number,
                createdAt=c.created_at,
            )

    @strawberry.field
    async def loans(
        self,
        skip: int = 0,
        limit: int = 100,
        customerId: Optional[str] = None,
        searchTerm: Optional[str] = None,
    ) -> LoanConnection:
        session_factory = get_async_session_local()
        async with session_factory() as session:
            stmt = select(LoanApplication)
            if customerId:
                stmt = stmt.where(LoanApplication.customer_id == customerId)
            # Remove non-existent borrower_name filter that caused crashes
            # if searchTerm:
            #     stmt = stmt.where(
            #         LoanApplication.borrower_name.ilike(f"%{searchTerm}%")
            #     )

            result = await session.execute(stmt.offset(skip).limit(limit))
            loan_list = result.scalars().all()

            loan_count = await session.execute(
                select(func.count()).select_from(LoanApplication)
            )
            total = loan_count.scalar()

            return LoanConnection(
                loans=[
                    LoanNode(
                        id=str(l.id),
                        principal=l.principal,
                        status=l.status,
                        customerId=str(l.customer_id),
                        productId=l.product_id,
                        termMonths=l.term_months,
                        approvedPrincipal=l.approved_principal,
                        approvedRate=l.approved_rate,
                        outstandingBalance=l.outstanding_balance,
                        collectionsOfficer=l.collections_officer,
                        assignedCollectionsBranch=l.assigned_collections_branch,
                        createdAt=l.created_at,
                        updatedAt=l.updated_at,
                        disbursedAt=l.disbursed_at,
                    )
                    for l in loan_list
                ],
                total=total,
            )

    @strawberry.field
    async def loan(self, id: strawberry.ID) -> Optional[LoanNode]:
        session_factory = get_async_session_local()
        async with session_factory() as session:
            result = await session.execute(
                select(LoanApplication).where(LoanApplication.id == int(id))
            )
            l = result.scalar_one_or_none()
            if not l:
                return None
            return LoanNode(
                id=str(l.id),
                principal=l.principal,
                status=l.status,
                customerId=str(l.customer_id),
                productId=l.product_id,
                termMonths=l.term_months,
                approvedPrincipal=l.approved_principal,
                approvedRate=l.approved_rate,
                outstandingBalance=l.outstanding_balance,
                createdAt=l.created_at,
                updatedAt=l.updated_at,
                disbursedAt=l.disbursed_at,
            )

    @strawberry.field
    async def loanTransactions(
        self, 
        loanId: Optional[strawberry.ID] = None,
        searchTerm: Optional[str] = None,
        transactionType: Optional[str] = None,
        skip: int = 0,
        limit: int = 100
    ) -> List[LoanTransactionNode]:
        session_factory = get_async_session_local()
        async with session_factory() as session:
            stmt = select(LoanTransaction)
            if loanId:
                stmt = stmt.where(LoanTransaction.loan_id == int(loanId))
            if searchTerm:
                stmt = stmt.where(LoanTransaction.description.ilike(f"%{searchTerm}%"))
            if transactionType:
                stmt = stmt.where(LoanTransaction.type == transactionType)
            
            stmt = stmt.offset(skip).limit(limit).order_by(LoanTransaction.timestamp.desc())
            result = await session.execute(stmt)
            txs = result.scalars().all()
            return [
                LoanTransactionNode(
                    id=str(t.id),
                    loanId=str(t.loan_id),
                    amount=t.amount,
                    transactionType=t.type,
                    description=t.description,
                    reference=t.receipt_number,
                    createdAt=t.timestamp,
                    # Ported fields
                    commercialBank=t.commercial_bank,
                    servicingBranch=t.servicing_branch,
                    region=t.region,
                    loanProductId=t.loan_product_id,
                    debitAccount=t.debit_account,
                    creditAccount=t.credit_account,
                    disbursementMethod=t.disbursement_method,
                    disbursementStatus=t.disbursement_status,
                    chequeNumber=t.cheque_number,
                    beneficiaryBank=t.beneficiary_bank,
                    beneficiaryAccount=t.beneficiary_account,
                    approvedBy=t.approved_by,
                    processedBy=t.processed_by,
                    createdBy=t.created_by,
                    updatedBy=t.updated_by,
                    borrowerName=t.borrower_name,
                    updatedAt=t.updated_at,
                )
                for t in txs
            ]

    @strawberry.field
    async def savingsAccounts(
        self,
        skip: int = 0,
        limit: int = 100,
        customerId: Optional[str] = None,
        searchTerm: Optional[str] = None,
    ) -> SavingsAccountConnection:
        session_factory = get_async_session_local()
        async with session_factory() as session:
            stmt = select(SavingsAccount)
            if customerId:
                stmt = stmt.where(SavingsAccount.customer_id == int(customerId))
            if searchTerm:
                stmt = stmt.where(
                    SavingsAccount.account_number.ilike(f"%{searchTerm}%")
                )

            # Get total count before pagination
            count_stmt = select(func.count()).select_from(stmt.subquery())
            total_result = await session.execute(count_stmt)
            total = total_result.scalar() or 0

            result = await session.execute(stmt.offset(skip).limit(limit))
            accounts = result.scalars().all()

            return SavingsAccountConnection(
                accounts=[
                    SavingsAccountNode(
                        id=str(a.id),
                        accountNumber=a.account_number,
                        balance=Decimal(str(a.balance)),
                        customerId=str(a.customer_id),
                        accountType=a.account_type,
                        status=a.status,
                        openedAt=a.opened_at,
                    )
                    for a in accounts
                ],
                total=total,
            )

    @strawberry.field
    async def savingsTransactions(
        self, accountId: strawberry.ID
    ) -> List[SavingsTransactionNode]:
        session_factory = get_async_session_local()
        async with session_factory() as session:
            result = await session.execute(
                select(SavingsTransaction).where(
                    SavingsTransaction.account_id == int(accountId)
                )
            )
            transactions = result.scalars().all()
            return [
                SavingsTransactionNode(
                    id=str(t.id),
                    accountId=str(t.account_id),
                    amount=t.amount,
                    accountType=t.transaction_type,
                    reference=t.reference,
                    description=t.description,
                    balanceBefore=t.balance_before,
                    balanceAfter=t.balance_after,
                    createdAt=t.created_at,
                )
                for t in transactions
            ]

    @strawberry.field
    async def customerActivities(self, customerId: str) -> List[CustomerActivityNode]:
        session_factory = get_async_session_local()
        async with session_factory() as session:
            result = await session.execute(
                select(CustomerActivity).where(
                    CustomerActivity.customer_id == customerId
                )
            )
            activities = result.scalars().all()
            return [
                CustomerActivityNode(
                    id=str(a.id),
                    customerId=str(a.customer_id),
                    activityType=a.action,
                    description=a.detail,
                    timestamp=a.created_at,
                    createdBy=a.actor_username or "system",
                )
                for a in activities
            ]

    @strawberry.field
    async def collections(
        self,
        first: int = 50,
        offset: int = 0,
        search: Optional[str] = None,
        status: Optional[str] = None,
        dateFrom: Optional[date] = None,
        dateTo: Optional[date] = None,
    ) -> CollectionConnection:
        session_factory = get_async_session_local()
        async with session_factory() as session:
            query = select(Collection)
            count_query = select(func.count(Collection.id))

            if status:
                query = query.where(Collection.status == status)
                count_query = count_query.where(Collection.status == status)
            if dateFrom:
                query = query.where(Collection.due_date >= dateFrom)
                count_query = count_query.where(Collection.due_date >= dateFrom)
            if dateTo:
                query = query.where(Collection.due_date <= dateTo)
                count_query = count_query.where(Collection.due_date <= dateTo)

            total_result = await session.execute(count_query)
            total = total_result.scalar() or 0

            query = query.order_by(Collection.due_date.desc()).offset(offset).limit(first)
            result = await session.execute(query)
            collections = result.scalars().all()

            customer_ids = list({str(c.customer_id) for c in collections})
            customer_names: dict[str, str] = {}
            if customer_ids:
                try:
                    int_ids = [int(cid) for cid in customer_ids if cid.isdigit()]
                    if int_ids:
                        cust_result = await session.execute(
                            select(Customer).where(Customer.id.in_(int_ids))
                        )
                        customer_names = {str(c.id): c.display_name for c in cust_result.scalars().all()}
                except (ValueError, TypeError):
                    pass

            today = date.today()
            nodes = []
            for c in collections:
                dpd = max(0, (today - c.due_date.date()).days) if c.due_date else 0
                if dpd <= 0:
                    bucket = "current"
                elif dpd <= 30:
                    bucket = "1-30_days"
                elif dpd <= 60:
                    bucket = "31-60_days"
                elif dpd <= 90:
                    bucket = "61-90_days"
                else:
                    bucket = "90+_days"

                nodes.append(
                    CollectionNode(
                        id=str(c.id),
                        customerId=str(c.customer_id),
                        borrowerName=customer_names.get(str(c.customer_id)),
                        amount=c.amount,
                        status=c.status,
                        dueDate=c.due_date,
                        daysPastDue=dpd,
                        agingBucket=bucket,
                        collectionDate=c.collection_date,
                        collectedBy=c.collected_by,
                        referenceNumber=c.reference_number,
                        collectionType=c.collection_type,
                        notes=c.notes,
                        createdAt=c.created_at,
                    )
                )

            return CollectionConnection(collections=nodes, total=total)

    @strawberry.field
    async def collectionDue(self) -> List[CollectionNode]:
        session_factory = get_async_session_local()
        async with session_factory() as session:
            today = date.today()
            result = await session.execute(
                select(Collection)
                .where(Collection.due_date <= today)
                .order_by(Collection.due_date.asc())
            )
            collections = result.scalars().all()

            customer_ids = list({str(c.customer_id) for c in collections})
            customer_names: dict[str, str] = {}
            if customer_ids:
                try:
                    int_ids = [int(cid) for cid in customer_ids if cid.isdigit()]
                    if int_ids:
                        cust_result = await session.execute(
                            select(Customer).where(Customer.id.in_(int_ids))
                        )
                        customer_names = {str(c.id): c.display_name for c in cust_result.scalars().all()}
                except (ValueError, TypeError):
                    pass

            today_date = date.today()
            nodes = []
            for c in collections:
                dpd = max(0, (today_date - c.due_date.date()).days) if c.due_date else 0
                if dpd <= 0:
                    bucket = "current"
                elif dpd <= 30:
                    bucket = "1-30_days"
                elif dpd <= 60:
                    bucket = "31-60_days"
                elif dpd <= 90:
                    bucket = "61-90_days"
                else:
                    bucket = "90+_days"

                nodes.append(
                    CollectionNode(
                        id=str(c.id),
                        customerId=str(c.customer_id),
                        borrowerName=customer_names.get(str(c.customer_id)),
                        amount=c.amount,
                        status=c.status,
                        dueDate=c.due_date,
                        daysPastDue=dpd,
                        agingBucket=bucket,
                        collectionDate=c.collection_date,
                        collectedBy=c.collected_by,
                        referenceNumber=c.reference_number,
                        collectionType=c.collection_type,
                        notes=c.notes,
                        createdAt=c.created_at,
                    )
                )

            return nodes

    @strawberry.field
    async def glAccounts(self) -> List[GLAccountNode]:
        session_factory = get_async_session_local()
        async with session_factory() as session:
            stmt = (
                select(
                    GLAccount,
                    func.sum(JournalLine.debit).label("total_debit"),
                    func.sum(JournalLine.credit).label("total_credit"),
                )
                .outerjoin(JournalLine, GLAccount.code == JournalLine.account_code)
                .group_by(GLAccount.id)
            )
            result = await session.execute(stmt)
            rows = result.all()
            nodes = []
            for row in rows:
                acc = row[0]
                total_debit = row[1] or Decimal("0.00")
                total_credit = row[2] or Decimal("0.00")
                balance = (
                    (total_debit - total_credit)
                    if acc.type.lower() in ["asset", "expense"]
                    else (total_credit - total_debit)
                )
                nodes.append(
                    GLAccountNode(
                        id=str(acc.id),
                        code=acc.code,
                        name=acc.name,
                        type=acc.type,
                        balance=balance,
                        createdAt=acc.created_at,
                    )
                )
            return nodes

    @strawberry.field
    async def collectionsDashboard(self) -> CollectionsDashboardNode:
        session_factory = get_async_session_local()
        today = date.today()
        first_day_of_month = today.replace(day=1)
        async with session_factory() as session:
            # 1. Dashboard Metrics
            total_collections = (
                await session.execute(
                    select(
                        func.sum(
                            AmortizationSchedule.principal_paid
                            + AmortizationSchedule.interest_paid
                        )
                    )
                )
            ).scalar() or Decimal("0.00")
            pending_collections = (
                await session.execute(
                    select(
                        func.sum(
                            AmortizationSchedule.principal_due
                            + AmortizationSchedule.interest_due
                            - AmortizationSchedule.principal_paid
                            - AmortizationSchedule.interest_paid
                        )
                    ).where(AmortizationSchedule.due_date >= today)
                )
            ).scalar() or Decimal("0.00")
            overdue_collections = (
                await session.execute(
                    select(
                        func.sum(
                            AmortizationSchedule.principal_due
                            + AmortizationSchedule.interest_due
                            - AmortizationSchedule.principal_paid
                            - AmortizationSchedule.interest_paid
                        )
                    ).where(AmortizationSchedule.due_date < today)
                )
            ).scalar() or Decimal("0.00")
            collected_this_month = (
                await session.execute(
                    select(
                        func.sum(
                            AmortizationSchedule.principal_paid
                            + AmortizationSchedule.interest_paid
                        )
                    ).where(AmortizationSchedule.due_date >= first_day_of_month)
                )
            ).scalar() or Decimal("0.00")

            # 2. Aging Buckets (Simplified logic based on overdue installments)
            # Fetch all unpaid installments to bucketize
            stmt = select(AmortizationSchedule).where(
                AmortizationSchedule.status != "paid"
            )
            unpaid = (await session.execute(stmt)).scalars().all()

            buckets = {
                "Current": {"count": 0, "amount": Decimal("0.00")},
                "1-30 DPD": {"count": 0, "amount": Decimal("0.00")},
                "31-60 DPD": {"count": 0, "amount": Decimal("0.00")},
                "61-90 DPD": {"count": 0, "amount": Decimal("0.00")},
                "90+ DPD": {"count": 0, "amount": Decimal("0.00")},
            }

            loan_ids_counted = set()
            total_loans_count = (
                await session.execute(select(func.count(LoanApplication.id)))
            ).scalar() or 0
            total_outstanding_stmt = select(
                func.sum(
                    AmortizationSchedule.principal_due
                    + AmortizationSchedule.interest_due
                    - AmortizationSchedule.principal_paid
                    - AmortizationSchedule.interest_paid
                )
            )
            total_outstanding = (
                await session.execute(total_outstanding_stmt)
            ).scalar() or Decimal("0.00")

            for item in unpaid:
                days_past_due = (today - item.due_date).days
                amount_due = (
                    item.principal_due
                    + item.interest_due
                    - item.principal_paid
                    - item.interest_paid
                )

                label = "Current"
                if days_past_due > 90:
                    label = "90+ DPD"
                elif days_past_due > 60:
                    label = "61-90 DPD"
                elif days_past_due > 30:
                    label = "31-60 DPD"
                elif days_past_due > 0:
                    label = "1-30 DPD"

                buckets[label]["amount"] += amount_due
                buckets[label]["count"] += (
                    1  # In a real system this would be per loan, but using per installment for simplicity
                )

            bucket_nodes = [
                CollectionBucket(
                    label=k, loanCount=v["count"], totalOutstanding=v["amount"]
                )
                for k, v in buckets.items()
            ]

            return CollectionsDashboardNode(
                totalLoans=total_loans_count,
                totalOutstanding=total_outstanding,
                buckets=bucket_nodes,
                totalCollections=total_collections,
                pendingCollections=pending_collections,
                overdueCollections=overdue_collections,
                collectedThisMonth=collected_this_month,
            )

    @strawberry.field
    async def auditLogs(self, limit: int = 50, offset: int = 0) -> List[AuditLogNode]:
        session_factory = get_async_session_local()
        async with session_factory() as session:
            rows = (
                await session.execute(
                    select(AuditLog).order_by(AuditLog.created_at.desc()).offset(offset).limit(limit)
                )
            ).scalars().all()
            return [
                AuditLogNode(
                    id=str(r.id),
                    userId=str(r.user_id) if r.user_id else "system",
                    action=r.action,
                    resource=f"{r.entity}/{r.entity_id}",
                    timestamp=r.created_at,
                )
                for r in rows
            ]

    @strawberry.field
    async def loanAmortization(
        self, loanId: strawberry.ID
    ) -> Optional[LoanAmortizationNode]:
        session_factory = get_async_session_local()
        async with session_factory() as session:
            l = (
                await session.execute(
                    select(LoanApplication).where(LoanApplication.id == int(loanId))
                )
            ).scalar_one_or_none()
            if not l:
                return None
            sched_items = (
                (
                    await session.execute(
                        select(AmortizationSchedule)
                        .where(AmortizationSchedule.loan_id == l.id)
                        .order_by(AmortizationSchedule.installment_number)
                    )
                )
                .scalars()
                .all()
            )
            # Fetch product to get repayment_frequency
            loan_product = None
            repayment_frequency = None
            if l.product_id:
                prod_result = await session.execute(
                    select(PGLoanProduct).where(PGLoanProduct.id == l.product_id)
                )
                loan_product = prod_result.scalar_one_or_none()
                if loan_product:
                    repayment_frequency = loan_product.repayment_frequency
            rows = []
            for item in sched_items:
                rows.append(
                    AmortizationScheduleRow(
                        installmentNumber=item.installment_number,
                        dueDate=item.due_date,
                        principalDue=item.principal_due,
                        interestDue=item.interest_due,
                        penaltyDue=item.penalty_due,
                        principalPaid=item.principal_paid,
                        interestPaid=item.interest_paid,
                        penaltyPaid=item.penalty_paid,
                        status=item.status,
                        paymentDate=item.payment_date,
                        totalDue=item.principal_due + item.interest_due + item.penalty_due,
                        totalPaid=item.principal_paid + item.interest_paid + item.penalty_paid,
                    )
                )
            return LoanAmortizationNode(
                id=str(l.id),
                loanId=str(l.id),
                principal=l.principal,
                interestRate=l.approved_rate or Decimal("12.00"),
                termMonths=l.term_months,
                repaymentFrequency=repayment_frequency,
                rows=rows,
            )

    @strawberry.field
    async def loanProducts(self) -> List[LoanProductNode]:
        session_factory = get_async_session_local()
        async with session_factory() as session:
            prods = (await session.execute(select(PGLoanProduct))).scalars().all()
            return [
                LoanProductNode(
                    id=str(p.id),
                    name=p.name,
                    productCode=p.product_code,
                    description=p.description,
                    interestRate=p.interest_rate,
                    termMonths=12,
                    amortizationType=p.amortization_type,
                    repaymentFrequency=p.repayment_frequency,
                    createdAt=p.created_at,
                )
                for p in prods
            ]

    @strawberry.field
    async def parMetrics(self) -> FinancialMetricsNode:
        session_factory = get_async_session_local()
        async with session_factory() as session:
            total = await session.scalar(select(func.count(LoanApplication.id)))
            overdue = await session.scalar(
                select(func.count(LoanApplication.id)).where(
                    LoanApplication.status == "active",
                    LoanApplication.outstanding_balance > 0,
                )
            )
            overdue_count = overdue or 0
            total_count = total or 1
            return FinancialMetricsNode(
                totalOutstanding=Decimal("0.00"),
                totalCollected=Decimal("0.00"),
                totalNPL=Decimal("0.00"),
                nplRatio=round(overdue_count / total_count * 100, 2) if total_count else 0.0,
                totalLLR=Decimal("0.00"),
                llrRatio=0.0,
                provisionedAmount=Decimal("0.00"),
            )

    @strawberry.field
    async def nplMetrics(self) -> FinancialMetricsNode:
        session_factory = get_async_session_local()
        async with session_factory() as session:
            total = await session.scalar(select(func.count(LoanApplication.id)))
            npl = await session.scalar(
                select(func.count(LoanApplication.id)).where(
                    LoanApplication.is_npl == True,
                )
            )
            npl_count = npl or 0
            total_count = total or 1
            return FinancialMetricsNode(
                totalNPL=Decimal("0.00"),
                nplRatio=round(npl_count / total_count * 100, 2) if total_count else 0.0,
                totalOutstanding=Decimal("0.00"),
                totalCollected=Decimal("0.00"),
                totalLLR=Decimal("0.00"),
                llrRatio=0.0,
                provisionedAmount=Decimal("0.00"),
            )

    @strawberry.field
    async def llrMetrics(self) -> FinancialMetricsNode:
        session_factory = get_async_session_local()
        async with session_factory() as session:
            total_portfolio = await session.scalar(
                select(func.coalesce(func.sum(LoanApplication.outstanding_balance), 0))
            )
            total = float(total_portfolio or 0)
            llr = round(total * 0.02, 2)  # 2% general provision
            return FinancialMetricsNode(
                totalOutstanding=Decimal(str(round(total, 2))),
                totalLLR=Decimal(str(llr)),
                llrRatio=2.0,
                provisionedAmount=Decimal(str(llr)),
                totalCollected=Decimal("0.00"),
                totalNPL=Decimal("0.00"),
                nplRatio=0.0,
            )

    @strawberry.field
    async def collections_due(
        self,
        info: Info,
        asOf: Optional[date] = None,
        branchCode: Optional[str] = None,
        collectionsOfficerId: Optional[str] = None,
        dueDateFrom: Optional[date] = None,
        dueDateTo: Optional[date] = None,
        limit: int = 500,
        offset: int = 0,
    ) -> CollectionsDueReportType:
        return await resolve_collections_due(info, asOf, branchCode, collectionsOfficerId, dueDateFrom, dueDateTo, limit, offset)

    @strawberry.field
    async def collections_due_summary(
        self,
        info: Info,
        asOf: Optional[date] = None,
        branchCode: Optional[str] = None,
    ) -> CollectionsDueSummaryType:
        return await resolve_collections_due_summary(info, asOf, branchCode)

    @strawberry.field
    async def aging_report(
        self,
        info: Info,
        asOf: Optional[date] = None,
        branchCode: Optional[str] = None,
    ) -> AgingReportType:
        return await resolve_aging_report(info, asOf, branchCode)

    @strawberry.field
    async def trialBalance(
        self,
        info: Info,
        asOf: Optional[date] = None,
    ) -> TrialBalanceReport:
        return await resolve_trial_balance(info, asOf)

    @strawberry.field
    async def incomeStatement(
        self,
        info: Info,
        year: int,
        month: int,
    ) -> IncomeStatementReport:
        return await resolve_income_statement(info, year, month)

    @strawberry.field
    async def balanceSheet(
        self,
        info: Info,
        asOf: Optional[date] = None,
    ) -> BalanceSheetReport:
        return await resolve_balance_sheet(info, asOf)

    @strawberry.field
    async def arAging(
        self,
        info: Info,
        asOf: Optional[date] = None,
        branchCode: Optional[str] = None,
    ) -> ARAgingReport:
        return await resolve_ar_aging(info, asOf, branchCode)

    @strawberry.field
    async def apAging(
        self,
        info: Info,
        asOf: Optional[date] = None,
        branchCode: Optional[str] = None,
    ) -> APAgingReport:
        return await resolve_ap_aging(info, asOf, branchCode)

    @strawberry.field
    async def delinquencyReport(
        self,
        info: Info,
        asOf: Optional[date] = None,
        branchCode: Optional[str] = None,
    ) -> DelinquencyReport:
        return await resolve_delinquency_report(info, asOf, branchCode)


    @strawberry.field
    async def unresolvedAlerts(self) -> List[Health]:
        return []  # Placeholder

    @strawberry.field
    async def complianceReports(self) -> List[Health]:
        return []  # Placeholder

    @strawberry.field
    async def journalEntries(
        self, skip: int = 0, limit: int = 50, referenceNo: Optional[str] = None, accountCode: Optional[str] = None
    ) -> JournalEntriesResponse:
        session_factory = get_async_session_local()
        async with session_factory() as session:
            query = select(JournalEntry)
            
            # Filter by account code if provided
            if accountCode:
                lines_subquery = (
                    select(JournalLine.entry_id)
                    .filter(JournalLine.account_code == accountCode)
                    .distinct()
                )
                query = query.filter(JournalEntry.id.in_(lines_subquery))
            
            if referenceNo:
                from sqlalchemy import or_
                query = query.filter(
                    or_(
                        JournalEntry.reference_no.ilike(f"%{referenceNo}%"),
                        JournalEntry.description.ilike(f"%{referenceNo}%")
                    )
                )

            count_result = await session.execute(query)
            all_entries = count_result.scalars().all()
            total = len(all_entries)

            result = await session.execute(
                query.order_by(JournalEntry.timestamp.desc()).offset(skip).limit(limit)
            )
            from sqlalchemy.orm import joinedload

            entries = []
            for entry in result.scalars().all():
                lines_result = await session.execute(
                    select(JournalLine)
                    .options(joinedload(JournalLine.account))
                    .filter(JournalLine.entry_id == entry.id)
                )
                lines = [
                    JournalLineNode(
                        id=str(l.id),
                        accountCode=l.account_code,
                        accountName=l.account.name if l.account else None,
                        debit=l.debit,
                        credit=l.credit,
                        description=l.description,
                    )
                    for l in lines_result.scalars().all()
                ]
                entries.append(
                    JournalEntryNode(
                        id=strawberry.ID(str(entry.id)),
                        referenceNo=entry.reference_no,
                        description=entry.description,
                        timestamp=entry.timestamp,
                        createdBy=entry.created_by,
                        lines=lines,
                    )
                )

            return JournalEntriesResponse(
                success=True, message="OK", entries=entries, total=total
            )

    @strawberry.field
    async def journalEntryByReference(
        self, reference: str
    ) -> Optional[JournalEntryNode]:
        session_factory = get_async_session_local()
        async with session_factory() as session:
            totals_stmt = (
                select(
                    JournalLine.entry_id,
                    func.sum(JournalLine.debit).label("total_debit"),
                    func.sum(JournalLine.credit).label("total_credit"),
                )
                .group_by(JournalLine.entry_id)
                .subquery()
            )
            stmt = (
                select(
                    JournalEntry, totals_stmt.c.total_debit, totals_stmt.c.total_credit
                )
                .outerjoin(totals_stmt, JournalEntry.id == totals_stmt.c.entry_id)
                .where(JournalEntry.reference_no == reference)
            )
            r = (await session.execute(stmt)).first()
            if not r:
                return None
            return JournalEntryNode(
                id=str(r[0].id),
                date=r[0].timestamp,
                description=r[0].description,
                reference=r[0].reference_no,
                debit=r[1] or Decimal("0.00"),
                credit=r[2] or Decimal("0.00"),
                createdAt=r[0].timestamp,
            )

    @strawberry.field
    async def glAccountTransactions(
        self, accountId: strawberry.ID
    ) -> List[GLTransactionNode]:
        session_factory = get_async_session_local()
        async with session_factory() as session:
            acc = (
                await session.execute(
                    select(GLAccount).where(GLAccount.id == int(accountId))
                )
            ).scalar_one_or_none()
            if not acc:
                return []
            rows = (
                await session.execute(
                    select(JournalLine, JournalEntry)
                    .join(JournalEntry)
                    .where(JournalLine.account_code == acc.code)
                    .order_by(JournalEntry.timestamp.desc())
                )
            ).all()
            return [
                GLTransactionNode(
                    id=str(l.id),
                    accountId=str(acc.id),
                    amount=l.debit if l.debit > 0 else l.credit,
                    type="debit" if l.debit > 0 else "credit",
                    reference=e.reference_no,
                    createdAt=e.timestamp,
                )
                for l, e in rows
            ]

    @strawberry.field
    async def dashboardStats(self) -> DashboardStats:
        session_factory = get_async_session_local()
        async with session_factory() as session:
            customer_count = (
                await session.execute(select(func.count(Customer.id)))
            ).scalar() or 0
            loan_count = (
                await session.execute(select(func.count(LoanApplication.id)))
            ).scalar() or 0
            active_count = (
                await session.execute(
                    select(func.count(LoanApplication.id)).where(LoanApplication.status == "active")
                )
            ).scalar() or 0
            active_savings_count = (
                await session.execute(
                    select(func.count(SavingsAccount.id)).where(SavingsAccount.status == "active")
                )
            ).scalar() or 0
            portfolio = (
                await session.execute(
                    select(func.coalesce(func.sum(LoanApplication.approved_principal), 0))
                    .where(LoanApplication.status == "active")
                )
            ).scalar() or Decimal("0.00")
            outstanding = (
                await session.execute(
                    select(func.coalesce(func.sum(LoanApplication.outstanding_balance), 0))
                    .where(LoanApplication.status == "active")
                )
            ).scalar() or Decimal("0.00")
            now = datetime.now()
            overdue_count = (
                await session.execute(
                    select(func.count(AmortizationSchedule.id))
                    .where(AmortizationSchedule.status != "paid")
                    .where(AmortizationSchedule.due_date < now)
                )
            ).scalar() or 0
            total_collections = (
                await session.execute(
                    select(func.coalesce(func.sum(Collection.amount), 0))
                    .where(Collection.status == "collected")
                )
            ).scalar() or Decimal("0.00")
            month_start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
            collected_this_month = (
                await session.execute(
                    select(func.coalesce(func.sum(Collection.amount), 0))
                    .where(Collection.status == "collected")
                    .where(Collection.collection_date >= month_start)
                )
            ).scalar() or Decimal("0.00")
            return DashboardStats(
                customersTotal=customer_count,
                loansTotal=loan_count,
                activeLoans=active_count,
                activeSavingsAccounts=active_savings_count,
                totalPortfolio=portfolio,
                overdueLoans=overdue_count,
                totalCollections=total_collections,
                collectedThisMonth=collected_this_month,
                totalOutstanding=outstanding,
            )


@strawberry.type
class MutationResponse:
    success: bool
    message: str


@strawberry.type
class BranchNode:
    id: int
    code: str
    name: str
    address: Optional[str] = None
    city: Optional[str] = None
    contactNumber: Optional[str] = None
    isActive: bool = True
    createdAt: datetime = strawberry.field(default_factory=datetime.now)
    updatedAt: datetime = strawberry.field(default_factory=datetime.now)


@strawberry.type
class Mutation:
    @strawberry.mutation
    async def create_dummy(self) -> MutationResponse:
        return MutationResponse(success=True, message="Placeholder")

    @strawberry.mutation
    async def create_loan_product(self, info: Info, input: LoanProductCreateInput) -> MutationResponse:
        current_user = info.context.get("current_user")
        if not current_user or current_user.role not in ("admin", "branch_manager"):
            return MutationResponse(success=False, message="Not authorized")

        session_factory = get_async_session_local()
        async with session_factory() as session:
            try:
                existing = await session.execute(
                    select(PGLoanProduct).where(PGLoanProduct.product_code == input.product_code)
                )
                if existing.scalar_one_or_none():
                    return MutationResponse(success=False, message="Loan product code already exists")

                new_prod = PGLoanProduct(
                    product_code=input.product_code,
                    name=input.name,
                    description=input.description,
                    amortization_type=input.amortization_type,
                    repayment_frequency=input.repayment_frequency,
                    interest_rate=input.interest_rate,
                    penalty_rate=input.penalty_rate,
                    grace_period_months=input.grace_period_months,
                    is_active=input.is_active,
                    principal_only_grace=input.principal_only_grace,
                    full_grace=input.full_grace,
                    origination_fee_rate=input.origination_fee_rate,
                    origination_fee_type=input.origination_fee_type,
                    prepayment_allowed=input.prepayment_allowed,
                    prepayment_penalty_rate=input.prepayment_penalty_rate,
                    customer_loan_limit=input.customer_loan_limit,
                )
                session.add(new_prod)
                await session.commit()
                await session.refresh(new_prod)
                return MutationResponse(success=True, message="Loan product created")
            except Exception as e:
                await session.rollback()
                return MutationResponse(success=False, message=str(e))

    @strawberry.mutation
    async def create_branch(self, info: Info, input: BranchInput) -> BranchResponse:
        current_user = info.context.get("current_user")
        if not current_user or current_user.role not in ("admin"):
            return BranchResponse(success=False, message="Not authorized")

        session_factory = get_async_session_local()
        async with session_factory() as session:
            try:
                # Check existing
                existing = await session.execute(
                    select(Branch).where(Branch.code == input.code)
                )
                if existing.scalar_one_or_none():
                    return BranchResponse(
                        success=False, message="Branch code already exists"
                    )

                new_branch = Branch(
                    code=input.code,
                    name=input.name,
                    address=input.address,
                    city=input.city,
                    contact_number=input.contactNumber,
                    is_active=True,
                )
                session.add(new_branch)
                await session.commit()
                await session.refresh(new_branch)

                return BranchResponse(
                    success=True,
                    message="Branch created successfully",
                    branch=BranchNode(
                        id=new_branch.id,
                        code=new_branch.code,
                        name=new_branch.name,
                        address=new_branch.address,
                        city=new_branch.city,
                        contactNumber=new_branch.contact_number,
                        isActive=new_branch.is_active,
                        createdAt=new_branch.created_at,
                        updatedAt=new_branch.updated_at,
                    ),
                )
            except Exception as e:
                await session.rollback()
                return BranchResponse(success=False, message=f"Error: {str(e)}")

    @strawberry.mutation
    async def update_branch(
        self, info: Info, branchId: strawberry.ID, input: BranchInput
    ) -> BranchResponse:
        current_user = info.context.get("current_user")
        if not current_user or current_user.role not in ("admin"):
            return BranchResponse(success=False, message="Not authorized")

        session_factory = get_async_session_local()
        async with session_factory() as session:
            try:
                result = await session.execute(
                    select(Branch).where(Branch.id == int(str(branchId)))
                )
                b = result.scalar_one_or_none()
                if not b:
                    return BranchResponse(success=False, message="Branch not found")

                b.name = input.name
                b.address = input.address
                b.city = input.city
                b.contact_number = input.contactNumber

                await session.commit()
                return BranchResponse(
                    success=True, message="Branch updated successfully"
                )
            except Exception as e:
                await session.rollback()
                return BranchResponse(success=False, message=f"Error: {str(e)}")

    @strawberry.mutation
    async def delete_branch(
        self, info: Info, branchId: strawberry.ID
    ) -> MutationResponse:
        current_user = info.context.get("current_user")
        if not current_user or current_user.role not in ("admin"):
            return MutationResponse(success=False, message="Not authorized")

        session_factory = get_async_session_local()
        async with session_factory() as session:
            try:
                result = await session.execute(
                    select(Branch).where(Branch.id == int(str(branchId)))
                )
                b = result.scalar_one_or_none()
                if not b:
                    return MutationResponse(success=False, message="Branch not found")

                await session.delete(b)
                await session.commit()
                return MutationResponse(
                    success=True, message="Branch deleted successfully"
                )
            except Exception as e:
                await session.rollback()
                return MutationResponse(success=False, message=f"Error: {str(e)}")

    @strawberry.mutation
    async def create_user(self, info: Info, input: UserCreateInput) -> UserResponse:
        current_user = info.context.get("current_user")
        if not current_user or current_user.role not in ("admin", "branch_manager"):
            return UserResponse(success=False, message="Not authorized")

        session_factory = get_async_session_local()
        async with session_factory() as session:
            try:
                # Check existing
                existing = await session.execute(
                    select(User).where(
                        (User.username == input.username) | (User.email == input.email)
                    )
                )
                if existing.scalar_one_or_none():
                    return UserResponse(
                        success=False, message="Username or Email already exists"
                    )

                new_user = User(
                    username=input.username,
                    email=input.email,
                    full_name=input.fullName,
                    hashed_password=get_password_hash(input.password),
                    role=input.role or "customer",
                    is_active=True,
                    is_superuser=(input.role == "admin"),
                    branch_id=input.branchId,
                    branch_code=input.branchCode,
                )
                session.add(new_user)
                await session.flush()  # Get ID

                if input.branchId or input.branchCode:
                    assignment = UserBranchAssignment(
                        user_id=str(new_user.uuid if new_user.uuid else new_user.id),
                        branch_id=input.branchId,
                        branch_code=input.branchCode,
                    )
                    session.add(assignment)

                await session.commit()
                return UserResponse(
                    success=True,
                    message="User created successfully",
                    user=UserNode(
                        id=str(new_user.uuid if new_user.uuid else new_user.id),
                        email=new_user.email,
                        username=new_user.username,
                        fullName=new_user.full_name,
                        isActive=new_user.is_active,
                        role=new_user.role,
                    ),
                )
            except Exception as e:
                await session.rollback()
                return UserResponse(success=False, message=f"Error: {str(e)}")

    @strawberry.mutation
    async def update_user(
        self, info: Info, id: strawberry.ID, input: UserUpdateInput
    ) -> UserResponse:
        current_user = info.context.get("current_user")
        # Admin can update anyone, others only themselves (except branch managers who can update branch users?)
        # For simplicity, keeping it to admin/branch_manager for now as per user request
        if not current_user or current_user.role not in ("admin", "branch_manager"):
            if str(current_user.uuid if current_user.uuid else current_user.id) != str(
                id
            ):
                return UserResponse(success=False, message="Not authorized")

        session_factory = get_async_session_local()
        async with session_factory() as session:
            try:
                # Find user by UUID or ID
                from sqlalchemy import or_

                result = await session.execute(
                    select(User).where(
                        or_(
                            User.uuid == str(id),
                            User.id == int(id) if str(id).isdigit() else False,
                        )
                    )
                )
                u = result.scalar_one_or_none()
                if not u:
                    return UserResponse(success=False, message="User not found")

                if input.username:
                    u.username = input.username
                if input.email:
                    u.email = input.email
                if input.fullName:
                    u.full_name = input.fullName
                if input.isActive is not None:
                    u.is_active = input.isActive
                if input.role:
                    # Only admin can change roles
                    if current_user.role == "admin":
                        u.role = input.role
                        u.is_superuser = input.role == "admin"

                if input.password:
                    u.hashed_password = get_password_hash(input.password)

                if input.branchId is not None:
                    u.branch_id = input.branchId
                if input.branchCode is not None:
                    u.branch_code = input.branchCode

                if input.branchId is not None or input.branchCode is not None:
                    # Update assignment
                    res_ba = await session.execute(
                        select(UserBranchAssignment).where(
                            UserBranchAssignment.user_id == str(id)
                        )
                    )
                    ba = res_ba.scalar_one_or_none()
                    if ba:
                        if input.branchId is not None:
                            ba.branch_id = input.branchId
                        if input.branchCode is not None:
                            ba.branch_code = input.branchCode
                    else:
                        session.add(
                            UserBranchAssignment(
                                user_id=str(id),
                                branch_id=input.branchId,
                                branch_code=input.branchCode,
                            )
                        )

                await session.commit()
                return UserResponse(success=True, message="User updated successfully")
            except Exception as e:
                await session.rollback()
                return UserResponse(success=False, message=f"Error: {str(e)}")

    @strawberry.mutation
    async def delete_user(self, info: Info, id: strawberry.ID) -> MutationResponse:
        current_user = info.context.get("current_user")
        if not current_user or current_user.role not in ("admin", "branch_manager"):
            return MutationResponse(success=False, message="Not authorized")

        session_factory = get_async_session_local()
        async with session_factory() as session:
            try:
                from sqlalchemy import or_

                result = await session.execute(
                    select(User).where(
                        or_(
                            User.uuid == str(id),
                            User.id == int(id) if str(id).isdigit() else False,
                        )
                    )
                )
                u = result.scalar_one_or_none()
                if not u:
                    return MutationResponse(success=False, message="User not found")

                await session.delete(u)
                await session.commit()
                return MutationResponse(
                    success=True, message="User deleted successfully"
                )
            except Exception as e:
                await session.rollback()
                return MutationResponse(success=False, message=f"Error: {str(e)}")

    @strawberry.mutation
    async def create_customer(
        self, info: Info, input: CustomerInput
    ) -> CustomerResponse:
        current_user = info.context.get("current_user")
        if not current_user or current_user.role not in ("admin", "branch_manager"):
            return CustomerResponse(success=False, message="Not authorized")

        session_factory = get_async_session_local()
        async with session_factory() as session:
            try:
                # Lookup branch_id from code
                branch_stmt = select(Branch).where(Branch.code == input.branchCode)
                branch_res = await session.execute(branch_stmt)
                branch = branch_res.scalar_one_or_none()
                branch_id = branch.id if branch else None

                new_customer = Customer(
                    display_name=input.displayName,
                    customer_type=input.customerType,
                    branch_code=input.branchCode,
                    branch_id=branch_id,
                    email_address=input.emailAddress,
                    mobile_number=input.mobileNumber,
                    is_active=True,
                )
                session.add(new_customer)
                await session.commit()
                await session.refresh(new_customer)

                return CustomerResponse(
                    success=True,
                    message="Customer created successfully",
                    customer=CustomerNode(
                        id=str(new_customer.id),
                        displayName=new_customer.display_name,
                        customerType=new_customer.customer_type,
                        branchCode=new_customer.branch_code,
                        isActive=new_customer.is_active,
                        emailAddress=new_customer.email_address,
                        mobileNumber=new_customer.mobile_number,
                        createdAt=new_customer.created_at,
                    ),
                )
            except Exception as e:
                await session.rollback()
                return CustomerResponse(success=False, message=f"Error: {str(e)}")

    @strawberry.mutation
    async def update_customer(
        self, info: Info, id: strawberry.ID, input: CustomerInput
    ) -> CustomerResponse:
        current_user = info.context.get("current_user")
        if not current_user or current_user.role not in ("admin", "branch_manager"):
            return CustomerResponse(success=False, message="Not authorized")

        session_factory = get_async_session_local()
        async with session_factory() as session:
            try:
                # Cast id to int for BigInteger comparison
                cust_id = int(str(id))
                result = await session.execute(
                    select(Customer).where(Customer.id == cust_id)
                )
                c = result.scalar_one_or_none()
                if not c:
                    return CustomerResponse(success=False, message="Customer not found")

                # Lookup branch_id if code changed
                if input.branchCode != c.branch_code:
                    branch_stmt = select(Branch).where(Branch.code == input.branchCode)
                    branch_res = await session.execute(branch_stmt)
                    branch = branch_res.scalar_one_or_none()
                    if branch:
                        c.branch_id = branch.id

                c.display_name = input.displayName
                c.customer_type = input.customerType
                c.branch_code = input.branchCode
                c.email_address = input.emailAddress
                c.mobile_number = input.mobileNumber

                await session.commit()
                return CustomerResponse(
                    success=True, message="Customer updated successfully"
                )
            except Exception as e:
                await session.rollback()
                return CustomerResponse(success=False, message=f"Error: {str(e)}")

    @strawberry.mutation
    async def delete_customer(self, info: Info, id: strawberry.ID) -> MutationResponse:
        current_user = info.context.get("current_user")
        if not current_user or current_user.role not in ("admin", "branch_manager"):
            return MutationResponse(success=False, message="Not authorized")

        session_factory = get_async_session_local()
        async with session_factory() as session:
            try:
                # Cast id to int for BigInteger comparison
                cust_id = int(str(id))
                result = await session.execute(
                    select(Customer).where(Customer.id == cust_id)
                )
                c = result.scalar_one_or_none()
                if not c:
                    return MutationResponse(success=False, message="Customer not found")

                await session.delete(c)
                await session.commit()
                return MutationResponse(
                    success=True, message="Customer deleted successfully"
                )
            except Exception as e:
                await session.rollback()
                return MutationResponse(success=False, message=f"Error: {str(e)}")

    @strawberry.mutation
    async def submit_loan(self, loanId: strawberry.ID) -> MutationResponse:
        return MutationResponse(success=True, message="Loan submitted for review")

    @strawberry.mutation
    async def approve_loan(
        self,
        id: strawberry.ID,
        approvedPrincipal: Optional[Decimal] = None,
        approvedRate: Optional[Decimal] = None,
    ) -> MutationResponse:
        return MutationResponse(success=True, message="Loan approved")

    @strawberry.field
    async def branches(self) -> List[BranchNode]:
        session_factory = get_async_session_local()
        async with session_factory() as session:
            stmt = select(Branch)
            result = await session.execute(stmt)
            branches = result.scalars().all()
            return [
                BranchNode(
                    id=b.id,
                    code=b.code,
                    name=b.name,
                    address=b.address,
                    city=b.city,
                    contactNumber=b.contact_number,
                    isActive=b.is_active,
                    createdAt=b.created_at,
                    updatedAt=b.updated_at,
                )
                for b in branches
            ]

    @strawberry.mutation
    async def createSavingsAccount(
        self, info: Info, input: SavingsAccountCreateInput
    ) -> SavingsAccountResponse:
        current_user = info.context.get("current_user")
        if not current_user:
            return SavingsAccountResponse(success=False, message="Not authenticated")

        session_factory = get_async_session_local()
        async with session_factory() as session:
            try:
                # Basic validation
                if not input.customerId or not input.accountNumber:
                    return SavingsAccountResponse(
                        success=False, message="Customer and Account Number are required"
                    )

                new_account = SavingsAccount(
                    account_number=input.accountNumber,
                    customer_id=int(input.customerId),
                    account_type=input.accountType,
                    balance=input.balance,
                    currency=input.currency,
                    status=input.status,
                    interest_rate=input.interestRate if input.interestRate else 0.00,
                    opened_at=input.openedAt if input.openedAt else datetime.now(),
                    
                    # Ported fields
                    principal=input.principal,
                    term_days=input.termDays,
                    interest_paid_frequency=input.interestPaidFrequency,
                    target_amount=input.targetAmount,
                    target_date=input.targetDate,
                    goal_name=input.goalName,
                    guardian_id=input.guardianId,
                    guardian_name=input.guardianName,
                    minor_date_of_birth=input.minorDateOfBirth,
                    secondary_owner_id=input.secondaryOwnerId,
                    secondary_owner_name=input.secondaryOwnerName,
                    operation_mode=input.operationMode,
                )
                
                # Calculate maturity date if applicable
                if input.termDays and input.openedAt:
                    from datetime import timedelta
                    new_account.maturity_date = input.openedAt + timedelta(days=input.termDays)

                session.add(new_account)
                await session.commit()
                await session.refresh(new_account)

                return SavingsAccountResponse(
                    success=True,
                    message="Savings account created successfully",
                    account=SavingsAccountNode(
                        id=str(new_account.id),
                        accountNumber=new_account.account_number,
                        balance=new_account.balance,
                        customerId=str(new_account.customer_id),
                        accountType=new_account.account_type,
                        status=new_account.status,
                        openedAt=new_account.opened_at,
                        
                        # Ported fields mapping
                        currency=new_account.currency,
                        interestRate=new_account.interest_rate,
                        maturityDate=new_account.maturity_date,
                        principal=new_account.principal,
                        termDays=new_account.term_days,
                        interestPaidFrequency=new_account.interest_paid_frequency,
                        targetAmount=new_account.target_amount,
                        targetDate=new_account.target_date,
                        goalName=new_account.goal_name,
                        guardianId=new_account.guardian_id,
                        guardianName=new_account.guardian_name,
                        minorDateOfBirth=new_account.minor_date_of_birth,
                        secondaryOwnerId=new_account.secondary_owner_id,
                        secondaryOwnerName=new_account.secondary_owner_name,
                        operationMode=new_account.operation_mode,
                    ),
                )
            except Exception as e:
                await session.rollback()
                return SavingsAccountResponse(success=False, message=f"Error: {str(e)}")

    @strawberry.mutation
    async def createLoan(self, info: Info, input: LoanInput) -> LoanResponse:
        current_user = info.context.get("current_user")
        if not current_user:
            return LoanResponse(success=False, message="Not authenticated")

        session_factory = get_async_session_local()
        async with session_factory() as session:
            try:
                new_loan = LoanApplication(
                    customer_id=input.customerId,
                    product_id=input.productId,
                    principal=input.principal,
                    term_months=input.termMonths,
                    disbursement_method=input.disbursementMethod,
                    status="draft",
                )
                session.add(new_loan)
                await session.commit()
                await session.refresh(new_loan)

                return LoanResponse(
                    success=True,
                    message="Loan created successfully",
                    loan=LoanNode(
                        id=str(new_loan.id),
                        principal=new_loan.principal,
                        status=new_loan.status,
                        customerId=str(new_loan.customer_id),
                        productId=new_loan.product_id,
                        termMonths=new_loan.term_months,
                        approvedPrincipal=new_loan.approved_principal,
                        approvedRate=new_loan.approved_rate,
                        outstandingBalance=new_loan.outstanding_balance,
                        createdAt=new_loan.created_at,
                        updatedAt=new_loan.updated_at,
                        disbursedAt=new_loan.disbursed_at,
                    ),
                )
            except Exception as e:
                await session.rollback()
                return LoanResponse(success=False, message=f"Error: {str(e)}")

    @strawberry.mutation
    async def submitLoan(self, info: Info, id: strawberry.ID) -> MutationResponse:
        current_user = info.context.get("current_user")
        if not current_user:
            return MutationResponse(success=False, message="Not authenticated")
            
        session_factory = get_async_session_local()
        async with session_factory() as session:
            result = await session.execute(select(LoanApplication).where(LoanApplication.id == int(str(id))))
            loan = result.scalar_one_or_none()
            if not loan:
                return MutationResponse(success=False, message="Loan not found")
            loan.status = "submitted"
            await session.commit()
            return MutationResponse(success=True, message="Loan submitted for review")

    @strawberry.mutation
    async def reviewLoan(self, info: Info, id: strawberry.ID) -> MutationResponse:
        current_user = info.context.get("current_user")
        if not current_user or current_user.role not in ("admin", "branch_manager", "loan_officer"):
            return MutationResponse(success=False, message="Not authorized")

        session_factory = get_async_session_local()
        async with session_factory() as session:
            result = await session.execute(select(LoanApplication).where(LoanApplication.id == int(str(id))))
            loan = result.scalar_one_or_none()
            if not loan:
                return MutationResponse(success=False, message="Loan not found")
            loan.status = "reviewing"
            await session.commit()
            return MutationResponse(success=True, message="Loan is now under review")

    @strawberry.mutation
    async def approveLoan(
        self, 
        info: Info, 
        id: strawberry.ID, 
        approvedPrincipal: Optional[Decimal] = None,
        approvedRate: Optional[Decimal] = None
    ) -> MutationResponse:
        current_user = info.context.get("current_user")
        if not current_user or current_user.role not in ("admin", "branch_manager", "loan_officer"):
            return MutationResponse(success=False, message="Not authorized")

        session_factory = get_async_session_local()
        async with session_factory() as session:
            result = await session.execute(select(LoanApplication).where(LoanApplication.id == int(str(id))))
            loan = result.scalar_one_or_none()
            if not loan:
                return MutationResponse(success=False, message="Loan not found")
            
            # Determine approved amount
            approved_amount = approvedPrincipal if approvedPrincipal else (loan.principal or Decimal(0))
            
            loan.status = "approved"
            if approvedPrincipal:
                loan.approved_principal = approvedPrincipal
            else:
                loan.approved_principal = loan.principal
            
            if approvedRate:
                loan.approved_rate = approvedRate
            
            # Get customer name for journal entries
            from .database.pg_core_models import Customer
            if str(loan.customer_id).isdigit():
                customer_stmt = select(Customer).where(Customer.id == int(str(loan.customer_id)))
            else:
                # Fallback to display_name or ID if uuid is not present in model
                # Based on previous investigation, Customer might not have uuid column yet
                customer_stmt = select(Customer).where(Customer.id == int(str(loan.customer_id)) if str(loan.customer_id).isdigit() else False)
            
            customer_res = await session.execute(customer_stmt)
            customer = customer_res.scalar_one_or_none()
            customer_name = customer.display_name if customer else "Customer"

            # Create GAAP-compliant journal entry for loan approval
            from .accounting import create_journal_entry
            
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
            return MutationResponse(success=True, message="Loan approved successfully")

    @strawberry.mutation
    async def rejectLoan(self, info: Info, id: strawberry.ID, reason: str) -> MutationResponse:
        current_user = info.context.get("current_user")
        if not current_user or current_user.role not in ("admin", "branch_manager", "loan_officer"):
            return MutationResponse(success=False, message="Not authorized")

        session_factory = get_async_session_local()
        async with session_factory() as session:
            result = await session.execute(select(LoanApplication).where(LoanApplication.id == int(str(id))))
            loan = result.scalar_one_or_none()
            if not loan:
                return MutationResponse(success=False, message="Loan not found")
            loan.status = "rejected"
            loan.rejected_reason = reason
            await session.commit()
            return MutationResponse(success=True, message="Loan rejected")

    @strawberry.mutation
    async def createLoanTransaction(
        self, info: Info, input: LoanTransactionCreateInput
    ) -> LoanTransactionResponse:
        current_user = info.context.get("current_user")
        if not current_user:
            return LoanTransactionResponse(success=False, message="Not authenticated")

        session_factory = get_async_session_local()
        async with session_factory() as session:
            try:
                new_tx = LoanTransaction(
                    loan_id=int(input.loanId),
                    type=input.transactionType,
                    amount=input.amount,
                    description=input.description,
                    receipt_number=input.receiptNumber,
                    processed_by=str(current_user.id),
                    
                    # Ported fields
                    commercial_bank=input.commercialBank,
                    servicing_branch=input.servicingBranch,
                    region=input.region,
                    loan_product_id=input.loanProductId,
                    debit_account=input.debitAccount,
                    credit_account=input.creditAccount,
                    disbursement_method=input.disbursementMethod,
                    disbursement_status=input.disbursementStatus,
                    cheque_number=input.chequeNumber,
                    beneficiary_bank=input.beneficiaryBank,
                    beneficiary_account=input.beneficiaryAccount,
                    approved_by=input.approvedBy,
                    borrower_name=input.borrowerName,
                    created_by=str(current_user.id),
                    updated_by=str(current_user.id),
                )
                
                session.add(new_tx)
                await session.commit()
                await session.refresh(new_tx)

                return LoanTransactionResponse(
                    success=True,
                    message="Loan transaction created successfully",
                    transaction=LoanTransactionNode(
                        id=str(new_tx.id),
                        loanId=str(new_tx.loan_id),
                        amount=new_tx.amount,
                        transactionType=new_tx.type,
                        description=new_tx.description,
                        reference=new_tx.receipt_number,
                        createdAt=new_tx.timestamp,
                        
                        # Ported fields mapping
                        commercialBank=new_tx.commercial_bank,
                        servicingBranch=new_tx.servicing_branch,
                        region=new_tx.region,
                        loanProductId=new_tx.loan_product_id,
                        debitAccount=new_tx.debit_account,
                        creditAccount=new_tx.credit_account,
                        disbursementMethod=new_tx.disbursement_method,
                        disbursementStatus=new_tx.disbursement_status,
                        chequeNumber=new_tx.cheque_number,
                        beneficiaryBank=new_tx.beneficiary_bank,
                        beneficiaryAccount=new_tx.beneficiary_account,
                        approvedBy=new_tx.approved_by,
                        processedBy=new_tx.processed_by,
                        createdBy=new_tx.created_by,
                        updatedBy=new_tx.updated_by,
                        borrowerName=new_tx.borrower_name,
                        updatedAt=new_tx.updated_at,
                    ),
                )
            except Exception as e:
                await session.rollback()
                return LoanTransactionResponse(success=False, message=f"Error: {str(e)}")

    @strawberry.mutation
    async def updateLoanTransaction(
        self, info: Info, id: strawberry.ID, input: LoanTransactionUpdateInput
    ) -> LoanTransactionResponse:
        current_user = info.context.get("current_user")
        if not current_user:
            return LoanTransactionResponse(success=False, message="Not authenticated")

        session_factory = get_async_session_local()
        async with session_factory() as session:
            try:
                result = await session.execute(
                    select(LoanTransaction).where(LoanTransaction.id == int(str(id)))
                )
                tx = result.scalar_one_or_none()
                if not tx:
                    return LoanTransactionResponse(success=False, message="Transaction not found")

                old_amount = tx.amount
                print(f"DEBUG updateLoanTransaction: old_amount={old_amount}, input.amount={input.amount}")
                
                # Update fields if provided
                if input.transactionType is not None: tx.type = input.transactionType
                if input.amount is not None: 
                    print(f"DEBUG: Setting tx.amount from {tx.amount} to {input.amount}")
                    tx.amount = input.amount
                if input.description is not None: tx.description = input.description
                if input.receiptNumber is not None: tx.receipt_number = input.receiptNumber
                if input.commercialBank is not None: tx.commercial_bank = input.commercialBank
                if input.servicingBranch is not None: tx.servicing_branch = input.servicingBranch
                if input.region is not None: tx.region = input.region
                if input.loanProductId is not None: tx.loan_product_id = input.loanProductId
                if input.debitAccount is not None: tx.debit_account = input.debitAccount
                if input.creditAccount is not None: tx.credit_account = input.creditAccount
                if input.disbursementMethod is not None: tx.disbursement_method = input.disbursementMethod
                if input.disbursementStatus is not None: tx.disbursement_status = input.disbursementStatus
                if input.chequeNumber is not None: tx.cheque_number = input.chequeNumber
                if input.beneficiaryBank is not None: tx.beneficiary_bank = input.beneficiaryBank
                if input.beneficiaryAccount is not None: tx.beneficiary_account = input.beneficiaryAccount
                if input.approvedBy is not None: tx.approved_by = input.approvedBy
                if input.borrowerName is not None: tx.borrower_name = input.borrowerName
                
                tx.updated_by = str(current_user.id)
                tx.updated_at = datetime.now()

                # If amount changed and this is a repayment, recalculate amortization
                if input.amount is not None and old_amount != input.amount and tx.type == "repayment":
                    print(f"DEBUG: Recalculating amortization. old={old_amount}, new={input.amount}")
                    
                    # Update loan outstanding balance
                    loan_result = await session.execute(
                        select(LoanApplication).where(LoanApplication.id == tx.loan_id)
                    )
                    loan = loan_result.scalar_one_or_none()
                    if loan:
                        # Reverse the old amount and apply new amount
                        loan.outstanding_balance = (loan.outstanding_balance or 0) + old_amount - input.amount
                        print(f"DEBUG: Updated loan outstanding balance to {loan.outstanding_balance}")
                    
                    # Recalculate amortization - get all schedules and recalculate properly
                    from .database.pg_loan_models import AmortizationSchedule
                    
                    # Get all schedules for this loan ordered by installment number
                    sched_result = await session.execute(
                        select(AmortizationSchedule)
                        .where(AmortizationSchedule.loan_id == tx.loan_id)
                        .order_by(AmortizationSchedule.installment_number.asc())
                    )
                    schedules = sched_result.scalars().all()
                    
                    # Reset all principal_paid and interest_paid to 0
                    for sched in schedules:
                        sched.principal_paid = Decimal("0.00")
                        sched.interest_paid = Decimal("0.00")
                        sched.status = "pending"
                    
                    # Apply the new payment amount properly (interest first, then principal)
                    remaining_payment = input.amount
                    for sched in schedules:
                        if remaining_payment <= 0:
                            break
                        
                        # Apply to interest first
                        interest_remaining = (sched.interest_due or Decimal("0.00")) - (sched.interest_paid or Decimal("0.00"))
                        if interest_remaining > 0:
                            interest_to_pay = min(remaining_payment, interest_remaining)
                            sched.interest_paid = (sched.interest_paid or Decimal("0.00")) + interest_to_pay
                            remaining_payment -= interest_to_pay
                        
                        if remaining_payment <= 0:
                            sched.status = "partial"
                            break
                        
                        # Apply to principal
                        principal_remaining = (sched.principal_due or Decimal("0.00")) - (sched.principal_paid or Decimal("0.00"))
                        if principal_remaining > 0:
                            principal_to_pay = min(remaining_payment, principal_remaining)
                            sched.principal_paid = (sched.principal_paid or Decimal("0.00")) + principal_to_pay
                            remaining_payment -= principal_to_pay
                        
                        # Update status
                        if (sched.principal_paid or Decimal("0.00")) >= (sched.principal_due or Decimal("0.00")) and (sched.interest_paid or Decimal("0.00")) >= (sched.interest_due or Decimal("0.00")):
                            sched.status = "paid"
                        else:
                            sched.status = "partial"
                    
                    print(f"DEBUG: Applied payment to schedules")
                    
                    # Update journal entry for the repayment
                    from .accounting import create_journal_entry
                    
                    # Find the old journal entry for this transaction
                    from .database.pg_accounting_models import JournalEntry, JournalLine
                    
                    # Search by loan_id in description instead
                    je_result = await session.execute(
                        select(JournalEntry).where(JournalEntry.description.like(f"%Loan 9%"))
                    )
                    journal_entries = je_result.scalars().all()
                    print(f"DEBUG: Found {len(journal_entries)} journal entries for Loan 9")
                    
                    journal_entry = None
                    if journal_entries and len(journal_entries) > 0:
                        # Get the most recent one by sorting by created_at
                        journal_entry = journal_entries[-1]
                        print(f"DEBUG: Using journal entry id={journal_entry.id}, description={journal_entry.description}")
                    else:
                        # Try searching by receipt number
                        print(f"DEBUG: No journal entry found, trying receipt number")
                    
                    if journal_entry:
                        # Delete old journal entry lines
                        old_lines_result = await session.execute(
                            select(JournalLine).where(JournalLine.entry_id == journal_entry.id)
                        )
                        old_lines = old_lines_result.scalars().all()
                        print(f"DEBUG: Deleting {len(old_lines)} old journal lines")
                        for line in old_lines:
                            await session.delete(line)
                        
                        # Recalculate principal and interest from schedules
                        sched_result = await session.execute(
                            select(AmortizationSchedule)
                            .where(AmortizationSchedule.loan_id == tx.loan_id)
                            .order_by(AmortizationSchedule.installment_number.asc())
                        )
                        schedules = sched_result.scalars().all()
                        
                        total_principal_paid = sum(s.principal_paid or Decimal("0.00") for s in schedules)
                        total_interest_paid = sum(s.interest_paid or Decimal("0.00") for s in schedules)
                        
                        # Create new journal entry lines
                        # Debit Cash (1010)
                        cash_line = JournalLine(
                            entry_id=journal_entry.id,
                            account_code="1010",
                            debit=input.amount,
                            credit=Decimal("0.00"),
                            description=f"Loan Repayment - {tx.loan_id}"
                        )
                        session.add(cash_line)
                        
                        # Credit Loans Receivable (1300) for principal
                        if total_principal_paid > 0:
                            principal_line = JournalLine(
                                entry_id=journal_entry.id,
                                account_code="1300",
                                debit=Decimal("0.00"),
                                credit=total_principal_paid,
                                description=f"Principal Payment - {tx.loan_id}"
                            )
                            session.add(principal_line)
                        
                        # Credit Interest Income (4100) for interest
                        if total_interest_paid > 0:
                            interest_line = JournalLine(
                                entry_id=journal_entry.id,
                                account_code="4100",
                                debit=Decimal("0.00"),
                                credit=total_interest_paid,
                                description=f"Interest Payment - {tx.loan_id}"
                            )
                            session.add(interest_line)
                        
                        print(f"DEBUG: Updated journal entry for repayment")

                await session.commit()
                await session.refresh(tx)

                return LoanTransactionResponse(
                    success=True,
                    message="Loan transaction updated successfully",
                    transaction=LoanTransactionNode(
                        id=str(tx.id),
                        loanId=str(tx.loan_id),
                        amount=tx.amount,
                        transactionType=tx.type,
                        description=tx.description,
                        reference=tx.receipt_number,
                        createdAt=tx.timestamp,
                        # Ported mapping...
                        borrowerName=tx.borrower_name,
                    ),
                )
            except Exception as e:
                await session.rollback()
                return LoanTransactionResponse(success=False, message=f"Error: {str(e)}")

    @strawberry.mutation
    async def deleteLoanTransaction(
        self, info: Info, id: strawberry.ID
    ) -> MutationResponse:
        current_user = info.context.get("current_user")
        if not current_user or current_user.role not in ("admin"):
            return MutationResponse(success=False, message="Not authorized")

        session_factory = get_async_session_local()
        async with session_factory() as session:
            try:
                result = await session.execute(
                    select(LoanTransaction).where(LoanTransaction.id == int(str(id)))
                )
                tx = result.scalar_one_or_none()
                if not tx:
                    return MutationResponse(success=False, message="Transaction not found")

                await session.delete(tx)
                await session.commit()
                return MutationResponse(success=True, message="Transaction deleted successfully")
            except Exception as e:
                await session.rollback()
                return MutationResponse(success=False, message=f"Error: {str(e)}")

    @strawberry.mutation
    async def disburseLoan(
        self, 
        info: Info, 
        id: strawberry.ID,
        disbursementMethod: Optional[str] = "cash"
    ) -> LoanResponse:
        current_user = info.context.get("current_user")
        if not current_user or current_user.role not in ("admin", "branch_manager", "loan_officer"):
            return LoanResponse(success=False, message="Not authorized")

        session_factory = get_async_session_local()
        async with session_factory() as session:
            try:
                print(f"DEBUG: Disbursing loan {id}")
                # 1. Fetch loan
                result = await session.execute(
                    select(LoanApplication).where(LoanApplication.id == int(str(id)))
                )
                loan = result.scalar_one_or_none()
                if not loan:
                    print(f"DEBUG: Loan {id} not found")
                    return LoanResponse(success=False, message="Loan not found")
                
                print(f"DEBUG: Loan found, status: {loan.status}")
                if loan.status != "approved":
                    return LoanResponse(success=False, message=f"Loan must be approved before disbursement. Current status: {loan.status}")

                # 2. Update loan status
                loan.status = "active"
                loan.disbursed_at = datetime.now()
                loan.disbursement_method = disbursementMethod
                loan.outstanding_balance = loan.approved_principal or loan.principal
                
                print(f"DEBUG: Fetching product for loan {loan.id}")
                # 3. Fetch product for amortization type
                prod_result = await session.execute(
                    select(PGLoanProduct).where(PGLoanProduct.id == loan.product_id)
                )
                product = prod_result.scalar_one()
                
                print(f"DEBUG: Generating schedule for loan {loan.id}")
                # 4. Generate amortization schedule
                principal = loan.approved_principal or loan.principal
                rate_annual = loan.approved_rate or product.interest_rate
                term_months = int(loan.term_months)
                amortization_type = product.amortization_type
                
                from dateutil.relativedelta import relativedelta
                from datetime import timedelta

                # Frequency config (same logic as loan.py)
                def _freq_config(freq: str, t_months: int):
                    cf = {
                        "daily": (t_months * 30, 1, 365),
                        "weekly": (t_months * 4, 7, 52),
                        "bi_weekly": (t_months * 2, 14, 26),
                        "monthly": (t_months, 0, 12),
                        "quarterly": (max(1, t_months // 3), 0, 4),
                        "bullet": (1, 0, 1),
                    }
                    return cf.get(freq, (t_months, 0, 12))
                def _calc_due(dt, i, ds, rd):
                    if ds > 0:
                        return dt + timedelta(days=i * ds)
                    elif rd == 12:
                        return dt + relativedelta(months=i)
                    elif rd == 4:
                        return dt + relativedelta(months=i * 3)
                    else:
                        return dt + relativedelta(months=i)

                repayment_frequency = product.repayment_frequency
                num_periods, days_step, rate_divisor = _freq_config(repayment_frequency, int(loan.term_months))
                rate_per_period = (rate_annual / Decimal(100)) / Decimal(rate_divisor)
                balance = principal

                def due(i: int):
                    dt = _calc_due(loan.disbursed_at, i, days_step, rate_divisor)
                    return dt.date()

                if amortization_type == "flat_rate":
                    interest_per_period = principal * rate_per_period
                    principal_per_period = principal / Decimal(num_periods)
                    for i in range(1, num_periods + 1):
                        balance -= principal_per_period
                        sched = AmortizationSchedule(
                            loan_id=loan.id,
                            installment_number=i,
                            due_date=due(i),
                            principal_due=round(principal_per_period, 2),
                            interest_due=round(interest_per_period, 2),
                            status="pending"
                        )
                        session.add(sched)

                elif amortization_type == "declining_balance":
                    if rate_per_period > 0:
                        pmt = (principal * rate_per_period) / (
                            Decimal(1) - (Decimal(1) + rate_per_period) ** Decimal(-num_periods)
                        )
                    else:
                        pmt = principal / Decimal(num_periods)
                    for i in range(1, num_periods + 1):
                        interest_for_period = balance * rate_per_period
                        principal_for_period = pmt - interest_for_period
                        balance -= principal_for_period
                        sched = AmortizationSchedule(
                            loan_id=loan.id,
                            installment_number=i,
                            due_date=due(i),
                            principal_due=round(principal_for_period, 2),
                            interest_due=round(interest_for_period, 2),
                            status="pending"
                        )
                        session.add(sched)
                else:
                    # Default/Interest-only fallback
                    interest_per_period = principal * rate_per_period
                    principal_per_period = principal / Decimal(num_periods)
                    for i in range(1, num_periods + 1):
                        sched = AmortizationSchedule(
                            loan_id=loan.id,
                            installment_number=i,
                            due_date=due(i),
                            principal_due=round(principal_per_period, 2),
                            interest_due=round(interest_per_period, 2),
                            status="pending"
                        )
                        session.add(sched)

                print(f"DEBUG: Creating transaction for loan {loan.id}")
                # 5. Create disbursement transaction
                txn = LoanTransaction(
                    loan_id=loan.id,
                    type="disbursement",
                    amount=loan.approved_principal or loan.principal,
                    receipt_number=f"DSB-{uuid.uuid4().hex[:8].upper()}",
                    description=f"Loan disbursement via {disbursementMethod}",
                    processed_by=str(current_user.id)
                )
                session.add(txn)
                
                # 6. Create journal entry for disbursement - reverse Disbursement Payable and record cash outflow
                from .accounting import create_journal_entry
                
                principal = loan.approved_principal or loan.principal
                disbursement_ref = f"JNL-DSB-{loan.id:06d}"
                gl_lines = [
                    {
                        "account_code": "2010",
                        "debit": principal,
                        "credit": Decimal(0),
                        "description": "Reverse Disbursement Payable - Loan Disbursed",
                    },
                    {
                        "account_code": "1010",
                        "debit": Decimal(0),
                        "credit": principal,
                        "description": "Cash Disbursed to Customer",
                    },
                ]
                
                try:
                    await create_journal_entry(
                        session=session,
                        reference_no=disbursement_ref,
                        description=f"Loan Disbursement - Customer {loan.customer_id} - Principal {principal}",
                        created_by=str(current_user.id),
                        lines=gl_lines,
                    )
                except Exception as e:
                    import logging
                    logging.error(f"Failed to create journal entry for loan disbursement: {e}")
                
                print(f"DEBUG: Committing disbursement for loan {loan.id}")
                await session.commit()
                await session.refresh(loan)
                print(f"DEBUG: Disbursement successful for loan {loan.id}")

                return LoanResponse(
                    success=True,
                    message="Loan disbursed successfully",
                    loan=LoanNode(
                        id=str(loan.id),
                        principal=loan.principal,
                        status=loan.status,
                        customerId=str(loan.customer_id),
                        productId=loan.product_id,
                        termMonths=loan.term_months,
                        approvedPrincipal=loan.approved_principal,
                        approvedRate=loan.approved_rate,
                        outstandingBalance=loan.outstanding_balance,
                        createdAt=loan.created_at,
                        updatedAt=loan.updated_at,
                        disbursedAt=loan.disbursed_at,
                    ),
                )
            except Exception as e:
                import traceback
                traceback.print_exc()
                await session.rollback()
                return LoanResponse(success=False, message=f"Error: {str(e)}")

    @strawberry.mutation
    async def repayLoan(
        self,
        info: Info,
        id: strawberry.ID,
        amount: Decimal,
        paymentMethod: Optional[str] = "cash",
        notes: Optional[str] = None,
        paymentDate: Optional[date] = None,
        invoiceNumber: Optional[str] = None,
        isEft: bool = False
    ) -> LoanResponse:
        current_user = info.context.get("current_user")
        if not current_user:
            return LoanResponse(success=False, message="Not authenticated")

        session_factory = get_async_session_local()
        async with session_factory() as session:
            try:
                # 1. Fetch loan
                loan_id_int = int(str(id))
                result = await session.execute(
                    select(LoanApplication).where(LoanApplication.id == loan_id_int)
                )
                loan = result.scalar_one_or_none()
                if not loan:
                    return LoanResponse(success=False, message="Loan not found")

                if loan.status != "active":
                    return LoanResponse(success=False, message="Only active loans can accept repayments")

                # 2. Update balance
                if not loan.outstanding_balance:
                    loan.outstanding_balance = loan.approved_principal or loan.principal

                loan.outstanding_balance -= amount
                if loan.outstanding_balance <= 0:
                    loan.outstanding_balance = 0
                    loan.status = "paid"

                # 3. Allocate payment to Amortization Schedule (Interest first, then Principal)
                from .database.pg_loan_models import AmortizationSchedule
                sched_result = await session.execute(
                    select(AmortizationSchedule)
                    .where(AmortizationSchedule.loan_id == loan_id_int)
                    .where(AmortizationSchedule.status != "paid")
                    .order_by(AmortizationSchedule.installment_number.asc())
                )
                schedules = sched_result.scalars().all()
                
                remaining_payment = amount
                total_interest_paid = Decimal("0.00")
                total_principal_paid = Decimal("0.00")
                
                effective_payment_date = datetime.combine(paymentDate, datetime.min.time()) if paymentDate else datetime.now()

                for sched in schedules:
                    if remaining_payment <= 0:
                        break
                    
                    # A. Satisfy Interest first
                    interest_remaining = sched.interest_due - (sched.interest_paid or 0)
                    if interest_remaining > 0:
                        interest_to_pay = min(remaining_payment, interest_remaining)
                        sched.interest_paid = (sched.interest_paid or 0) + interest_to_pay
                        remaining_payment -= interest_to_pay
                        total_interest_paid += interest_to_pay
                    
                    if remaining_payment <= 0:
                        sched.payment_date = effective_payment_date
                        sched.status = "partial"
                        break
                        
                    # B. Satisfy Principal next
                    principal_remaining = sched.principal_due - (sched.principal_paid or 0)
                    if principal_remaining > 0:
                        principal_to_pay = min(remaining_payment, principal_remaining)
                        sched.principal_paid = (sched.principal_paid or 0) + principal_to_pay
                        remaining_payment -= principal_to_pay
                        total_principal_paid += principal_to_pay
                    
                    # Update status
                    if (sched.principal_paid or 0) >= sched.principal_due and (sched.interest_paid or 0) >= sched.interest_due:
                        sched.status = "paid"
                    else:
                        sched.status = "partial"
                    
                    sched.payment_date = effective_payment_date

                # 4. Create transaction record
                receipt_no = invoiceNumber if invoiceNumber else f"PAY-{uuid.uuid4().hex[:8].upper()}"
                txn = LoanTransaction(
                    loan_id=loan.id,
                    type="repayment",
                    amount=amount,
                    receipt_number=receipt_no,
                    description=notes or f"Repayment via {paymentMethod}",
                    processed_by=str(current_user.id),
                    is_eft=isEft
                )
                
                if paymentDate:
                    txn.timestamp = datetime.combine(paymentDate, datetime.min.time())
                
                session.add(txn)

                # 5. Create Journal Entries
                # Debit Cash (1010), Credit Loans Receivable (1300) for Principal, Credit Interest Income (4100) for Interest
                from .accounting import create_journal_entry
                gl_lines = [
                    {
                        "account_code": "1010",
                        "debit": amount,
                        "credit": Decimal(0),
                        "description": f"Loan Repayment - {loan.id}",
                    }
                ]
                
                if total_principal_paid > 0:
                    gl_lines.append({
                        "account_code": "1300",
                        "debit": Decimal(0),
                        "credit": total_principal_paid,
                        "description": f"Principal Payment - {loan.id}",
                    })
                
                if total_interest_paid > 0:
                    gl_lines.append({
                        "account_code": "4100",
                        "debit": Decimal(0),
                        "credit": total_interest_paid,
                        "description": f"Interest Payment - {loan.id}",
                    })
                
                # Handle unallocated amount (if any) as advance payment
                unallocated = amount - (total_principal_paid + total_interest_paid)
                if unallocated > 0:
                    gl_lines.append({
                        "account_code": "2100", # Customer Advances
                        "debit": Decimal(0),
                        "credit": unallocated,
                        "description": f"Unallocated Advance - {loan.id}",
                    })

                await create_journal_entry(
                    session=session,
                    reference_no=txn.receipt_number,
                    description=f"Loan Repayment - Loan {loan.id}",
                    created_by=str(current_user.id),
                    lines=gl_lines,
                )

                await session.commit()
                await session.refresh(loan)

                return LoanResponse(
                    success=True,
                    message=f"Repayment of ₱{amount:,.2f} recorded successfully",
                    loan=LoanNode(
                        id=str(loan.id),
                        principal=loan.principal,
                        status=loan.status,
                        customerId=str(loan.customer_id),
                        productId=loan.product_id,
                        termMonths=loan.term_months,
                        approvedPrincipal=loan.approved_principal,
                        approvedRate=loan.approved_rate,
                        outstandingBalance=loan.outstanding_balance,
                        createdAt=loan.created_at,
                        updatedAt=loan.updated_at,
                        disbursedAt=loan.disbursed_at,
                    ),
                )
            except Exception as e:
                await session.rollback()
                return LoanResponse(success=False, message=f"Error: {str(e)}")

    @strawberry.mutation
    async def createSavingsTransaction(
        self, info: Info, input: SavingsTransactionCreateInput
    ) -> SavingsTransactionResponse:
        current_user = info.context.get("current_user")
        if not current_user:
            return SavingsTransactionResponse(success=False, message="Not authenticated")

        session_factory = get_async_session_local()
        async with session_factory() as session:
            try:
                # 1. Fetch account
                stmt = select(SavingsAccount).where(SavingsAccount.id == int(input.accountId))
                result = await session.execute(stmt)
                acc = result.scalar_one_or_none()
                if not acc:
                    return SavingsTransactionResponse(success=False, message="Account not found")

                # 2. Prepare transaction
                balance_before = acc.balance
                amount = input.amount
                
                if input.transactionType == "withdrawal":
                    if acc.balance < amount:
                        return SavingsTransactionResponse(success=False, message="Insufficient balance")
                    acc.balance -= amount
                elif input.transactionType == "deposit":
                    acc.balance += amount
                else:
                    return SavingsTransactionResponse(success=False, message="Invalid transaction type")

                new_tx = SavingsTransaction(
                    account_id=acc.id,
                    transaction_type=input.transactionType,
                    amount=amount,
                    balance_before=balance_before,
                    balance_after=acc.balance,
                    reference=input.reference,
                    description=input.description,
                )
                
                session.add(new_tx)
                
                # 3. Create Journal Entry for Double-Entry Accounting
                from .utils.savings_accounting_utils import post_savings_transaction_accounting
                reference_no = input.reference or f"SAV-{uuid.uuid4().hex[:8].upper()}"
                
                await post_savings_transaction_accounting(
                    session=session,
                    account_type=acc.account_type or "regular",
                    transaction_type=input.transactionType,
                    amount=Decimal(str(amount)),
                    reference_no=reference_no,
                    created_by=str(current_user.id) if current_user else None
                )
                
                await session.commit()
                await session.refresh(new_tx)

                return SavingsTransactionResponse(
                    success=True,
                    message=f"Savings {input.transactionType} successful",
                    transaction=SavingsTransactionNode(
                        id=str(new_tx.id),
                        accountId=str(new_tx.account_id),
                        amount=new_tx.amount,
                        accountType=new_tx.transaction_type, # mapping to existing field
                        reference=new_tx.reference,
                        description=new_tx.description,
                        createdAt=new_tx.created_at,
                    ),
                )
            except Exception as e:
                await session.rollback()
                return SavingsTransactionResponse(success=False, message=f"Error: {str(e)}")

    @strawberry.mutation
    async def assign_loan_collections_officer(
        self,
        info: Info,
        loanId: strawberry.ID,
        collectionsOfficerId: Optional[str] = None,
    ) -> MutationResponse:
        from .auth.rbac import require_approval_role

        user = require_approval_role(info)
        session_factory = get_async_session_local()
        async with session_factory() as session:
            try:
                loan = await session.get(LoanApplication, int(str(loanId)))
                if not loan:
                    return MutationResponse(success=False, message="Loan not found")
                loan.collections_officer = collectionsOfficerId
                await session.commit()
                return MutationResponse(success=True, message="Collections officer assigned")
            except Exception as e:
                await session.rollback()
                return MutationResponse(success=False, message=str(e))

    @strawberry.mutation
    async def assign_loan_collections_branch(
        self,
        info: Info,
        loanId: strawberry.ID,
        branchCode: Optional[str] = None,
    ) -> MutationResponse:
        from .auth.rbac import require_approval_role

        user = require_approval_role(info)
        session_factory = get_async_session_local()
        async with session_factory() as session:
            try:
                loan = await session.get(LoanApplication, int(str(loanId)))
                if not loan:
                    return MutationResponse(success=False, message="Loan not found")
                loan.assigned_collections_branch = branchCode
                await session.commit()
                return MutationResponse(success=True, message="Collections branch assigned")
            except Exception as e:
                await session.rollback()
                return MutationResponse(success=False, message=str(e))

    @strawberry.mutation
    async def create_collection(
        self, info: Info, input: CollectionCreateInput
    ) -> MutationResponse:
        current_user = info.context.get("current_user")
        if not current_user or current_user.role not in ("admin", "branch_manager", "collections_officer"):
            return MutationResponse(success=False, message="Not authorized")

        session_factory = get_async_session_local()
        async with session_factory() as session:
            try:
                new_collection = Collection(
                    customer_id=input.customerId,
                    amount=input.amount,
                    status="pending",
                    due_date=input.dueDate,
                    reference_number=input.referenceNumber,
                    collection_type=input.collectionType,
                    notes=input.notes,
                    collected_by=str(current_user.id),
                )
                session.add(new_collection)
                await session.commit()
                return MutationResponse(success=True, message="Collection created")
            except Exception as e:
                await session.rollback()
                return MutationResponse(success=False, message=str(e))

    @strawberry.mutation
    async def createGLAccount(
        self, info: Info, input: GLAccountCreateInput
    ) -> GLAccountResponse:
        from .chart_of_accounts import ChartOfAccountsMutation

        return await ChartOfAccountsMutation().create_gl_account(info, input)

    @strawberry.mutation
    async def createManualJournalEntry(
        self, info: Info, input: JournalEntryCreateInput
    ) -> JournalEntryResponse:
        from .chart_of_accounts import ChartOfAccountsMutation

        return await ChartOfAccountsMutation().create_manual_journal_entry(info, input)


schema = strawberry.Schema(query=Query, mutation=Mutation)
