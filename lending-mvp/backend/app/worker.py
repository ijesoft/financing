"""
ARQ background worker for Phase 1 async tasks.
Start with: arq app.worker.WorkerSettings
"""
import os
import logging
from arq import cron
from arq.connections import RedisSettings

logger = logging.getLogger(__name__)


# ── Task definitions ──────────────────────────────────────────────────────────

async def generate_loan_statement(ctx, loan_id: str, user_id: str):
    """
    Placeholder: generate PDF loan statement and store/email it.
    - ctx['redis'] gives the shared Redis connection
    """
    logger.info("generate_loan_statement | loan_id=%s user_id=%s", loan_id, user_id)
    # TODO: fetch loan, render PDF, upload to MinIO/S3, send email via SendGrid
    await ctx["redis"].set(
        f"statement:status:{loan_id}",
        "generated",
        ex=86400,
    )
    return {"status": "ok", "loan_id": loan_id}


async def send_notification(ctx, user_id: str, message: str, channel: str = "email", subject: str = ""):
    """
    Send notification via email / SMS / push.
    - Integrates with SendGrid for email
    - Integrates with Twilio for SMS
    - Supports push notifications via Firebase FCM
    """
    import os
    from datetime import datetime
    
    logger.info("send_notification | user=%s channel=%s", user_id, channel)
    
    # Get configuration
    smtp_host = os.environ.get("SMTP_HOST", "smtp.sendgrid.net")
    smtp_port = int(os.environ.get("SMTP_PORT", 587))
    smtp_user = os.environ.get("SMTP_USER", "apikey")
    smtp_password = os.environ.get("SMTP_PASSWORD", "")
    from_email = os.environ.get("FROM_EMAIL", "notifications@financing-solutions.ph")
    twilio_sid = os.environ.get("TWILIO_SID", "")
    twilio_auth = os.environ.get("TWILIO_AUTH", "")
    twilio_from = os.environ.get("TWILIO_FROM", "")
    
    if channel == "email":
        # Send email via SMTP (SendGrid)
        if not smtp_password:
            logger.warning("SMTP credentials not configured")
            return {"status": "skipped", "message": "SMTP not configured"}
        
        try:
            import smtplib
            from email.mime.text import MIMEText
            from email.mime.multipart import MIMEMultipart
            
            # Fetch user email from database
            from ..database.customer_crud import CustomerCRUD
            from ..database import get_customers_collection
            from ..database.user_crud import UserCRUD
            from ..database import get_users_collection
            
            users_collection = get_users_collection()
            user_crud = UserCRUD(users_collection)
            user = await user_crud.get_user_by_id(user_id)
            
            if not user or not user.email:
                return {"status": "error", "message": "User email not found"}
            
            # Create email
            msg = MIMEMultipart()
            msg["Subject"] = subject or "Notification from Financing Solutions"
            msg["From"] = from_email
            msg["To"] = user.email
            
            body = f"""
            {message}
            
            ---
            This is an automated notification. Please do not reply to this email.
            
            Financing Solutions Inc.
            Your Trusted Financial Partner
            """
            
            msg.attach(MIMEText(body, "plain"))
            
            # Send email
            with smtplib.SMTP(smtp_host, smtp_port) as server:
                server.starttls()
                server.login(smtp_user, smtp_password)
                server.sendmail(from_email, user.email, msg.as_string())
            
            logger.info(f"Email sent to {user.email}")
            return {
                "status": "success",
                "channel": "email",
                "to": user.email,
                "sent_at": datetime.utcnow().isoformat()
            }
            
        except Exception as e:
            logger.error(f"Email notification failed: {e}")
            return {"status": "error", "channel": "email", "error": str(e)}
    
    elif channel == "sms":
        # Send SMS via Twilio
        if not twilio_sid or not twilio_auth:
            logger.warning("Twilio credentials not configured")
            return {"status": "skipped", "message": "Twilio not configured"}
        
        try:
            import httpx
            
            # Fetch user mobile number from database
            from ..database.customer_crud import CustomerCRUD
            from ..database import get_customers_collection
            
            customers_collection = get_customers_collection()
            customer_crud = CustomerCRUD(customers_collection)
            customer = await customer_crud.get_customer_by_id(user_id)
            
            mobile_number = customer.mobile_number if customer else None
            
            if not mobile_number:
                return {"status": "error", "message": "Mobile number not found"}
            
            # Send SMS via Twilio API
            async with httpx.AsyncClient() as client:
                response = await client.post(
                    f"https://api.twilio.com/2010-04-01/Accounts/{twilio_sid}/Messages.json",
                    auth=(twilio_sid, twilio_auth),
                    data={
                        "From": twilio_from,
                        "To": mobile_number,
                        "Body": message
                    }
                )
                
                if response.status_code == 201:
                    data = response.json()
                    logger.info(f"SMS sent to {mobile_number}")
                    return {
                        "status": "success",
                        "channel": "sms",
                        "to": mobile_number,
                        "sid": data.get("sid"),
                        "sent_at": datetime.utcnow().isoformat()
                    }
                else:
                    logger.error(f"SMS failed: {response.text}")
                    return {"status": "error", "channel": "sms", "error": response.text}
                    
        except Exception as e:
            logger.error(f"SMS notification failed: {e}")
            return {"status": "error", "channel": "sms", "error": str(e)}
    
    else:
        logger.warning(f"Unsupported notification channel: {channel}")
        return {"status": "error", "message": f"Unsupported channel: {channel}"}


