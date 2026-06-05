from fastapi import APIRouter, HTTPException, Depends
from pydantic import BaseModel, Field
from typing import Optional, List, Literal
from datetime import datetime, date
from decimal import Decimal
from bson import ObjectId

from app.models import PyObjectId
from app.schema import (
    CashDrawerSession, CashDrawerUpdate, TransactionLimitConfig,
    TransactionLimitUpdate, TellerSessionResponse
)
# from app.main import db  # TODO: Implement MongoDB setup
# from app.audit_middleware import audit_log
from app.worker import send_notification
from app.auth.authentication import get_current_user

router = APIRouter(prefix="/api/v1/teller", tags=["Teller Operations"])

# ============================================================================
# TELLER CASH DRAWER MODELS
# ============================================================================

class CashDrawerOpening(BaseModel):
    teller_id: PyObjectId
    branch_id: PyObjectId
    initial_amount: Decimal
    notes: Optional[str] = None

class CashDrawerClosing(BaseModel):
    session_id: PyObjectId
    expected_amount: Decimal
    actual_amount: Decimal
    variance_reason: Optional[str] = None
    notes: Optional[str] = None

class CashDrawerTransaction(BaseModel):
    session_id: PyObjectId
    transaction_type: Literal["deposit", "withdrawal", "transfer"]
    amount: Decimal
    customer_id: Optional[PyObjectId] = None
    customer_name: Optional[str] = None
    reference_id: Optional[str] = None
    notes: Optional[str] = None

# ============================================================================
# TELLER TRANSACTION LIMITS MODELS
# ============================================================================

class TransactionLimitCreate(BaseModel):
    role: str
    daily_limit: Decimal
    weekly_limit: Decimal
    monthly_limit: Decimal
    single_transaction_limit: Decimal
    branch_id: Optional[PyObjectId] = None
    active: bool = True

class TransactionLimitUpdate(BaseModel):
    daily_limit: Optional[Decimal] = None
    weekly_limit: Optional[Decimal] = None
    monthly_limit: Optional[Decimal] = None
    single_transaction_limit: Optional[Decimal] = None
    active: Optional[bool] = None

# ============================================================================
# TELLER OPERATIONS LOGIC
# ============================================================================

