"""
AI service — connects to local LLM server (OpenAI-compatible API).
"""

import logging
import httpx
from .config import settings

logger = logging.getLogger(__name__)

AI_SYSTEM_PROMPT = """You are an expert lending and collections assistant for LendingMVP, a Philippine financing platform. You help loan officers, collection officers, and branch managers with their daily work.

Your knowledge covers:
- Loan products and amortization types (flat rate, diminishing balance, daily/weekly/monthly/quarterly/bullet)
- Collections strategies for delinquent loans (BSP regulations, PD 1070)
- Philippine lending regulations (Lending Company Regulation Act, SEC rules, BSP circulars)
- Credit analysis and risk assessment best practices
- Customer management and KYC requirements
- Payment gateway integrations (GCash, Maya, InstaPay, PESONet)
- Collections reporting and aging analysis
- Loan restructuring and rehabilitation options

Rules:
- Answer concisely and practically for the Philippine context
- If you don't know something, say so — don't make up regulations or policies
- Do not give legal advice — suggest consulting legal counsel for complex cases
- Keep answers under 500 words unless asked for detail
- Be professional but approachable"""


async def ask_ai(question: str) -> str:
    base_url = settings.local_ai_base_url
    api_key = settings.local_ai_api_key
    model = settings.local_ai_model

    if not base_url or not model:
        logger.warning("AI service not configured: missing LOCAL_AI_BASE_URL or LOCAL_AI_MODEL")
        return "AI service is not configured. Please set LOCAL_AI_BASE_URL and LOCAL_AI_MODEL in your .env file."

    headers = {
        "Content-Type": "application/json",
    }
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"

    payload = {
        "model": model,
        "messages": [
            {"role": "system", "content": AI_SYSTEM_PROMPT},
            {"role": "user", "content": question},
        ],
        "temperature": 0.3,
        "max_tokens": 2000,
    }

    try:
        async with httpx.AsyncClient(timeout=60.0) as client:
            response = await client.post(
                f"{base_url.rstrip('/')}/chat/completions",
                headers=headers,
                json=payload,
            )
            response.raise_for_status()
            data = response.json()
            answer = data["choices"][0]["message"]["content"]

            # Strip think tags from models that emit them (e.g. DeepSeek)
            if "<｜end▁of▁thinking｜>" in answer:
                answer = answer.split("<｜end▁of▁thinking｜>")[-1].strip()
            return answer

    except httpx.TimeoutException:
        logger.error("AI service request timed out")
        return "The AI service is temporarily unavailable (timeout). Please try again later."
    except httpx.HTTPStatusError as e:
        logger.error(f"AI service returned {e.response.status_code}: {e.response.text}")
        return f"The AI service returned an error (status {e.response.status_code}). Please try again later."
    except Exception as e:
        logger.error(f"AI service request failed: {e}")
        return "The AI service is temporarily unavailable. Please try again later."
