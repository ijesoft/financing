"""
PostgreSQL CRUD operations for core entities.
Replaces MongoDB-based CRUD with SQLAlchemy async operations.
"""

from typing import List, Optional
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, desc, func

from ..database.pg_core_models import User, Customer, SavingsAccount, StandingOrder
from ..database.pg_loan_models import PGLoanProduct, LoanApplication, LoanTransaction, AmortizationSchedule
from ..models import UserCreate, UserUpdate, UserInDB, CustomerCreate, CustomerUpdate, CustomerInDB
from ..auth.security import get_password_hash, verify_password


# ---------------------------------------------------------------------------
# User CRUD (PostgreSQL)
# ---------------------------------------------------------------------------
class UserCRUD:
    def __init__(self, db: AsyncSession):
        self.db = db

    async def create_user(self, user: UserCreate) -> UserInDB:
        hashed_password = get_password_hash(user.password)

        db_user = User(
            email=user.email,
            username=user.username,
            full_name=user.full_name,
            role=user.role,
            branch_id=user.branch_id,
            branch_code=user.branch_code,
            hashed_password=hashed_password,
            is_active=True,
            is_superuser=False,
        )

        self.db.add(db_user)
        await self.db.commit()
        await self.db.refresh(db_user)

        return UserInDB(
            id=str(db_user.uuid),
            email=db_user.email,
            username=db_user.username,
            full_name=db_user.full_name,
            role=db_user.role,
            branch_id=db_user.branch_id,
            branch_code=db_user.branch_code,
            is_active=db_user.is_active,
            created_at=db_user.created_at,
            updated_at=db_user.updated_at,
            hashed_password=db_user.hashed_password,
        )

    async def get_user_by_id(self, user_id: str) -> Optional[UserInDB]:
        result = await self.db.execute(
            select(User).where(User.uuid == user_id)
        )
        user = result.scalar_one_or_none()
        if user:
            return UserInDB(
                id=str(user.uuid),
                email=user.email,
                username=user.username,
                full_name=user.full_name,
                role=user.role,
                branch_id=user.branch_id,
                branch_code=user.branch_code,
                is_active=user.is_active,
                created_at=user.created_at,
                updated_at=user.updated_at,
                hashed_password=user.hashed_password,
            )
        return None

    async def get_user_by_email(self, email: str) -> Optional[UserInDB]:
        result = await self.db.execute(
            select(User).where(User.email == email)
        )
        user = result.scalar_one_or_none()
        if user:
            return UserInDB(
                id=str(user.uuid),
                email=user.email,
                username=user.username,
                full_name=user.full_name,
                role=user.role,
                branch_id=user.branch_id,
                branch_code=user.branch_code,
                is_active=user.is_active,
                created_at=user.created_at,
                updated_at=user.updated_at,
                hashed_password=user.hashed_password,
            )
        return None

    async def get_user_by_username(self, username: str) -> Optional[UserInDB]:
        result = await self.db.execute(
            select(User).where(User.username == username)
        )
        user = result.scalar_one_or_none()
        if user:
            return UserInDB(
                id=str(user.uuid),
                email=user.email,
                username=user.username,
                full_name=user.full_name,
                role=user.role,
                branch_id=user.branch_id,
                branch_code=user.branch_code,
                is_active=user.is_active,
                created_at=user.created_at,
                updated_at=user.updated_at,
                hashed_password=user.hashed_password,
            )
        return None

    async def get_users(self, skip: int = 0, limit: int = 100) -> List[UserInDB]:
        result = await self.db.execute(
            select(User).offset(skip).limit(limit)
        )
        users = result.scalars().all()
        return [
            UserInDB(
                id=str(user.uuid),
                email=user.email,
                username=user.username,
                full_name=user.full_name,
                role=user.role,
                branch_id=user.branch_id,
                branch_code=user.branch_code,
                is_active=user.is_active,
                created_at=user.created_at,
                updated_at=user.updated_at,
                hashed_password=user.hashed_password,
            )
            for user in users
        ]

    async def count_users(self) -> int:
        result = await self.db.execute(select(func.count(User.id)))
        return result.scalar_one()

    async def update_user(self, user_id: str, user_update: UserUpdate) -> Optional[UserInDB]:
        result = await self.db.execute(
            select(User).where(User.uuid == user_id)
        )
        user = result.scalar_one_or_none()
        if not user:
            return None

        update_data = user_update.model_dump(exclude_unset=True)
        
        if "password" in update_data:
            update_data["hashed_password"] = get_password_hash(user_update.password)
            del update_data["password"]

        for field, value in update_data.items():
            if value is not None:
                setattr(user, field, value)

        await self.db.commit()
        await self.db.refresh(user)

        return UserInDB(
            id=str(user.uuid),
            email=user.email,
            username=user.username,
            full_name=user.full_name,
            role=user.role,
            branch_id=user.branch_id,
            branch_code=user.branch_code,
            is_active=user.is_active,
            created_at=user.created_at,
            updated_at=user.updated_at,
            hashed_password=user.hashed_password,
        )

    async def delete_user(self, user_id: str) -> bool:
        result = await self.db.execute(
            select(User).where(User.uuid == user_id)
        )
        user = result.scalar_one_or_none()
        if not user:
            return False

        await self.db.delete(user)
        await self.db.commit()
        return True


