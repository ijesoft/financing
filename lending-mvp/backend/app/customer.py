import json
import re
import strawberry
from typing import List, Optional
from strawberry.types import Info
from fastapi import HTTPException, status
from datetime import datetime, date, timezone

from starlette.requests import Request

from .models import CustomerInDB, CustomerCreate, CustomerUpdate, PyObjectId, UserInDB
from .database.customer_crud import CustomerCRUD
from .database.pg_models import Beneficiary, CustomerActivity
from .database.postgres import AsyncSessionLocal
from .auth.rbac import get_sql_branch_filter, assert_branch_access, require_management_role
from sqlalchemy import select


# KYC + Risk GraphQL types
@strawberry.type
class KYCStatusType:
    status: str           # "pending" | "submitted" | "verified" | "rejected"
    risk_score: Optional[float] = strawberry.field(name="riskScore", default=None)

# Beneficiary
@strawberry.type
class BeneficiaryType:
    id: int
    customer_id: str = strawberry.field(name="customerId")
    full_name: str = strawberry.field(name="fullName")
    relationship: str
    contact_number: Optional[str] = strawberry.field(name="contactNumber", default=None)
    email: Optional[str] = None
    address: Optional[str] = None
    is_primary: bool = strawberry.field(name="isPrimary", default=False)
    created_at: datetime = strawberry.field(name="createdAt")

@strawberry.input
class BeneficiaryCreateInput:
    customer_id: str
    full_name: str
    relationship: str
    contact_number: Optional[str] = None
    email: Optional[str] = None
    address: Optional[str] = None
    is_primary: Optional[bool] = False

@strawberry.type
class BeneficiaryResponse:
    success: bool
    message: str
    beneficiary: Optional[BeneficiaryType] = None

@strawberry.type
class BeneficiariesResponse:
    success: bool
    message: str
    beneficiaries: List[BeneficiaryType]

# Customer activity log
@strawberry.type
class CustomerActivityType:
    id: int
    customer_id: str = strawberry.field(name="customerId")
    actor_username: Optional[str] = strawberry.field(name="actorUsername", default=None)
    action: str
    detail: Optional[str] = None
    created_at: datetime = strawberry.field(name="createdAt")

@strawberry.type
class CustomerActivityResponse:
    success: bool
    message: str
    activities: List[CustomerActivityType]

# Customer Types
@strawberry.type
class CustomerType:
    id: strawberry.ID
    customer_type: str = strawberry.field(name="customerType")
    last_name: Optional[str] = strawberry.field(name="lastName", default=None)
    first_name: Optional[str] = strawberry.field(name="firstName", default=None)
    display_name: str = strawberry.field(name="displayName")
    middle_name: Optional[str] = strawberry.field(name="middleName", default=None)
    tin_no: Optional[str] = strawberry.field(name="tinNo", default=None)
    sss_no: Optional[str] = strawberry.field(name="sssNo", default=None)
    permanent_address: Optional[str] = strawberry.field(name="permanentAddress", default=None)
    birth_date: Optional[date] = strawberry.field(name="birthDate", default=None)
    birth_place: Optional[str] = strawberry.field(name="birthPlace", default=None)
    mobile_number: Optional[str] = strawberry.field(name="mobileNumber", default=None)
    email_address: str = strawberry.field(name="emailAddress")
    employer_name_address: Optional[str] = strawberry.field(name="employerNameAddress", default=None)
    job_title: Optional[str] = strawberry.field(name="jobTitle", default=None)
    salary_range: Optional[str] = strawberry.field(name="salaryRange", default=None)
    created_at: datetime = strawberry.field(name="createdAt")
    updated_at: datetime = strawberry.field(name="updatedAt")
    company_name: Optional[str] = strawberry.field(name="companyName", default=None)
    company_address: Optional[str] = strawberry.field(name="companyAddress", default=None)
    branch: str
    # Phase 1 additions
    kyc_status: Optional[str] = strawberry.field(name="kycStatus", default="pending")
    risk_score: Optional[float] = strawberry.field(name="riskScore", default=None)
    customer_category: Optional[str] = strawberry.field(name="customerCategory", default="individual")