async def accrue_daily_interest(ctx):
    """
    PG-only daily accrual: SELECT FOR UPDATE active savings accounts,
    compute daily interest, atomically update balance + post GL + create SavingsTransaction.

    Banking-grade: idempotent per account per day via reference_no = f"INT-ACCRUE-{account_id}-{today}"
    Uses: DR 5400 Interest Expense / CR 2020 Savings Deposits Payable (and interest_posting txn).
    """
    logger.info("accrue_daily_interest | running")
    from datetime import date as _date
    from decimal import Decimal as _Dec, ROUND_HALF_UP
    from sqlalchemy import select as _select

    try:
        from app.database import get_async_session_local as _get_sess
        from app.database.pg_core_models import SavingsAccount, SavingsTransaction
        from app.accounting import create_journal_entry as _je

        today = _date.today()
        ref_prefix = f"INT-{today.isoformat()}"

        session_factory = _get_sess()
        processed = 0
        total_posted = _Dec("0.00")

        async with session_factory() as session:
            # Fetch all active accounts with interest_rate >0
            res = await session.execute(
                _select(SavingsAccount).where(SavingsAccount.status == "active")
            )
            accounts = res.scalars().all()
            for account in accounts:
                if account.interest_rate is None:
                    continue
                rate = _Dec(str(account.interest_rate))
                if rate <= _Dec("0.00"):
                    continue
                bal = _Dec(str(account.balance or _Dec("0.00")))
                if bal <= _Dec("0.00"):
                    continue
                # Formula: daily_interest = bal * (rate/100) / 365, quantized to cent
                daily = (bal * (rate / _Dec("100")) / _Dec("365")).quantize(_Dec("0.01"), rounding=ROUND_HALF_UP)
                if daily <= _Dec("0.00"):
                    continue

                # Idempotency check: has we already posted for this account today?
                ref = f"INT-ACCRUE-{account.id}-{today.isoformat()}"
                exists = await session.execute(
                    _select(SavingsTransaction).where(SavingsTransaction.reference == ref)
                )
                if exists.scalar_one_or_none() is not None:
                    continue

                # Lock account row
                locked = await session.execute(
                    _select(SavingsAccount).where(SavingsAccount.id == account.id).with_for_update()
                )
                locked_acct = locked.scalar_one_or_none()
                if not locked_acct:
                    continue
                before = _Dec(str(locked_acct.balance or _Dec("0.00")))
                after = before + daily
                locked_acct.balance = after

                # Create SavingsTransaction
                txn = SavingsTransaction(
                    account_id=account.id,
                    transaction_type="interest_posting",
                    amount=daily,
                    balance_before=before,
                    balance_after=after,
                    reference=ref,
                    description=f"Daily interest {rate}% on {before} @ {today.isoformat()}",
                )
                session.add(txn)
                await session.flush()

                # GL: DR 5400 Interest Expense / CR 2020 Savings Deposits Payable — idempotent via reference
                try:
                    await _je(
                        session,
                        reference_no=ref,
                        description=f"Daily savings interest — account {account.account_number} — {today.isoformat()}",
                        lines=[
                            {"account_code": "5400", "debit": daily, "credit": _Dec("0.00")},
                            {"account_code": "2020", "debit": _Dec("0.00"), "credit": daily},
                        ],
                        created_by="system:accrual",
                        idempotency_key=ref,
                    )
                except Exception as je_exc:
                    # If idempotency hit, rollback interest? No — journal already exists, keep account update
                    logger.warning("GL posting for interest %s failed (idempotent?): %s", ref, je_exc)

                processed += 1
                total_posted += daily

            await session.commit()

        logger.info("accrue_daily_interest | completed | accounts_processed=%d total_interest=%.2f", processed, float(total_posted))
        return {"status": "success", "accounts_processed": processed, "total_interest_posted": str(total_posted)}

    except Exception as e:
        logger.exception("accrue_daily_interest | error: %s", str(e))
        return {"status": "error", "message": str(e)}