# ---------------------------------------------------------------------------
# Customer CRUD (PostgreSQL)
# ---------------------------------------------------------------------------
class CustomerCRUD:
    def __init__(self, db: AsyncSession):
        self.db = db

    async def create_customer(self, customer: CustomerCreate) -> CustomerInDB:
        db_customer = Customer(
            customer_type=customer.customer_type,
            last_name=customer.last_name,
            first_name=customer.first_name,
            middle_name=customer.middle_name,
            display_name=customer.display_name,
            tin_no=customer.tin_no,
            sss_no=customer.sss_no,
            birth_date=customer.birth_date,
            birth_place=customer.birth_place,
            mobile_number=customer.mobile_number,
            email_address=customer.email_address,
            permanent_address=customer.permanent_address,
            employer_name_address=customer.employer_name_address,
            job_title=customer.job_title,
            salary_range=customer.salary_range,
            company_name=customer.company_name,
            company_address=customer.company_address,
            branch_id=customer.branch_id,
            branch_code=customer.branch_code,
            is_active=True,
        )

        self.db.add(db_customer)
        await self.db.commit()
        await self.db.refresh(db_customer)

        return CustomerInDB(
            id=db_customer.id,
            customer_type=db_customer.customer_type,
            last_name=db_customer.last_name,
            first_name=db_customer.first_name,
            middle_name=db_customer.middle_name,
            display_name=db_customer.display_name,
            tin_no=db_customer.tin_no,
            sss_no=db_customer.sss_no,
            birth_date=db_customer.birth_date,
            birth_place=db_customer.birth_place,
            mobile_number=db_customer.mobile_number,
            email_address=db_customer.email_address,
            permanent_address=db_customer.permanent_address,
            employer_name_address=db_customer.employer_name_address,
            job_title=db_customer.job_title,
            salary_range=db_customer.salary_range,
            company_name=db_customer.company_name,
            company_address=db_customer.company_address,
            branch=db_customer.branch_code,
            created_at=db_customer.created_at,
            updated_at=db_customer.updated_at,
        )

    async def get_customer_by_id(self, customer_id: int) -> Optional[CustomerInDB]:
        result = await self.db.execute(
            select(Customer).where(Customer.id == customer_id)
        )
        customer = result.scalar_one_or_none()
        if customer:
            return CustomerInDB(
                id=customer.id,
                customer_type=customer.customer_type,
                last_name=customer.last_name,
                first_name=customer.first_name,
                middle_name=customer.middle_name,
                display_name=customer.display_name,
                tin_no=customer.tin_no,
                sss_no=customer.sss_no,
                birth_date=customer.birth_date,
                birth_place=customer.birth_place,
                mobile_number=customer.mobile_number,
                email_address=customer.email_address,
                permanent_address=customer.permanent_address,
                employer_name_address=customer.employer_name_address,
                job_title=customer.job_title,
                salary_range=customer.salary_range,
                company_name=customer.company_name,
                company_address=customer.company_address,
                branch=customer.branch_code,
                created_at=customer.created_at,
                updated_at=customer.updated_at,
            )
        return None

    async def get_customers(self, skip: int = 0, limit: int = 100, branch_id: Optional[int] = None) -> List[CustomerInDB]:
        query = select(Customer)
        if branch_id:
            query = query.where(Customer.branch_id == branch_id)
        
        result = await self.db.execute(query.offset(skip).limit(limit))
        customers = result.scalars().all()
        
        return [
            CustomerInDB(
                id=customer.id,
                customer_type=customer.customer_type,
                last_name=customer.last_name,
                first_name=customer.first_name,
                middle_name=customer.middle_name,
                display_name=customer.display_name,
                tin_no=customer.tin_no,
                sss_no=customer.sss_no,
                birth_date=customer.birth_date,
                birth_place=customer.birth_place,
                mobile_number=customer.mobile_number,
                email_address=customer.email_address,
                permanent_address=customer.permanent_address,
                employer_name_address=customer.employer_name_address,
                job_title=customer.job_title,
                salary_range=customer.salary_range,
                company_name=customer.company_name,
                company_address=customer.company_address,
                branch=customer.branch_code,
                created_at=customer.created_at,
                updated_at=customer.updated_at,
            )
            for customer in customers
        ]

    async def count_customers(self, branch_id: Optional[int] = None) -> int:
        query = select(func.count(Customer.id))
        if branch_id:
            query = query.where(Customer.branch_id == branch_id)
        
        result = await self.db.execute(query)
        return result.scalar_one()

    async def update_customer(self, customer_id: int, customer_update: CustomerUpdate) -> Optional[CustomerInDB]:
        result = await self.db.execute(
            select(Customer).where(Customer.id == customer_id)
        )
        customer = result.scalar_one_or_none()
        if not customer:
            return None

        update_data = customer_update.model_dump(exclude_unset=True)

        for field, value in update_data.items():
            if value is not None:
                setattr(customer, field, value)

        await self.db.commit()
        await self.db.refresh(customer)

        return CustomerInDB(
            id=customer.id,
            customer_type=customer.customer_type,
            last_name=customer.last_name,
            first_name=customer.first_name,
            middle_name=customer.middle_name,
            display_name=customer.display_name,
            tin_no=customer.tin_no,
            sss_no=customer.sss_no,
            birth_date=customer.birth_date,
            birth_place=customer.birth_place,
            mobile_number=customer.mobile_number,
            email_address=customer.email_address,
            permanent_address=customer.permanent_address,
            employer_name_address=customer.employer_name_address,
            job_title=customer.job_title,
            salary_range=customer.salary_range,
            company_name=customer.company_name,
            company_address=customer.company_address,
            branch=customer.branch_code,
            created_at=customer.created_at,
            updated_at=customer.updated_at,
        )

    async def delete_customer(self, customer_id: int) -> bool:
        result = await self.db.execute(
            select(Customer).where(Customer.id == customer_id)
        )
        customer = result.scalar_one_or_none()
        if not customer:
            return False

        await self.db.delete(customer)
        await self.db.commit()
        return True


