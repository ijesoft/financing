import strawberry
from enum import Enum
from typing import List, Optional
from strawberry.types import Info
from .database import get_db
from .database.savings_crud import SavingsCRUD
from .basemodel.savings_model import (
    RegularSavings, HighYieldSavings, TimeDeposit, SavingsAccountBase,
    ShareCapitalAccount, GoalSavings, MinorSavingsAccount, JointAccount
)
from .models import UserInDB
from .customer import CustomerType, convert_customer_db_to_customer_type
from .database.customer_crud import CustomerCRUD
from decimal import Decimal
from datetime import datetime, timedelta


# Savings Account Types
@strawberry.enum
class SavingsAccountKind(Enum):
    REGULAR = "regular"
    HIGH_YIELD = "high_yield"
    TIME_DEPOSIT = "time_deposit"
    SHARE_CAPITAL = "share_capital"
    GOAL_SAVINGS = "goal_savings"
    MINOR_SAVINGS = "minor_savings"
    JOINT_ACCOUNT = "joint_account"


@strawberry.enum
class AccountStatus(Enum):
    ACTIVE = "active"
    FROZEN = "frozen"
    CLOSED = "closed"
    MATURED = "matured"


@strawberry.type
class SavingsAccountType:
    id: strawberry.ID
    account_number: str = strawberry.field(name="accountNumber")
    user_id: strawberry.ID = strawberry.field(name="userId")
    type: str
    balance: float
    currency: str
    opened_at: datetime = strawberry.field(name="openedAt")
    created_at: datetime = strawberry.field(name="createdAt")
    updated_at: datetime = strawberry.field(name="updatedAt")
    status: str
    interest_rate: Optional[float] = strawberry.field(name="interestRate", default=None)
    maturity_date: Optional[datetime] = strawberry.field(name="maturityDate", default=None)
    target_amount: Optional[float] = strawberry.field(name="targetAmount", default=None)
    target_date: Optional[datetime] = strawberry.field(name="targetDate", default=None)
    guardian_id: Optional[str] = strawberry.field(name="guardianId", default=None)
    secondary_owner_id: Optional[str] = strawberry.field(name="secondaryOwnerId", default=None)
    operation_mode: Optional[str] = strawberry.field(name="operationMode", default=None)
    customer: Optional[CustomerType] = None

    @strawberry.field
    async def customer(self, info: Info) -> Optional[CustomerType]:
        # Check if customer_info was already joined via aggregate lookup
        customer_info = getattr(self, "customer_info", None)
        if customer_info:
            # If it's a dict from MongoDB, convert it
            if isinstance(customer_info, dict):
                return convert_customer_db_to_customer_type(customer_info)
            return customer_info

        # Fallback to separate query if not pre-fetched
        db = get_db()
        customer_crud = CustomerCRUD(db.customers)
        
        customer_data = await customer_crud.get_customer_by_id(str(self.user_id))
        
        if customer_data:
            return convert_customer_db_to_customer_type(customer_data)
        return None

 

@strawberry.input
class SavingsAccountCreateInput:
    customer_id: strawberry.ID
    account_number: str
    type: str
    balance: float = 0.00
    currency: str = "PHP"
    status: str = "active"
    opened_at: datetime
    interest_rate: Optional[float] = None
    interest_paid_frequency: Optional[str] = None
    principal: Optional[float] = None
    term_days: Optional[int] = None
    target_amount: Optional[float] = None
    target_date: Optional[datetime] = None
    goal_name: Optional[str] = None
    guardian_id: Optional[str] = None
    guardian_name: Optional[str] = None
    minor_date_of_birth: Optional[datetime] = None
    secondary_owner_id: Optional[str] = None
    secondary_owner_name: Optional[str] = None
    operation_mode: Optional[str] = "EITHER"

@strawberry.type
class SavingsAccountResponse:
    success: bool
    message: str
    account: Optional[SavingsAccountType] = None

@strawberry.type
class SavingsAccountsResponse:
    success: bool
    message: str
    accounts: List[SavingsAccountType]
    total: int

# Transaction Types
@strawberry.type
class TransactionType:
    id: strawberry.ID
    account_id: strawberry.ID = strawberry.field(name="accountId")
    transaction_type: str = strawberry.field(name="transactionType") # e.g., "deposit", "withdrawal"
    amount: float
    timestamp: datetime
    notes: Optional[str] = None

@strawberry.input
class TransactionCreateInput:
    account_id: strawberry.ID
    amount: float
    notes: Optional[str] = None