class TellerOperations:
    """Teller Operations Management"""
    
    @staticmethod
    async def open_cash_drawer(data: CashDrawerOpening) -> CashDrawerSession:
        """Open a new teller cash drawer session"""
        try:
            # Check if there's already an open session
            existing_session = await db.cash_drawers.find_one({
                "teller_id": str(data.teller_id),
                "status": "open",
                "closed_at": None
            })
            
            if existing_session:
                raise HTTPException(status_code=400, detail="Teller already has an open session")
            
            session_id = str(ObjectId())
            
            session_doc = {
                "_id": session_id,
                "teller_id": str(data.teller_id),
                "branch_id": str(data.branch_id),
                "opening_time": datetime.utcnow(),
                "initial_amount": float(data.initial_amount),
                "current_amount": float(data.initial_amount),
                "status": "open",
                "notes": data.notes,
                "created_at": datetime.utcnow(),
                "closed_at": None,
                "transactions": []
            }
            
            await db.cash_drawers.insert_one(session_doc)
            
            return CashDrawerSession(
                session_id=session_id,
                teller_id=str(data.teller_id),
                branch_id=str(data.branch_id),
                opening_time=session_doc["opening_time"],
                initial_amount=data.initial_amount,
                current_amount=data.initial_amount,
                status="open",
                notes=data.notes
            )
        except Exception as e:
            raise HTTPException(status_code=500, detail=f"Failed to open cash drawer: {str(e)}")
    
    @staticmethod
    async def close_cash_drawer(data: CashDrawerClosing) -> CashDrawerSession:
        """Close teller cash drawer and reconcile"""
        try:
            session = await db.cash_drawers.find_one({"_id": str(data.session_id)})
            
            if not session:
                raise HTTPException(status_code=404, detail="Cash drawer session not found")
            
            if session["status"] == "closed":
                raise HTTPException(status_code=400, detail="Session already closed")
            
            variance = float(data.actual_amount) - float(data.expected_amount)
            
            session_doc = {
                "status": "closed",
                "closing_time": datetime.utcnow(),
                "expected_amount": float(data.expected_amount),
                "actual_amount": float(data.actual_amount),
                "variance": variance,
                "variance_reason": data.variance_reason,
                "notes": data.notes,
                "closed_at": datetime.utcnow()
            }
            
            await db.cash_drawers.update_one(
                {"_id": str(data.session_id)},
                {"$set": session_doc}
            )
            
            return CashDrawerSession(
                session_id=str(data.session_id),
                status="closed",
                closing_time=session_doc["closing_time"],
                expected_amount=data.expected_amount,
                actual_amount=data.actual_amount,
                variance=variance,
                variance_reason=data.variance_reason
            )
        except Exception as e:
            raise HTTPException(status_code=500, detail=f"Failed to close cash drawer: {str(e)}")
    
    @staticmethod
    async def process_transaction(data: CashDrawerTransaction) -> dict:
        """Process a cash drawer transaction"""
        try:
            session = await db.cash_drawers.find_one({"_id": str(data.session_id)})
            
            if not session:
                raise HTTPException(status_code=404, detail="Cash drawer session not found")
            
            if session["status"] != "open":
                raise HTTPException(status_code=400, detail="Session is not open")
            
            transaction_id = str(ObjectId())
            
            transaction = {
                "_id": transaction_id,
                "session_id": str(data.session_id),
                "transaction_type": data.transaction_type,
                "amount": float(data.amount),
                "customer_id": str(data.customer_id) if data.customer_id else None,
                "customer_name": data.customer_name,
                "reference_id": data.reference_id,
                "notes": data.notes,
                "timestamp": datetime.utcnow()
            }
            
            # Update current balance
            current_amount = session["current_amount"]
            if data.transaction_type == "deposit":
                current_amount += float(data.amount)
            elif data.transaction_type == "withdrawal":
                current_amount -= float(data.amount)
            
            if current_amount < 0:
                raise HTTPException(status_code=400, detail="Insufficient cash balance")
            
            await db.cash_drawers.update_one(
                {"_id": str(data.session_id)},
                {
                    "$set": {"current_amount": current_amount},
                    "$push": {"transactions": transaction}
                }
            )
            
            return {
                "transaction_id": transaction_id,
                "session_id": str(data.session_id),
                "transaction_type": data.transaction_type,
                "amount": float(data.amount),
                "new_balance": current_amount,
                "timestamp": transaction["timestamp"]
            }
        except Exception as e:
            raise HTTPException(status_code=500, detail=f"Failed to process transaction: {str(e)}")
    
    @staticmethod
    async def get_current_balance(session_id: str) -> dict:
        """Get current cash drawer balance"""
        session = await db.cash_drawers.find_one({"_id": session_id})
        
        if not session:
            raise HTTPException(status_code=404, detail="Cash drawer session not found")
        
        return {
            "session_id": session_id,
            "current_amount": session["current_amount"],
            "initial_amount": session["initial_amount"],
            "status": session["status"],
            "opening_time": session["opening_time"],
            "transaction_count": len(session.get("transactions", []))
        }
    
    @staticmethod
    async def set_transaction_limits(data: TransactionLimitCreate) -> TransactionLimitConfig:
        """Set transaction limits for a role"""
        try:
            limit_doc = {
                "role": data.role,
                "daily_limit": float(data.daily_limit),
                "weekly_limit": float(data.weekly_limit),
                "monthly_limit": float(data.monthly_limit),
                "single_transaction_limit": float(data.single_transaction_limit),
                "branch_id": str(data.branch_id) if data.branch_id else None,
                "active": data.active,
                "created_at": datetime.utcnow(),
                "updated_at": datetime.utcnow()
            }
            
            result = await db.transaction_limits.insert_one(limit_doc)
            
            return TransactionLimitConfig(
                id=str(result.inserted_id),
                role=data.role,
                daily_limit=data.daily_limit,
                weekly_limit=data.weekly_limit,
                monthly_limit=data.monthly_limit,
                single_transaction_limit=data.single_transaction_limit,
                branch_id=str(data.branch_id) if data.branch_id else None,
                active=data.active
            )
        except Exception as e:
            raise HTTPException(status_code=500, detail=f"Failed to set transaction limits: {str(e)}")
    
    @staticmethod
    async def update_transaction_limits(limit_id: str, data: TransactionLimitUpdate) -> TransactionLimitConfig:
        """Update transaction limits"""
        update_fields = {}
        
        if data.daily_limit is not None:
            update_fields["daily_limit"] = float(data.daily_limit)
        if data.weekly_limit is not None:
            update_fields["weekly_limit"] = float(data.weekly_limit)
        if data.monthly_limit is not None:
            update_fields["monthly_limit"] = float(data.monthly_limit)
        if data.single_transaction_limit is not None:
            update_fields["single_transaction_limit"] = float(data.single_transaction_limit)
        if data.active is not None:
            update_fields["active"] = data.active
        
        update_fields["updated_at"] = datetime.utcnow()
        
        result = await db.transaction_limits.update_one(
            {"_id": limit_id},
            {"$set": update_fields}
        )
        
        if result.matched_count == 0:
            raise HTTPException(status_code=404, detail="Transaction limit not found")
        
        limit = await db.transaction_limits.find_one({"_id": limit_id})
        
        return TransactionLimitConfig(
            id=limit_id,
            role=limit["role"],
            daily_limit=limit["daily_limit"],
            weekly_limit=limit["weekly_limit"],
            monthly_limit=limit["monthly_limit"],
            single_transaction_limit=limit["single_transaction_limit"],
            branch_id=limit.get("branch_id"),
            active=limit["active"]
        )

# ============================================================================
# API ENDPOINTS
# ============================================================================

@router.post("/cash-drawer/open", response_model=CashDrawerSession)
async def open_cash_drawer(
    data: CashDrawerOpening,
    current_user: dict = Depends(get_current_user),
):
    """Open teller cash drawer session"""
    result = await TellerOperations.open_cash_drawer(data)
    return result

@router.post("/cash-drawer/close", response_model=CashDrawerSession)
async def close_cash_drawer(
    data: CashDrawerClosing,
    current_user: dict = Depends(get_current_user),
):
    """Close and reconcile teller cash drawer"""
    result = await TellerOperations.close_cash_drawer(data)
    return result

@router.post("/cash-drawer/transaction", response_model=dict)
async def process_cash_transaction(
    data: CashDrawerTransaction,
    current_user: dict = Depends(get_current_user),
):
    """Process a cash drawer transaction"""
    result = await TellerOperations.process_transaction(data)
    return result

@router.get("/cash-drawer/{session_id}/balance", response_model=dict)
async def get_cash_drawer_balance(
    session_id: str,
    current_user: dict = Depends(get_current_user),
):
    """Get current cash drawer balance"""
    return await TellerOperations.get_current_balance(session_id)

@router.post("/transaction-limits", response_model=TransactionLimitConfig)
async def set_transaction_limits(
    data: TransactionLimitCreate,
    current_user: dict = Depends(get_current_user),
):
    """Set transaction limits for a role"""
    result = await TellerOperations.set_transaction_limits(data)
    return result
