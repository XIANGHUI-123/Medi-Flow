"""
ai_service.py  ─  AI API integration for transcript & image analysis.

Supports two providers (tried in order):
  1. OpenAI  – if OPENAI_API_KEY is set in .env
  2. Flex AI – if AI_API_LOGIN_URL + AI_API_CHAT_URL are set in .env

Falls back to keyword matching when neither provider is reachable.
"""

import os
import json
import re
import logging
from datetime import datetime, timedelta, timezone
from typing import Optional

import httpx
from dotenv import load_dotenv

load_dotenv(override=True)
logger = logging.getLogger(__name__)

# ── Configuration ────────────────────────────────────────────
# OpenAI (set OPENAI_API_KEY=DISABLED or leave empty to skip)
_raw_openai_key  = os.getenv("OPENAI_API_KEY", "")
OPENAI_API_KEY   = _raw_openai_key if _raw_openai_key.startswith("sk-") else ""
OPENAI_MODEL     = os.getenv("OPENAI_MODEL", "gpt-4o-mini")

# Flex AI (FlexToken) — direct key + base URL (preferred)
FLEX_API_KEY  = os.getenv("FLEX_API_KEY", "sk-M0rK-34iVcYLlBwozBUz5w")
FLEX_API_BASE = os.getenv("FLEX_API_BASE", "https://aiworkshopapi.flexinfra.com.my/v1")
FLEX_MODEL    = os.getenv("FLEX_MODEL", "qwen2.5")

# Flex AI login fallback (used only when FLEX_API_KEY is empty)
AI_LOGIN_URL  = os.getenv("AI_API_LOGIN_URL", "")
AI_USERNAME   = os.getenv("AI_API_USERNAME", "")
AI_PASSWORD   = os.getenv("AI_API_PASSWORD", "")

# ── Flex AI cache (login fallback) ──────────────────────────
_flex_jwt: Optional[str] = None
_flex_jwt_expiry: Optional[datetime] = None
_flex_api_key: Optional[str] = None
_flex_chat_base: Optional[str] = None
_flex_litellm_user_id: Optional[str] = None


# ── Known medical‑action keyword lists ──────────────────────
LAB_TEST_KEYWORDS = [
    "blood test", "urine test", "x-ray", "xray", "mri",
    "ct scan", "cbc", "complete blood count", "ecg",
    "ultrasound", "biopsy", "culture test", "liver function",
    "kidney function", "thyroid test", "hba1c", "blood sugar",
    "lipid panel", "cholesterol test",
]

MEDICATION_KEYWORDS = [
    "antibiotic", "painkiller", "paracetamol", "ibuprofen",
    "amoxicillin", "tablet", "capsule", "prescription drug",
    "cream", "ointment", "inhaler", "insulin", "metformin",
    "aspirin", "steroid", "antifungal", "antiviral",
    "cough syrup", "lozenges", "eye drops",
]


# ─────────────────────────────────────────────────────────────
# Unified AI call — tries OpenAI first, then Flex AI
# ─────────────────────────────────────────────────────────────
async def _call_ai(system_prompt: str, user_content: str,
                   temperature: float = 0.2, max_tokens: int = 1024) -> Optional[str]:
    """
    Send a chat completion request and return the assistant's text.
    Returns None if every provider fails.
    """
    # ── Provider 1: OpenAI ───────────────────────────────────
    if OPENAI_API_KEY:
        text = await _call_openai(system_prompt, user_content, temperature, max_tokens)
        if text:
            return text

    # ── Provider 2: Flex AI Workshop ─────────────────────────
    text = await _call_flex_ai(system_prompt, user_content, temperature, max_tokens)
    if text:
        return text

    return None