@strawberry.type
class TransactionResponse:
    success: bool
    message: str
    transaction: Optional[TransactionType] = None

@strawberry.type
class TransactionsResponse:
    success: bool
    message: str
    transactions: List[TransactionType]
    total: int


def map_db_account_to_strawberry_type(account_data: SavingsAccountBase) -> SavingsAccountType:
    """Maps a SavingsAccountBase object to a SavingsAccountType."""
    return SavingsAccountType(
        id=strawberry.ID(str(account_data.id)),
        account_number=account_data.account_number,
        user_id=strawberry.ID(str(account_data.user_id)),
        type=account_data.type,
        balance=account_data.balance,
        currency=account_data.currency,
        opened_at=account_data.opened_at,
        status=account_data.status,
        created_at=account_data.created_at,
        updated_at=account_data.updated_at
    )

@strawberry.type
class SavingsQuery:
    # @strawberry.field
    # async def savingsAccount(self, info: Info, account_id: strawberry.ID) -> SavingsAccountResponse:
    #     from .savings import SavingsQuery
    #     return await SavingsQuery().savingsAccount(info, account_id)

    # @strawberry.field
    # async def savingsAccounts(self, info: Info) -> SavingsAccountsResponse:
    #     from .savings import SavingsQuery
    #     return await SavingsQuery().savingsAccounts(info)



    @strawberry.field
    async def savingsAccount(self, info: Info, account_id: strawberry.ID) -> SavingsAccountResponse:
        current_user: UserInDB = info.context.get("current_user")
        if not current_user:
            return SavingsAccountResponse(success=False, message="Not authenticated")

        db = get_db()
        savings_crud = SavingsCRUD(db.savings)
        account_data = await savings_crud.get_savings_account_by_id(str(account_id))

        if not account_data:
            return SavingsAccountResponse(success=False, message="Account not found")

        # Branch check for staff
        if current_user.role != "admin" and current_user.role != "customer":
            customer_crud = CustomerCRUD(db.customers)
            customer_db = await customer_crud.get_customer_by_id(str(account_data.user_id))
            if customer_db and customer_db.branch != current_user.assigned_branch:
                return SavingsAccountResponse(
                    success=False, 
                    message=f"Access denied: Account belongs to branch {customer_db.branch}"
                )

        # Basic authorization: check if the account belongs to the current user
        # if str(account_data.user_id) != str(current_user.id):
        #     return SavingsAccountResponse(success=False, message="Not authorized to view this account")
            
        account = map_db_account_to_strawberry_type(account_data)
        return SavingsAccountResponse(success=True, message="Account retrieved", account=account)

    @strawberry.field
    async def savingsAccounts(self, info: Info, searchTerm: Optional[str] = None, customerId: Optional[str] = None) -> SavingsAccountsResponse:
        current_user: UserInDB = info.context.get("current_user")
        if not current_user:
            return SavingsAccountsResponse(success=False, message="Not authenticated", accounts=[], total=0)

        branch_filter = None
        if current_user.role != "admin" and current_user.role != "customer":
            branch_filter = current_user.assigned_branch
            if not branch_filter:
                return SavingsAccountsResponse(success=True, message="No branch assigned to user", accounts=[], total=0)

        db = get_db()
        savings_crud = SavingsCRUD(db.savings)
        # Use searchTerm and branch_filter for server-side filtering
        accounts_data = await savings_crud.get_all_savings_accounts(
            search_term=searchTerm, 
            customer_id=customerId or (str(current_user.id) if current_user.role == "customer" else None),
            branch=branch_filter
        )
        accounts = [map_db_account_to_strawberry_type(acc) for acc in accounts_data]
        return SavingsAccountsResponse(success=True, message="Accounts retrieved", accounts=accounts, total=len(accounts))