@strawberry.input
class CustomerCreateInput:
    customer_type: str # Added customer_type
    last_name: Optional[str] = None # Made optional
    first_name: Optional[str] = None # Made optional
    middle_name: Optional[str] = None
    display_name: str
    tin_no: Optional[str] = None
    sss_no: Optional[str] = None
    permanent_address: Optional[str] = None
    birth_date: Optional[datetime] = None
    birth_place: Optional[str] = None
    mobile_number: Optional[str] = None
    email_address: str
    employer_name_address: Optional[str] = None
    job_title: Optional[str] = None
    salary_range: Optional[str] = None
    company_name: Optional[str] = None
    company_address: Optional[str] = None
    branch: str

@strawberry.input
class CustomerUpdateInput:
    customer_type: str # Added customer_type
    last_name: Optional[str] = None
    first_name: Optional[str] = None
    middle_name: Optional[str] = None
    tin_no: Optional[str] = None
    sss_no: Optional[str] = None
    permanent_address: Optional[str] = None
    birth_date: Optional[datetime] = None
    birth_place: Optional[str] = None
    mobile_number: Optional[str] = None
    email_address: Optional[str] = None
    employer_name_address: Optional[str] = None
    job_title: Optional[str] = None
    salary_range: Optional[str] = None
    company_name: Optional[str] = None
    company_address: Optional[str] = None
    branch: str
    display_name: str

@strawberry.type
class CustomerResponse:
    success: bool
    message: str
    customer: Optional[CustomerType] = None

@strawberry.type
class CustomersResponse:
    success: bool
    message: str
    customers: List[CustomerType]
    total: int


@strawberry.type
class Query:
    @strawberry.field
    async def customers(
        self,
        info: Info,
        skip: int = 0,
        limit: int = 100,
        search_term: Optional[str] = None,
    ) -> CustomersResponse:
        current_user: UserInDB = info.context.get("current_user")
        if not current_user:
            return CustomersResponse(success=False, message="Not authenticated", customers=[], total=0)
        try:
            from .auth.rbac import get_mongo_branch_filter
            customer_crud = CustomerCRUD(AsyncSessionLocal())
            # Apply branch filter based on caller's role
            branch_filter = get_mongo_branch_filter(current_user)
            customers_db = await customer_crud.get_customers(skip=skip, limit=limit, search_term=search_term, extra_filter=branch_filter)
            total = await customer_crud.count_customers(search_term=search_term, extra_filter=branch_filter)
            customers = [convert_customer_db_to_customer_type(customer_db) for customer_db in customers_db]
            return CustomersResponse(success=True, message="Customers retrieved successfully", customers=customers, total=total)
        except Exception as e:
            return CustomersResponse(success=False, message=f"Error retrieving customers: {str(e)}", customers=[], total=0)

    @strawberry.field
    async def customer_by_id(self, info: Info, customer_id: strawberry.ID) -> CustomerResponse:
        """Get customer by ID. Branch-scoped for non-admin roles."""
        current_user: UserInDB = info.context.get("current_user")
        if not current_user or current_user.role not in ("admin", "loan_officer", "branch_manager", "teller", "auditor"):
            raise Exception("Not authorized")
        try:
            customers_collection = get_customers_collection()
            customer_crud = CustomerCRUD(customers_collection)
            customer_db = await customer_crud.get_customer_by_id(str(customer_id))
            if not customer_db:
                return CustomerResponse(success=False, message="Customer not found")
            # Enforce branch access for non-admin/non-auditor roles
            assert_branch_access(current_user, getattr(customer_db, 'branch', None))
            return CustomerResponse(success=True, message="OK", customer=convert_customer_db_to_customer_type(customer_db))
        except HTTPException as he:
            raise he
        except Exception as e:
            return CustomerResponse(success=False, message=f"Error: {str(e)}")

    @strawberry.field
    async def beneficiaries(self, info: Info, customer_id: str) -> BeneficiariesResponse:
        """Get beneficiaries for a customer."""
        current_user = info.context.get("current_user")
        if not current_user:
            raise Exception("Not authenticated")
        async with AsyncSessionLocal() as session:
            result = await session.execute(
                select(Beneficiary).where(Beneficiary.customer_id == customer_id).order_by(Beneficiary.is_primary.desc())
            )
            rows = result.scalars().all()
        beneficiaries = [
            BeneficiaryType(
                id=r.id, customer_id=r.customer_id, full_name=r.full_name,
                relationship=r.relationship, contact_number=r.contact_number,
                email=r.email, address=r.address, is_primary=r.is_primary, created_at=r.created_at,
            ) for r in rows
        ]
        return BeneficiariesResponse(success=True, message="OK", beneficiaries=beneficiaries)

    @strawberry.field
    async def customer_activities(self, info: Info, customer_id: str) -> CustomerActivityResponse:
        """Get activity log for a customer."""
        current_user = info.context.get("current_user")
        if not current_user:
            raise Exception("Not authenticated")
        async with AsyncSessionLocal() as session:
            result = await session.execute(
                select(CustomerActivity)
                .where(CustomerActivity.customer_id == customer_id)
                .order_by(CustomerActivity.created_at.desc())
                .limit(100)
            )
            rows = result.scalars().all()
        activities = [
            CustomerActivityType(
                id=r.id, customer_id=r.customer_id, actor_username=r.actor_username,
                action=r.action, detail=r.detail, created_at=r.created_at,
            ) for r in rows
        ]
        return CustomerActivityResponse(success=True, message="OK", activities=activities)


