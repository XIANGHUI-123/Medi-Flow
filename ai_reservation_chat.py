"""
ai_reservation_chat.py  ─  Medi‑Flow Orchestrator  ─  AI Chat Assistant

Natural-language chat interface that lets doctors book patient appointments
by typing messages like:
    "Book appointment for Tan Wei Ming tomorrow at 10am for fever."

Workflow:
  1. Doctor types a message in the chat box
  2. AI parses the message to extract: patient_name, date, time, reason
  3. System searches the patient in the database
  4. Checks for time-slot conflicts
  5. Creates the appointment via the backend API
  6. AI replies with a confirmation (or error)

Entry point: render()
"""

import json
import os
import re
import logging
from datetime import date, timedelta

import httpx
import requests
import streamlit as st
from dotenv import load_dotenv

load_dotenv(override=True)
logger = logging.getLogger(__name__)

# ── Backend / AI config ──────────────────────────────────────
API_BASE = "http://127.0.0.1:8000"

# Flex AI (same config as ai_service.py)
FLEX_API_KEY  = os.getenv("FLEX_API_KEY", "")
FLEX_API_BASE = os.getenv("FLEX_API_BASE", "https://aiworkshopapi.flexinfra.com.my/v1")
FLEX_MODEL    = os.getenv("FLEX_MODEL", "qwen2.5")


def _headers() -> dict:
    return {"Authorization": f"Bearer {st.session_state.token}"}


# ═════════════════════════════════════════════════════════════
#  AI Intent Parsing
# ═════════════════════════════════════════════════════════════

_SYSTEM_PROMPT = """You are a medical appointment booking assistant.
Extract booking details from the doctor's message.
Return ONLY a JSON object with these keys (no extra text):
{
  "patient_name": "full name or empty string",
  "date": "YYYY-MM-DD or relative like 'tomorrow'",
  "time": "HH:MM in 24-hour format",
  "reason": "reason for visit or empty string"
}
If the message is NOT a booking request, return:
{"intent": "chat", "reply": "your helpful reply"}
Today's date is """ + date.today().isoformat() + "."


def _call_ai_sync(user_message: str) -> str | None:
    """Synchronous AI call to Flex AI for intent parsing."""
    if not FLEX_API_KEY:
        return None
    headers = {
        "Authorization": f"Bearer {FLEX_API_KEY}",
        "Content-Type": "application/json",
    }
    payload = {
        "model": FLEX_MODEL,
        "messages": [
            {"role": "system", "content": _SYSTEM_PROMPT},
            {"role": "user",   "content": user_message},
        ],
        "temperature": 0.1,
        "max_tokens": 300,
    }
    try:
        with httpx.Client(timeout=30, verify=False) as client:
            resp = client.post(
                f"{FLEX_API_BASE.rstrip('/')}/chat/completions",
                headers=headers,
                json=payload,
            )
            if resp.status_code < 400:
                body = resp.json()
                text = body.get("choices", [{}])[0].get("message", {}).get("content", "")
                return text if text else None
            else:
                logger.warning("AI chat returned %d: %s", resp.status_code, resp.text[:200])
    except Exception as exc:
        logger.warning("AI chat call failed: %s", exc)
    return None


def _extract_json(text: str) -> dict | None:
    """Robustly extract a JSON object from AI response text."""
    if not text:
        return None
    # Try to find JSON block in markdown fences or raw
    m = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", text, re.DOTALL)
    if m:
        try:
            return json.loads(m.group(1))
        except json.JSONDecodeError:
            pass
    m = re.search(r"\{[^{}]*\}", text, re.DOTALL)
    if m:
        try:
            return json.loads(m.group(0))
        except json.JSONDecodeError:
            pass
    return None