@strawberry.type
class SavingsMutation:
    @strawberry.field
    async def createSavingsAccount(self, info: Info, input: SavingsAccountCreateInput) -> SavingsAccountResponse:
        current_user: UserInDB = info.context.get("current_user")
        if not current_user:
            return SavingsAccountResponse(success=False, message="Not authenticated")

        db = get_db()
        savings_crud = SavingsCRUD(db.savings)

        account_data = {
            "account_number": input.account_number,
            "user_id": str(input.customer_id),
            "balance": input.balance,
            "opened_at": input.opened_at,
            "currency": input.currency,
            "status": input.status,
            "type": input.type
        }

        if input.type == "regular":
            account_to_create = RegularSavings(**account_data)
        elif input.type == "high_yield":
            if input.interest_rate is not None:
                account_data["interest_rate"] = input.interest_rate
            if input.interest_paid_frequency is not None:
                account_data["interest_paid_frequency"] = input.interest_paid_frequency
            account_to_create = HighYieldSavings(**account_data)
        elif input.type == "time_deposit":
            if input.principal is not None:
                account_data["principal"] = input.principal
            if input.term_days is not None:
                account_data["term_days"] = input.term_days
                account_data["maturity_date"] = input.opened_at + timedelta(days=input.term_days)
            if input.interest_rate is not None:
                account_data["interest_rate"] = input.interest_rate
            account_to_create = TimeDeposit(**account_data)
        elif input.type == "share_capital":
            account_data["membership_date"] = input.opened_at
            account_data["minimum_share"] = 100.00
            account_data["share_value"] = 100.00
            account_data["total_shares"] = int(input.balance / 100) if input.balance > 0 else 0
            account_to_create = ShareCapitalAccount(**account_data)
        elif input.type == "goal_savings":
            account_data["target_amount"] = input.target_amount or 0.0
            account_data["target_date"] = input.target_date or (input.opened_at + timedelta(days=365))
            account_data["goal_name"] = input.goal_name or "Savings Goal"
            account_data["current_savings"] = input.balance
            account_data["interest_rate"] = input.interest_rate or 1.50
            account_to_create = GoalSavings(**account_data)
        elif input.type == "minor_savings":
            if not input.guardian_id or not input.guardian_name:
                return SavingsAccountResponse(success=False, message="Guardian info required for minor account")
            account_data["guardian_id"] = input.guardian_id
            account_data["guardian_name"] = input.guardian_name
            account_data["minor_date_of_birth"] = input.minor_date_of_birth or input.opened_at
            account_data["interest_rate"] = input.interest_rate or 0.50
            account_to_create = MinorSavingsAccount(**account_data)
        elif input.type == "joint_account":
            if not input.secondary_owner_id or not input.secondary_owner_name:
                return SavingsAccountResponse(success=False, message="Secondary owner info required for joint account")
            account_data["primary_owner_id"] = str(input.customer_id)
            account_data["secondary_owner_id"] = input.secondary_owner_id
            account_data["secondary_owner_name"] = input.secondary_owner_name
            account_data["operation_mode"] = input.operation_mode or "EITHER"
            account_to_create = JointAccount(**account_data)
        else:
            return SavingsAccountResponse(success=False, message=f"Invalid account type: {input.type}")
        
        created_account = await savings_crud.create_savings_account(account_to_create)
        created_account_data = await savings_crud.get_savings_account_by_id(str(created_account.id))

        # Banking-grade: opening deposit must hit the GL.
        # DR 1010 (Cash in Bank) / CR 2020 (Savings Deposits Payable)
        if input.balance and float(input.balance) > 0:
            try:
                from .accounting import create_journal_entry
                amount = float(input.balance)
                await create_journal_entry(
                    db,
                    reference_no=f"SA-OPEN-{input.account_number}",
                    description=f"Opening deposit for savings account {input.account_number}",
                    lines=[
                        {"account_code": "1010", "debit": amount, "credit": 0},
                        {"account_code": "2020", "debit": 0, "credit": amount},
                    ],
                    created_by=str(getattr(current_user, "id", None) or ""),
                )
            except Exception:
                pass

        account = map_db_account_to_strawberry_type(created_account_data)

        return SavingsAccountResponse(success=True, message="Savings account created", account=account)


@strawberry.input
class FundTransferInput:
    from_account_id: strawberry.ID
    to_account_id: strawberry.ID
    amount: float
    notes: Optional[str] = None


@strawberry.input
class StandingOrderInput:
    source_account_id: strawberry.ID
    destination_account_id: strawberry.ID
    amount: float
    frequency: str
    start_date: datetime
    end_date: Optional[datetime] = None
    is_active: bool = True


@strawberry.type
class FundTransferResponse:
    success: bool
    message: str
    transaction_id: Optional[str] = None


@strawberry.type
class StandingOrderResponse:
    success: bool
    message: str
    standing_order_id: Optional[str] = None


@strawberry.type
class StatementData:
    account_number: str
    period_start: datetime
    period_end: datetime
    opening_balance: float
    closing_balance: float
    total_deposits: float
    total_withdrawals: float
    total_credits: float
    total_debits: float
    transactions: List[TransactionType]


@strawberry.type
class StatementResponse:
    success: bool
    message: str
    statement: Optional[StatementData] = None