async def _call_openai(system_prompt: str, user_content: str,
                       temperature: float, max_tokens: int) -> Optional[str]:
    """Call the OpenAI chat completions API directly via httpx."""
    if not OPENAI_API_KEY:
        return None
    headers = {
        "Authorization": f"Bearer {OPENAI_API_KEY}",
        "Content-Type": "application/json",
    }
    payload = {
        "model": OPENAI_MODEL,
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user",   "content": user_content},
        ],
        "temperature": temperature,
        "max_tokens": max_tokens,
    }
    try:
        async with httpx.AsyncClient(timeout=60) as client:
            resp = await client.post(
                "https://api.openai.com/v1/chat/completions",
                headers=headers,
                json=payload,
            )
            if resp.status_code < 400:
                body = resp.json()
                text = body.get("choices", [{}])[0].get("message", {}).get("content", "")
                if text:
                    logger.info("OpenAI response received (%d chars)", len(text))
                    return text
            else:
                logger.warning("OpenAI returned %d: %s", resp.status_code, resp.text[:200])
    except Exception as exc:
        logger.warning("OpenAI call failed: %s", exc)
    return None


async def _flex_login() -> bool:
    """
    Authenticate with the Flex AI Workshop platform.
    Steps: login → getKey → baseUrl.
    Caches JWT, API key, and chat base URL.
    Returns True on success.
    """
    global _flex_jwt, _flex_jwt_expiry, _flex_api_key, _flex_chat_base, _flex_litellm_user_id

    # Return cached data if JWT still valid and we have all pieces
    if (_flex_jwt and _flex_jwt_expiry
            and datetime.now(timezone.utc) < _flex_jwt_expiry
            and _flex_api_key and _flex_chat_base):
        return True

    if not AI_LOGIN_URL or not AI_USERNAME or not AI_PASSWORD:
        return False

    base = AI_LOGIN_URL.rstrip("/")

    try:
        async with httpx.AsyncClient(timeout=30, verify=False) as client:
            # Step 1: Login
            resp = await client.post(
                f"{base}/api/auth/login",
                json={"email": AI_USERNAME, "password": AI_PASSWORD},
            )
            resp.raise_for_status()
            body = resp.json()
            data = body.get("data", {})
            token = data.get("token")
            user = data.get("user", {})
            litellm_id = user.get("liteLLMfx_user_id", "")

            if not token or not litellm_id:
                logger.warning("Flex AI login: missing token or user id in response")
                return False

            _flex_jwt = token
            _flex_jwt_expiry = datetime.now(timezone.utc) + timedelta(minutes=55)
            _flex_litellm_user_id = litellm_id
            headers = {"Authorization": f"Bearer {token}"}

            # Step 2: Get LiteLLM API key
            key_resp = await client.get(
                f"{base}/api/auth/getKey",
                params={"id": litellm_id},
                headers=headers,
            )
            key_resp.raise_for_status()
            api_key = key_resp.json().get("key")
            if not api_key:
                logger.warning("Flex AI getKey: no key in response")
                return False
            _flex_api_key = api_key

            # Step 3: Get chat base URL
            url_resp = await client.get(
                f"{base}/api/auth/baseUrl",
                headers=headers,
            )
            url_resp.raise_for_status()
            chat_base = url_resp.json().get("results", {}).get("base_url")
            if not chat_base:
                logger.warning("Flex AI baseUrl: no base_url in response")
                return False
            _flex_chat_base = chat_base.rstrip("/")

            logger.info("Flex AI login successful (key=%s… base=%s)", api_key[:8], _flex_chat_base)
            return True

    except Exception as exc:
        logger.warning("Flex AI login failed: %s", exc)
        return False


async def _call_flex_ai(system_prompt: str, user_content: str,
                        temperature: float, max_tokens: int) -> Optional[str]:
    """Call the Flex AI (FlexToken) LiteLLM proxy."""
    # Use direct key if available, otherwise fall back to login flow
    api_key = FLEX_API_KEY
    api_base = FLEX_API_BASE.rstrip("/")

    if not api_key:
        if not await _flex_login():
            return None
        api_key = _flex_api_key
        api_base = _flex_chat_base

    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }
    payload = {
        "model": FLEX_MODEL,
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user",   "content": user_content},
        ],
        "temperature": temperature,
        "max_tokens": max_tokens,
    }

    try:
        async with httpx.AsyncClient(timeout=60, verify=False) as client:
            resp = await client.post(
                f"{api_base}/chat/completions",
                headers=headers,
                json=payload,
            )
            if resp.status_code < 400:
                body = resp.json()
                text = body.get("choices", [{}])[0].get("message", {}).get("content", "")
                if text:
                    logger.info("Flex AI response (%d chars)", len(text))
                    return text
            else:
                logger.warning("Flex AI chat returned %d: %s", resp.status_code, resp.text[:200])
    except Exception as exc:
        logger.warning("Flex AI chat failed: %s", exc)

    return None