def convert_customer_db_to_customer_type(customer_db: CustomerInDB) -> "CustomerType":
    """Convert CustomerInDB to CustomerType schema"""
    return CustomerType(
        id=strawberry.ID(str(customer_db.id)),
        last_name=customer_db.last_name,
        first_name=customer_db.first_name,
        display_name=customer_db.display_name,
        middle_name=customer_db.middle_name,
        tin_no=customer_db.tin_no,
        sss_no=customer_db.sss_no,
        permanent_address=customer_db.permanent_address,
        birth_date=customer_db.birth_date,
        birth_place=customer_db.birth_place,
        mobile_number=customer_db.mobile_number,
        email_address=customer_db.email_address,
        employer_name_address=customer_db.employer_name_address,
        job_title=customer_db.job_title,
        salary_range=customer_db.salary_range,
        created_at=customer_db.created_at,
        updated_at=customer_db.updated_at,
        company_name=customer_db.company_name,
        company_address=customer_db.company_address,
        customer_type=customer_db.customer_type,
        branch=customer_db.branch
    )


@strawberry.type
class Mutation:
    @strawberry.field
    async def create_customer(self, info: Info, input: CustomerCreateInput) -> CustomerResponse:
        current_user = info.context.get("current_user")
        if current_user is None:
            raise Exception("Not authenticated")
        if current_user.role not in ("admin", "loan_officer", "branch_manager"):
            raise Exception("Not authorized")

        try:
            customers_collection = get_customers_collection()
            customer_crud = CustomerCRUD(customers_collection)

            # Email uniqueness check
            if await customer_crud.get_customer_by_email(input.email_address):
                return CustomerResponse(success=False, message="Customer with this email already exists")

            # For branch-scoped roles, auto-assign to their branch (ignore client-sent branch)
            if current_user.role in ("loan_officer", "branch_manager"):
                user_branch = getattr(current_user, 'branch_code', None)
                if user_branch:
                    input.branch = user_branch

            # ── Duplicate name detection ──────────────────────────────────────
            pattern = re.compile(re.escape(input.display_name.strip()), re.IGNORECASE)
            similar_cursor = customers_collection.find(
                {"display_name": {"$regex": pattern}},
                {"display_name": 1, "_id": 1},
            ).limit(5)
            similar = await similar_cursor.to_list(length=5)
            duplicate_names = [s["display_name"] for s in similar]
            warning = ""
            if duplicate_names:
                warning = f"Warning: Similar names found — {', '.join(duplicate_names)}. "

            # Store branch_code for scoping
            customer_data = strawberry.asdict(input)
            # Ensure branch_code field is also stored for scoping
            if 'branch' in customer_data:
                customer_data['branch_code'] = customer_data['branch']
            customer_create = CustomerCreate(**customer_data)
            customer_db = await customer_crud.create_customer(customer_create)
            customer = convert_customer_db_to_customer_type(customer_db)

            # Log activity
            async with AsyncSessionLocal() as session:
                session.add(CustomerActivity(
                    customer_id=str(customer_db.id),
                    actor_user_id=str(current_user.id),
                    actor_username=current_user.username,
                    action="created",
                    detail=json.dumps({"display_name": customer_db.display_name, "branch": customer_db.branch}),
                    created_at=datetime.now(timezone.utc),
                ))
                await session.commit()

            return CustomerResponse(
                success=True,
                message=f"{warning}Customer created successfully",
                customer=customer,
            )
        except Exception as e:
            return CustomerResponse(success=False, message=f"Error creating customer: {str(e)}")

    @strawberry.field
    async def update_customer(self, info: Info, customer_id: strawberry.ID, input: CustomerUpdateInput) -> CustomerResponse:
        """Update an existing customer."""
        current_user: UserInDB = info.context.get("current_user")
        if not current_user or current_user.role not in ("admin", "loan_officer", "branch_manager"):
            raise Exception("Not authorized")
        try:
            customers_collection = get_customers_collection()
            customer_crud = CustomerCRUD(customers_collection)
            customer_update = CustomerUpdate(**strawberry.asdict(input))
            customer_db = await customer_crud.update_customer(str(customer_id), customer_update)
            if not customer_db:
                return CustomerResponse(success=False, message="Customer not found")

            # Log activity
            async with AsyncSessionLocal() as session:
                session.add(CustomerActivity(
                    customer_id=str(customer_id),
                    actor_user_id=str(current_user.id),
                    actor_username=current_user.username,
                    action="updated",
                    detail=json.dumps({"updated_fields": list(strawberry.asdict(input).keys())}),
                    created_at=datetime.now(timezone.utc),
                ))
                await session.commit()

            return CustomerResponse(success=True, message="Customer updated", customer=convert_customer_db_to_customer_type(customer_db))
        except Exception as e:
            return CustomerResponse(success=False, message=f"Error: {str(e)}")

    @strawberry.field
    async def delete_customer(self, info: Info, customer_id: strawberry.ID) -> CustomerResponse:
        """Delete a customer."""
        current_user: UserInDB = info.context.get("current_user")
        if not current_user or current_user.role != "admin":
            raise Exception("Not authorized")
        try:
            customers_collection = get_customers_collection()
            customer_crud = CustomerCRUD(customers_collection)
            success = await customer_crud.delete_customer(str(customer_id))
            if not success:
                return CustomerResponse(success=False, message="Customer not found")
            return CustomerResponse(success=True, message="Customer deleted")
        except Exception as e:
            return CustomerResponse(success=False, message=f"Error: {str(e)}")

    @strawberry.field
    async def add_beneficiary(self, info: Info, input: BeneficiaryCreateInput) -> BeneficiaryResponse:
        """Add a beneficiary / next of kin to a customer."""
        current_user = info.context.get("current_user")
        if not current_user:
            raise Exception("Not authenticated")
        if current_user.role not in ("admin", "loan_officer", "branch_manager"):
            raise Exception("Not authorized")
        async with AsyncSessionLocal() as session:
            b = Beneficiary(
                customer_id=input.customer_id,
                full_name=input.full_name,
                relationship=input.relationship,
                contact_number=input.contact_number,
                email=input.email,
                address=input.address,
                is_primary=input.is_primary or False,
            )
            session.add(b)
            session.add(CustomerActivity(
                customer_id=input.customer_id,
                actor_user_id=str(current_user.id),
                actor_username=current_user.username,
                action="beneficiary_added",
                detail=json.dumps({"full_name": input.full_name, "relationship": input.relationship}),
                created_at=datetime.now(timezone.utc),
            ))
            await session.commit()
            await session.refresh(b)
        return BeneficiaryResponse(
            success=True, message="Beneficiary added",
            beneficiary=BeneficiaryType(
                id=b.id, customer_id=b.customer_id, full_name=b.full_name,
                relationship=b.relationship, contact_number=b.contact_number,
                email=b.email, address=b.address, is_primary=b.is_primary, created_at=b.created_at,
            )
        )

    @strawberry.field
    async def delete_beneficiary(self, info: Info, beneficiary_id: int) -> BeneficiaryResponse:
        """Remove a beneficiary."""
        current_user = info.context.get("current_user")
        if not current_user or current_user.role not in ("admin", "loan_officer"):
            raise Exception("Not authorized")
        async with AsyncSessionLocal() as session:
            b = await session.get(Beneficiary, beneficiary_id)
            if not b:
                return BeneficiaryResponse(success=False, message="Beneficiary not found")
            await session.delete(b)
            await session.commit()
        return BeneficiaryResponse(success=True, message="Beneficiary deleted")