# ---------------------------------------------------------------------------
# Savings Account CRUD (PostgreSQL)
# ---------------------------------------------------------------------------
class SavingsAccountCRUD:
    def __init__(self, db: AsyncSession):
        self.db = db

    async def create_savings_account(self, account: SavingsAccount) -> SavingsAccount:
        self.db.add(account)
        await self.db.commit()
        await self.db.refresh(account)
        return account

    async def get_savings_account_by_id(self, account_id: int) -> Optional[SavingsAccount]:
        result = await self.db.execute(
            select(SavingsAccount).where(SavingsAccount.id == account_id)
        )
        return result.scalar_one_or_none()

    async def get_savings_account_by_number(self, account_number: str) -> Optional[SavingsAccount]:
        result = await self.db.execute(
            select(SavingsAccount).where(SavingsAccount.account_number == account_number)
        )
        return result.scalar_one_or_none()

    async def get_savings_accounts_by_customer(self, customer_id: int, skip: int = 0, limit: int = 100) -> List[SavingsAccount]:
        result = await self.db.execute(
            select(SavingsAccount)
            .where(SavingsAccount.customer_id == customer_id)
            .offset(skip)
            .limit(limit)
        )
        return result.scalars().all()

    async def update_savings_account(self, account_id: int, update_data: dict) -> Optional[SavingsAccount]:
        result = await self.db.execute(
            select(SavingsAccount).where(SavingsAccount.id == account_id)
        )
        account = result.scalar_one_or_none()
        if not account:
            return None

        for field, value in update_data.items():
            if value is not None:
                setattr(account, field, value)

        await self.db.commit()
        await self.db.refresh(account)
        return account

    async def delete_savings_account(self, account_id: int) -> bool:
        result = await self.db.execute(
            select(SavingsAccount).where(SavingsAccount.id == account_id)
        )
        account = result.scalar_one_or_none()
        if not account:
            return False

        await self.db.delete(account)
        await self.db.commit()
        return True