def _resolve_date(date_str: str) -> str | None:
    """Convert relative dates (tomorrow, today, next monday) to YYYY-MM-DD."""
    if not date_str:
        return None
    s = date_str.strip().lower()

    # Already in ISO format
    if re.match(r"\d{4}-\d{2}-\d{2}$", s):
        return s

    today = date.today()

    if s == "today":
        return today.isoformat()
    if s == "tomorrow":
        return (today + timedelta(days=1)).isoformat()
    if s == "day after tomorrow":
        return (today + timedelta(days=2)).isoformat()

    # "next monday", "next friday", etc.
    days_map = {
        "monday": 0, "tuesday": 1, "wednesday": 2, "thursday": 3,
        "friday": 4, "saturday": 5, "sunday": 6,
    }
    m = re.match(r"next\s+(\w+)", s)
    if m:
        day_name = m.group(1).lower()
        if day_name in days_map:
            target = days_map[day_name]
            current = today.weekday()
            delta = (target - current) % 7
            if delta == 0:
                delta = 7
            return (today + timedelta(days=delta)).isoformat()

    # Try parsing as-is
    try:
        from datetime import datetime as dt
        for fmt in ("%Y-%m-%d", "%d/%m/%Y", "%d-%m-%Y", "%B %d", "%b %d"):
            try:
                parsed = dt.strptime(s, fmt)
                if parsed.year == 1900:
                    parsed = parsed.replace(year=today.year)
                return parsed.date().isoformat()
            except ValueError:
                continue
    except Exception:
        pass

    return None


def _normalize_time(time_str: str) -> str | None:
    """Normalise time strings like '10am', '2:30 PM', '14:00' → 'HH:MM'."""
    if not time_str:
        return None
    s = time_str.strip().lower().replace(".", ":")

    # Already HH:MM
    m = re.match(r"(\d{1,2}):(\d{2})$", s)
    if m:
        h, mins = int(m.group(1)), int(m.group(2))
        if 0 <= h <= 23 and 0 <= mins <= 59:
            return f"{h:02d}:{mins:02d}"

    # "10am", "2pm", "2:30pm"
    m = re.match(r"(\d{1,2})(?::(\d{2}))?\s*(am|pm)$", s)
    if m:
        h = int(m.group(1))
        mins = int(m.group(2) or 0)
        if m.group(3) == "pm" and h != 12:
            h += 12
        if m.group(3) == "am" and h == 12:
            h = 0
        if 0 <= h <= 23 and 0 <= mins <= 59:
            return f"{h:02d}:{mins:02d}"

    return None


def _regex_fallback(message: str) -> dict | None:
    """Simple regex-based extraction when AI is unavailable."""
    text = message.lower()

    # Check if it looks like a booking request
    if not any(kw in text for kw in ["book", "schedule", "appointment", "reserve"]):
        return None

    result = {"patient_name": "", "date": "", "time": "", "reason": ""}

    # Extract name: "for <Name>" pattern
    m = re.search(
        r"(?:for|patient)\s+([A-Z][a-z]+(?:\s+(?:bin|binti|a/l|a/p|[A-Z])[a-z]*)*)",
        message, re.IGNORECASE,
    )
    if m:
        result["patient_name"] = m.group(1).strip()

    # Extract date
    for pattern, resolver in [
        (r"\b(tomorrow)\b", lambda m: "tomorrow"),
        (r"\b(today)\b", lambda m: "today"),
        (r"\b(day after tomorrow)\b", lambda m: "day after tomorrow"),
        (r"\b(\d{4}-\d{2}-\d{2})\b", lambda m: m.group(1)),
        (r"\b(\d{1,2}/\d{1,2}/\d{4})\b", lambda m: m.group(1)),
        (r"\bnext\s+(monday|tuesday|wednesday|thursday|friday|saturday|sunday)\b",
         lambda m: f"next {m.group(1)}"),
    ]:
        dm = re.search(pattern, text)
        if dm:
            result["date"] = resolver(dm)
            break

    # Extract time
    tm = re.search(r"\b(\d{1,2}(?::\d{2})?\s*(?:am|pm))\b", text, re.IGNORECASE)
    if tm:
        result["time"] = tm.group(1)
    else:
        tm = re.search(r"\bat\s+(\d{1,2}:\d{2})\b", text)
        if tm:
            result["time"] = tm.group(1)

    # Extract reason: "for <reason>" after time, or common keywords
    rm = re.search(
        r"(?:for|due to|because of|regarding)\s+(?:a\s+)?(\w[\w\s]{2,30}?)(?:\.|$)",
        text,
    )
    if rm:
        reason_candidate = rm.group(1).strip()
        # Don't capture the patient name as reason
        if result["patient_name"] and result["patient_name"].lower() in reason_candidate.lower():
            pass
        else:
            result["reason"] = reason_candidate

    return result if result["patient_name"] else None