# ─────────────────────────────────────────────────────────────
# Transcript analysis via AI
# ─────────────────────────────────────────────────────────────
async def analyze_transcript(transcript_text: str) -> dict:
    """
    Send a consultation transcript to the AI and get structured
    medical‑action intents back.

    Returns dict with keys:
        lab_tests    : list[str]
        medications  : list[str]
        summary      : str
        raw_response : str   (original AI output for logging)
    """
    system_prompt = (
        "You are a medical assistant AI. Analyze the following doctor-patient "
        "consultation transcript. Extract:\n"
        "1. Any lab tests mentioned or implied (blood test, urine test, x-ray, "
        "MRI, CT scan, CBC, etc.)\n"
        "2. Any medications mentioned or implied (antibiotics, painkillers, "
        "specific drug names, etc.)\n"
        "3. A brief clinical summary.\n\n"
        "Return your answer STRICTLY as JSON with keys: "
        "\"lab_tests\" (list of strings), \"medications\" (list of strings), "
        "\"summary\" (string). Do NOT include any text outside the JSON."
    )

    ai_text = await _call_ai(system_prompt, transcript_text, temperature=0.2, max_tokens=1024)

    if ai_text is None:
        logger.warning("All AI providers unavailable – using keyword fallback")
        result = _keyword_fallback(transcript_text)
        result["raw_response"] = ""
        return result

    result = _parse_ai_json(ai_text)
    result["raw_response"] = ai_text
    return result


# ─────────────────────────────────────────────────────────────
# Image analysis via AI
# ─────────────────────────────────────────────────────────────
async def analyze_image_description(image_description: str) -> dict:
    """
    Analyze an image description (or base64 caption) for symptoms.

    Returns:
        symptom          : str
        confidence       : float
        suggested_test   : str
        suggested_medicine : str
    """
    system_prompt = (
        "You are a medical triage AI. Given the following description of a "
        "patient image (or direct image analysis), return a JSON with keys:\n"
        "  symptom           (string – most likely symptom),\n"
        "  confidence         (float 0-1),\n"
        "  suggested_test     (string),\n"
        "  suggested_medicine (string).\n"
        "Return ONLY valid JSON."
    )

    ai_text = await _call_ai(system_prompt, image_description, temperature=0.3, max_tokens=512)

    if ai_text is None:
        return {
            "symptom": "analysis unavailable (AI providers unreachable)",
            "confidence": 0.0,
            "suggested_test": "general blood test",
            "suggested_medicine": "consult doctor",
        }

    try:
        parsed = _extract_json(ai_text)
        return {
            "symptom":            parsed.get("symptom", "unknown"),
            "confidence":         float(parsed.get("confidence", 0.0)),
            "suggested_test":     parsed.get("suggested_test", ""),
            "suggested_medicine": parsed.get("suggested_medicine", ""),
        }
    except Exception:
        return {
            "symptom": "analysis error",
            "confidence": 0.0,
            "suggested_test": "general blood test",
            "suggested_medicine": "consult doctor",
        }