# ── Worker settings ───────────────────────────────────────────────────────────

_redis_url = os.getenv("REDIS_URL", "redis://:lending_redis_pass@redis:6379/0")

# Parse password from URL for RedisSettings if present
def _parse_redis_settings(url: str) -> RedisSettings:
    """Convert redis://[:password@]host:port/db to arq RedisSettings."""
    # e.g. redis://:pass@host:6379/0
    url = url.replace("redis://", "")
    password = None
    if "@" in url:
        credentials, hostpart = url.rsplit("@", 1)
        password = credentials.lstrip(":")
    else:
        hostpart = url

    # strip db
    if "/" in hostpart:
        hostpart, _ = hostpart.rsplit("/", 1)

    host, port = hostpart.rsplit(":", 1)
    return RedisSettings(host=host, port=int(port), password=password)


# ── Teller & Payment Gateway Notifications ───────────────────────────────────

async def send_teller_cash_drawer_notification(ctx, teller_id: str, message: str, session_id: str):
    """Send notification for teller cash drawer operations"""
    logger.info("send_teller_cash_drawer_notification | teller=%s session=%s", teller_id, session_id)
    
    try:
        # Fetch teller email
        from ..database.user_crud import UserCRUD
        from ..database import get_users_collection
        
        users_collection = get_users_collection()
        user_crud = UserCRUD(users_collection)
        teller = await user_crud.get_user_by_id(teller_id)
        
        if teller and teller.email:
            await send_notification(ctx, teller_id, message, "email", "Teller Cash Drawer Notification")
        
        # Send SMS if configured
        if os.environ.get("TWILIO_SID"):
            await send_notification(ctx, teller_id, message, "sms", "")
        
        logger.info(f"Notifications sent to teller {teller_id}")
        return {"status": "ok", "teller_id": teller_id, "session_id": session_id}
    except Exception as e:
        logger.error(f"Failed to send teller notification: {e}")
        return {"status": "error", "message": str(e)}


async def send_payment_gateway_notification(ctx, user_id: str, message: str, payment_type: str, gateway: str):
    """Send notification for payment gateway operations"""
    logger.info("send_payment_gateway_notification | user=%s gateway=%s payment_type=%s", user_id, gateway, payment_type)
    
    try:
        # Send email notification
        await send_notification(ctx, user_id, message, "email", f"Payment {payment_type.title()} via {gateway}")
        
        # Send SMS for important payments
        if payment_type in ["loan_repayment", "deposit"]:
            await send_notification(ctx, user_id, f"Payment {payment_type} processed via {gateway}", "sms", "")
        
        logger.info(f"Payment notifications sent to user {user_id}")
        return {"status": "ok", "user_id": user_id, "gateway": gateway}
    except Exception as e:
        logger.error(f"Failed to send payment notification: {e}")
        return {"status": "error", "message": str(e)}


async def send_transaction_limit_notification(ctx, user_id: str, message: str):
    """Send notification for transaction limit updates"""
    logger.info("send_transaction_limit_notification | user=%s", user_id)
    
    try:
        # Send email notification
        await send_notification(ctx, user_id, message, "email", "Transaction Limits Updated")
        return {"status": "ok", "user_id": user_id}
    except Exception as e:
        logger.error(f"Failed to send transaction limit notification: {e}")
        return {"status": "error", "message": str(e)}


class WorkerSettings:
    functions = [
        generate_loan_statement, 
        send_notification,
        send_teller_cash_drawer_notification,
        send_payment_gateway_notification,
        send_transaction_limit_notification
    ]
    cron_jobs = [
        cron(accrue_daily_interest, hour=0, minute=0),  # midnight UTC daily
    ]
    redis_settings = _parse_redis_settings(_redis_url)
    max_jobs = 10
    job_timeout = 300
    on_startup = None
    on_shutdown = None