def parse_booking_request(message: str) -> dict:
    """
    Parse a doctor's natural-language booking message.

    Returns:
        {
            "intent": "book" | "chat",
            "patient_name": str,
            "date": "YYYY-MM-DD",
            "time": "HH:MM",
            "reason": str,
            "reply": str    (only for chat intent)
        }
    """
    # ── Try AI parsing first ─────────────────────────────────
    ai_text = _call_ai_sync(message)
    parsed = _extract_json(ai_text)

    if parsed:
        # AI returned a chat response (not a booking)
        if parsed.get("intent") == "chat":
            return {
                "intent": "chat",
                "reply": parsed.get("reply", "How can I help you?"),
            }

        # AI returned booking fields
        name = parsed.get("patient_name", "")
        if name:
            resolved_date = _resolve_date(parsed.get("date", ""))
            resolved_time = _normalize_time(parsed.get("time", ""))
            return {
                "intent": "book",
                "patient_name": name,
                "date": resolved_date or "",
                "time": resolved_time or "",
                "reason": parsed.get("reason", ""),
            }

    # ── Fallback to regex parsing ────────────────────────────
    regex_result = _regex_fallback(message)
    if regex_result:
        resolved_date = _resolve_date(regex_result.get("date", ""))
        resolved_time = _normalize_time(regex_result.get("time", ""))
        return {
            "intent": "book",
            "patient_name": regex_result["patient_name"],
            "date": resolved_date or "",
            "time": resolved_time or "",
            "reason": regex_result.get("reason", ""),
        }

    # ── Neither AI nor regex could parse → treat as general chat
    if ai_text:
        return {"intent": "chat", "reply": ai_text}
    return {
        "intent": "chat",
        "reply": (
            "I can help you book appointments! Try saying:\n"
            '> "Book appointment for **Tan Wei Ming** tomorrow at **10am** for **fever**."'
        ),
    }


# ═════════════════════════════════════════════════════════════
#  Backend helpers
# ═════════════════════════════════════════════════════════════

def _search_patient(name: str) -> dict | None:
    """Search for a patient by name via the backend API."""
    try:
        resp = requests.get(
            f"{API_BASE}/api/patients/search",
            params={"q": name},
            headers=_headers(),
            timeout=10,
        )
        if resp.status_code == 200:
            results = resp.json()
            if results:
                # Return best match (first result)
                return results[0]
    except requests.RequestException:
        pass
    return None


def _create_appointment(patient_id: int, patient_name: str,
                        appt_date: str, appt_time: str, reason: str) -> dict:
    """Create an appointment via the backend API. Returns response dict."""
    try:
        resp = requests.post(
            f"{API_BASE}/api/appointments",
            data={
                "patient_id": patient_id,
                "patient_name": patient_name,
                "appointment_date": appt_date,
                "appointment_time": appt_time,
                "reason": reason,
            },
            headers=_headers(),
            timeout=15,
        )
        if resp.status_code == 200:
            return {"success": True, **resp.json()}
        elif resp.status_code == 409:
            return {"success": False, "error": resp.json().get("detail", "Time slot conflict.")}
        else:
            return {"success": False, "error": resp.json().get("detail", resp.text)}
    except requests.RequestException as e:
        return {"success": False, "error": f"Backend not reachable: {e}"}


def _fetch_appointments() -> list:
    """Fetch all appointments for the current doctor."""
    try:
        resp = requests.get(
            f"{API_BASE}/api/appointments",
            headers=_headers(),
            timeout=10,
        )
        if resp.status_code == 200:
            return resp.json()
    except requests.RequestException:
        pass
    return []


# ═════════════════════════════════════════════════════════════
#  Chat message handler
# ═════════════════════════════════════════════════════════════