# ─────────────────────────────────────────────────────────────
# Internal helpers
# ─────────────────────────────────────────────────────────────
async def generate_medical_report(text: str) -> dict:
    """
    Take raw doctor input (any language), detect language,
    translate to English if needed, and generate a structured
    medical report with extracted lab tests & medications.

    Uses multiple small AI calls to stay within model output limits.
    """
    fallback = _keyword_fallback(text)
    default_result = {
        "detected_language": "unknown",
        "original_text": text,
        "translated_text": text,
        "report": f"Consultation Notes:\n{text}",
        "symptom": "unknown",
        "confidence": 0.0,
        "suggested_test": "",
        "suggested_medicine": "",
        **fallback,
    }

    # ── Call 1: Diagnosis fields (compact) ───────────────────
    diag_prompt = (
        "You are a medical triage AI. Analyze the text and return ONLY valid JSON "
        "(no markdown):\n"
        '{"detected_language":"..","symptom":"..","confidence":0.8,'
        '"suggested_test":"..","suggested_medicine":".."}'
    )
    diag_text = await _call_ai(diag_prompt, text, temperature=0.2, max_tokens=512)
    diag = _extract_json(diag_text) if diag_text else {}

    # ── Call 2: Lab tests & medications ──────────────────────
    orders_prompt = (
        "You are a medical assistant AI. Extract lab tests and medications "
        "from the text. Return ONLY valid JSON (no markdown):\n"
        '{"lab_tests":[".."],"medications":[".."],"summary":"one sentence"}'
    )
    orders_text = await _call_ai(orders_prompt, text, temperature=0.2, max_tokens=512)
    orders = _extract_json(orders_text) if orders_text else {}

    # ── Call 3: Report text ──────────────────────────────────
    report_prompt = (
        "You are a medical documentation AI. Write a concise medical report "
        "(max 80 words) for the consultation below. "
        "Return ONLY the report text, no JSON, no markdown fences."
    )
    report_text = await _call_ai(report_prompt, text, temperature=0.3, max_tokens=512)

    # ── Merge results ────────────────────────────────────────
    return {
        "detected_language": diag.get("detected_language", "unknown"),
        "original_text":     text,
        "translated_text":   text,  # translation handled separately if needed
        "report":            report_text.strip() if report_text else f"Consultation Notes:\n{text}",
        "symptom":           diag.get("symptom", "unknown"),
        "confidence":        float(diag.get("confidence", 0.0)),
        "suggested_test":    diag.get("suggested_test", ""),
        "suggested_medicine": diag.get("suggested_medicine", ""),
        "lab_tests":         orders.get("lab_tests", fallback["lab_tests"]),
        "medications":       orders.get("medications", fallback["medications"]),
        "summary":           orders.get("summary", fallback["summary"]),
    }


def _parse_ai_json(text: str) -> dict:
    """
    Attempt to parse the AI's JSON response.
    Falls back to keyword detection if JSON parsing fails.
    """
    parsed = _extract_json(text)
    if parsed and ("lab_tests" in parsed or "medications" in parsed):
        return {
            "lab_tests":   parsed.get("lab_tests", []),
            "medications": parsed.get("medications", []),
            "summary":     parsed.get("summary", ""),
        }
    # Could not parse structured JSON – fall back to keyword scan on text
    return _keyword_fallback(text)


def _extract_json(text: str) -> dict:
    """Try to extract a JSON object from a string that might contain markdown fences."""
    # Strip markdown JSON fences if present
    cleaned = re.sub(r"```json\s*", "", text)
    cleaned = re.sub(r"```\s*", "", cleaned)
    try:
        return json.loads(cleaned)
    except json.JSONDecodeError:
        # Try to find a JSON object in the text
        match = re.search(r"\{.*\}", cleaned, re.DOTALL)
        if match:
            try:
                return json.loads(match.group())
            except json.JSONDecodeError:
                pass
    return {}


def _keyword_fallback(text: str) -> dict:
    """
    Simple keyword‑based extraction when the AI is unavailable.
    Scans the transcript for known lab‑test and medication keywords.
    """
    text_lower = text.lower()

    found_tests = [kw for kw in LAB_TEST_KEYWORDS if kw in text_lower]
    found_meds  = [kw for kw in MEDICATION_KEYWORDS if kw in text_lower]

    return {
        "lab_tests":   found_tests,
        "medications": found_meds,
        "summary":     "Analysis performed via keyword matching (AI unavailable).",
    }