def _handle_message(message: str) -> str:
    """Process a doctor's chat message and return the AI response."""

    # Step 1: Parse intent
    parsed = parse_booking_request(message)

    if parsed["intent"] == "chat":
        return parsed["reply"]

    # Step 2: Validate extracted fields
    name = parsed.get("patient_name", "")
    appt_date = parsed.get("date", "")
    appt_time = parsed.get("time", "")
    reason = parsed.get("reason", "")

    missing = []
    if not name:
        missing.append("**patient name**")
    if not appt_date:
        missing.append("**date**")
    if not appt_time:
        missing.append("**time**")

    if missing:
        return (
            f"I couldn't extract the following from your message: {', '.join(missing)}.\n\n"
            "Please try again with a complete request, for example:\n"
            '> "Book appointment for **Tan Wei Ming** on **2026-03-20** at **10:00** for **fever**."'
        )

    # Step 3: Search patient in database
    patient = _search_patient(name)
    if not patient:
        return (
            f"🔍 Patient **\"{name}\"** not found in the system.\n\n"
            "Please register the patient first, or check the spelling."
        )

    # Step 4: Create the appointment
    result = _create_appointment(
        patient_id=patient["patient_id"],
        patient_name=patient["name"],
        appt_date=appt_date,
        appt_time=appt_time,
        reason=reason,
    )

    if result["success"]:
        return (
            f"✅ **Appointment booked successfully!**\n\n"
            f"| Detail | Value |\n"
            f"|--------|-------|\n"
            f"| **Patient** | {result['patient_name']} (ID: {patient['patient_id']}) |\n"
            f"| **Date** | {result['appointment_date']} |\n"
            f"| **Time** | {result['appointment_time']} |\n"
            f"| **Reason** | {reason or 'General consultation'} |\n"
            f"| **Appointment ID** | #{result['appointment_id']} |"
        )
    else:
        error = result.get("error", "Unknown error")
        if "already booked" in error.lower() or "409" in str(error):
            return f"⚠️ That time slot is already booked. Please choose another time.\n\n_{error}_"
        return f"❌ Could not create appointment: {error}"


# ═════════════════════════════════════════════════════════════
#  Status badge helpers
# ═════════════════════════════════════════════════════════════

_STATUS_ICON = {"scheduled": "🟢", "completed": "✅", "cancelled": "🔴"}


# ═════════════════════════════════════════════════════════════
#  Main entry point
# ═════════════════════════════════════════════════════════════

def render():
    st.title("🤖 AI Appointment Assistant")

    # ── Session state for chat history ───────────────────────
    if "chat_messages" not in st.session_state:
        st.session_state.chat_messages = [
            {
                "role": "assistant",
                "content": (
                    "Hello doctor! 👋 I'm your AI appointment assistant.\n\n"
                    "You can book appointments using natural language. Try:\n"
                    '> "Book appointment for **Tan Wei Ming** tomorrow at **10am** for **fever**."'
                ),
            }
        ]

    # ── Layout: Chat + Appointments sidebar ──────────────────
    col_chat, col_appts = st.columns([3, 2])

    # ── Right column: Today's appointments ───────────────────
    with col_appts:
        with st.container(border=True):
            st.markdown("#### 📋 Appointments")
            appointments = _fetch_appointments()

            if appointments:
                for a in appointments:
                    status = a.get("status", "scheduled")
                    icon = _STATUS_ICON.get(status, "⚪")
                    with st.container(border=True):
                        st.markdown(
                            f"{icon} **{a.get('patient_name', 'Unknown')}**"
                        )
                        st.caption(
                            f"📆 {a.get('appointment_date', '')}  "
                            f"🕐 {a.get('appointment_time', '')}  "
                        )
                        if a.get("reason"):
                            st.caption(f"Reason: {a['reason']}")
            else:
                st.info("No appointments yet.")

            if st.button("🔄 Refresh", key="chat_refresh_appts"):
                st.rerun()

    # ── Left column: Chat interface ──────────────────────────
    with col_chat:
        with st.container(border=True):
            st.markdown("#### 💬 Chat")

            # Display chat history
            for msg in st.session_state.chat_messages:
                with st.chat_message(msg["role"]):
                    st.markdown(msg["content"])

        # Chat input (must be outside container for Streamlit to render it at bottom)
        user_input = st.chat_input(
            "Type your message… e.g. Book appointment for Ali tomorrow at 9am for cough",
            key="chat_input",
        )

        if user_input:
            # Add user message to history
            st.session_state.chat_messages.append(
                {"role": "user", "content": user_input}
            )

            # Process and get AI response
            with st.spinner("🤖 Thinking …"):
                response = _handle_message(user_input)

            # Add assistant response to history
            st.session_state.chat_messages.append(
                {"role": "assistant", "content": response}
            )

            st.rerun()
