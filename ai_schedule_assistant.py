"""
ai_schedule_assistant.py  ─  Medi‑Flow Orchestrator  ─  AI Schedule Assistant

Two-step conversational flow:
  1. Doctor types a booking request (natural language)
  2. AI extracts patient, date, reason → system checks schedule →
     presents available 30-min slots (09:00–17:00)
  3. Doctor picks a slot → system books the appointment

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

# ── Config ───────────────────────────────────────────────────
API_BASE = "http://127.0.0.1:8000"

FLEX_API_KEY  = os.getenv("FLEX_API_KEY", "")
FLEX_API_BASE = os.getenv("FLEX_API_BASE", "https://aiworkshopapi.flexinfra.com.my/v1")
FLEX_MODEL    = os.getenv("FLEX_MODEL", "qwen2.5")

WORK_START = 9   # 09:00
WORK_END   = 17  # 17:00 (last slot at 16:30)


def _headers() -> dict:
    return {"Authorization": f"Bearer {st.session_state.token}"}


# ═════════════════════════════════════════════════════════════
#  AI Intent Parsing
# ═════════════════════════════════════════════════════════════

_SYSTEM_PROMPT = (
    "You are a medical schedule assistant.\n"
    "Extract booking details from the doctor's message.\n"
    "Return ONLY a JSON object with these keys (no extra text):\n"
    "{\n"
    '  "patient_name": "full name or empty string",\n'
    '  "date": "YYYY-MM-DD or relative like tomorrow",\n'
    '  "reason": "reason for visit or empty string"\n'
    "}\n"
    "If the message is NOT a booking request, return:\n"
    '{"intent": "chat", "reply": "your helpful reply"}\n'
    "Today's date is " + date.today().isoformat() + "."
)


def _call_ai_sync(user_message: str) -> str | None:
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
                return body.get("choices", [{}])[0].get("message", {}).get("content", "") or None
            logger.warning("AI returned %d: %s", resp.status_code, resp.text[:200])
    except Exception as exc:
        logger.warning("AI call failed: %s", exc)
    return None


def _extract_json(text: str) -> dict | None:
    if not text:
        return None
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


# ═════════════════════════════════════════════════════════════
#  Date helpers
# ═════════════════════════════════════════════════════════════

def _resolve_date(date_str: str) -> str | None:
    if not date_str:
        return None
    s = date_str.strip().lower()
    if re.match(r"\d{4}-\d{2}-\d{2}$", s):
        return s
    today = date.today()
    if s == "today":
        return today.isoformat()
    if s == "tomorrow":
        return (today + timedelta(days=1)).isoformat()
    if s == "day after tomorrow":
        return (today + timedelta(days=2)).isoformat()
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


# ═════════════════════════════════════════════════════════════
#  Regex fallback (extracts patient, date, reason — no time)
# ═════════════════════════════════════════════════════════════

def _regex_fallback(message: str) -> dict | None:
    text = message.lower()
    if not any(kw in text for kw in ["book", "schedule", "appointment", "reserve", "slot", "available"]):
        return None
    result = {"patient_name": "", "date": "", "reason": ""}
    m = re.search(
        r"(?:for|patient)\s+([A-Z][a-z]+(?:\s+(?:bin|binti|a/l|a/p|[A-Z])[a-z]*)*)",
        message, re.IGNORECASE,
    )
    if m:
        result["patient_name"] = m.group(1).strip()
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
    rm = re.search(
        r"(?:for|due to|because of|regarding)\s+(?:a\s+)?(\w[\w\s]{2,30}?)(?:\.|$)",
        text,
    )
    if rm:
        reason_candidate = rm.group(1).strip()
        if result["patient_name"] and result["patient_name"].lower() in reason_candidate.lower():
            pass
        else:
            result["reason"] = reason_candidate
    return result if result["patient_name"] else None


def parse_booking_request(message: str) -> dict:
    """Parse a doctor's message. Returns intent='schedule' with patient/date/reason (no time)."""
    ai_text = _call_ai_sync(message)
    parsed = _extract_json(ai_text)

    if parsed:
        if parsed.get("intent") == "chat":
            return {"intent": "chat", "reply": parsed.get("reply", "How can I help you?")}
        name = parsed.get("patient_name", "")
        if name:
            return {
                "intent": "schedule",
                "patient_name": name,
                "date": _resolve_date(parsed.get("date", "")) or "",
                "reason": parsed.get("reason", ""),
            }

    regex_result = _regex_fallback(message)
    if regex_result:
        return {
            "intent": "schedule",
            "patient_name": regex_result["patient_name"],
            "date": _resolve_date(regex_result.get("date", "")) or "",
            "reason": regex_result.get("reason", ""),
        }

    return {
        "intent": "chat",
        "reply": (
            "I couldn't parse your request. Try:\n"
            '> "Check schedule for **Tan Wei Ming** tomorrow for **fever**."'
        ),
    }


# ═════════════════════════════════════════════════════════════
#  Schedule helpers
# ═════════════════════════════════════════════════════════════

def get_doctor_schedule(appt_date: str) -> list[str]:
    """Fetch booked time-slots for the logged-in doctor on *appt_date*."""
    try:
        resp = requests.get(
            f"{API_BASE}/api/appointments/schedule",
            params={"date": appt_date},
            headers=_headers(),
            timeout=10,
        )
        if resp.status_code == 200:
            data = resp.json()
            return [s["time"] for s in data.get("booked_slots", [])]
    except requests.RequestException:
        pass
    return []


def find_available_slots(booked_times: list[str]) -> list[str]:
    """Generate 30-min slots from 09:00–17:00, excluding already booked ones."""
    slots: list[str] = []
    hour = WORK_START
    minute = 0
    while hour < WORK_END:
        slot = f"{hour:02d}:{minute:02d}"
        if slot not in booked_times:
            slots.append(slot)
        minute += 30
        if minute >= 60:
            minute = 0
            hour += 1
    return slots


# ═════════════════════════════════════════════════════════════
#  Backend helpers
# ═════════════════════════════════════════════════════════════

def _search_patient(name: str) -> dict | None:
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
                return results[0]
    except requests.RequestException:
        pass
    return None


def create_appointment(patient_id: int, patient_name: str,
                       appt_date: str, appt_time: str, reason: str) -> dict:
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
#  Chat message handler (two-step state machine)
# ═════════════════════════════════════════════════════════════

def _handle_message(message: str) -> str:
    """Process a doctor's chat message. Manages pending-booking state."""

    # ── Step A: If we're waiting for a slot selection ─────────
    pending = st.session_state.get("sched_pending")
    if pending:
        # Try to match a slot from the message (e.g. "10:00", "3", "#3")
        chosen_slot = _match_slot_selection(message, pending["available_slots"])
        if chosen_slot is None:
            return (
                "I didn't recognise a slot from your message.\n\n"
                "Please reply with the **slot number** (e.g. `3`) or **time** (e.g. `10:00`), "
                "or type **cancel** to start over."
            )

        # Book the appointment
        result = create_appointment(
            patient_id=pending["patient_id"],
            patient_name=pending["patient_name"],
            appt_date=pending["date"],
            appt_time=chosen_slot,
            reason=pending["reason"],
        )
        st.session_state.sched_pending = None  # clear pending

        if result["success"]:
            # ── Reset chat after successful booking ──────────
            confirm_msg = (
                f"✅ **Appointment booked!**\n\n"
                f"| Detail | Value |\n"
                f"|--------|-------|\n"
                f"| **Patient** | {result['patient_name']} |\n"
                f"| **Date** | {result['appointment_date']} |\n"
                f"| **Time** | {result['appointment_time']} |\n"
                f"| **Reason** | {pending['reason'] or 'General consultation'} |\n"
                f"| **Appointment ID** | #{result['appointment_id']} |"
            )
            st.session_state.sched_messages = [
                {"role": "assistant", "content": confirm_msg},
            ]
            # Signal render() to show success toast and rerun
            st.session_state["_sched_booking_success"] = True
            return confirm_msg
        return f"❌ Could not book: {result.get('error', 'Unknown error')}"

    # ── Step B: New request — parse and recommend slots ──────
    if message.strip().lower() == "cancel":
        return "Cancelled. Send a new booking request whenever you're ready."

    parsed = parse_booking_request(message)

    if parsed["intent"] == "chat":
        return parsed["reply"]

    name = parsed.get("patient_name", "")
    appt_date = parsed.get("date", "")
    reason = parsed.get("reason", "")

    if not name:
        return "I need at least the **patient name**. Try:\n> 'Schedule for **Ali bin Ahmad** tomorrow for fever.'"
    if not appt_date:
        return f"When would you like to schedule for **{name}**? Please include a **date**."

    # Search patient
    patient = _search_patient(name)
    if not patient:
        return (
            f"🔍 Patient **\"{name}\"** not found in the system.\n\n"
            "Please register the patient first, or check the spelling."
        )

    # Fetch schedule & find available slots
    booked = get_doctor_schedule(appt_date)
    available = find_available_slots(booked)

    if not available:
        return (
            f"😔 No available slots on **{appt_date}**. "
            "All time-slots (09:00–17:00) are booked.\n\n"
            "Try another date."
        )

    # Store pending booking (waiting for slot selection)
    st.session_state.sched_pending = {
        "patient_id": patient["patient_id"],
        "patient_name": patient["name"],
        "date": appt_date,
        "reason": reason,
        "available_slots": available,
    }

    # ── Build clean vertical slot display ────────────────
    # Each time-slot on its own line for readability
    slot_lines = "\n".join(f"• `{slot}`" for slot in available)

    booked_section = ""
    if booked:
        booked_lines = "\n".join(f"  ⛔ `{t}`" for t in sorted(booked))
        booked_section = f"\n\n**Already Booked:**\n{booked_lines}"

    return (
        f"### 📅 Available Appointment Slots\n\n"
        f"**Patient:** {patient['name']}\n\n"
        f"**Date:** {appt_date}\n\n"
        f"**Available Times:**\n\n"
        f"{slot_lines}"
        f"{booked_section}\n\n"
        f"---\n"
        f"👇 **Pick a slot below** or reply with the time (e.g. `10:00`), or type **cancel**."
    )


def _match_slot_selection(message: str, available_slots: list[str]) -> str | None:
    """Match user reply to one of the available slots."""
    text = message.strip().lower()

    if text in ("cancel", "no", "nevermind"):
        st.session_state.sched_pending = None
        return None  # signal cancellation handled upstream

    # Direct time match (e.g. "10:00", "10:30")
    time_match = re.search(r"\b(\d{1,2}:\d{2})\b", text)
    if time_match:
        t = time_match.group(1)
        # Normalize to HH:MM
        parts = t.split(":")
        normalised = f"{int(parts[0]):02d}:{parts[1]}"
        if normalised in available_slots:
            return normalised

    # Slot number (e.g. "3", "#3")
    num_match = re.search(r"#?(\d{1,2})\b", text)
    if num_match:
        idx = int(num_match.group(1)) - 1
        if 0 <= idx < len(available_slots):
            return available_slots[idx]

    return None


# ═════════════════════════════════════════════════════════════
#  Status badge helpers
# ═════════════════════════════════════════════════════════════
_STATUS_ICON = {"scheduled": "🟢", "completed": "✅", "cancelled": "🔴"}


# ═════════════════════════════════════════════════════════════
#  Main entry point
# ═════════════════════════════════════════════════════════════

def render():
    st.title("📅 AI Schedule Assistant")

    # ── Session state ────────────────────────────────────────
    if "sched_messages" not in st.session_state:
        st.session_state.sched_messages = [
            {
                "role": "assistant",
                "content": (
                    "Hello doctor! 👋 I'm your **AI Schedule Assistant**.\n\n"
                    "Tell me who you'd like to schedule and when, and I'll show you "
                    "the available time-slots.\n\n"
                    "Try:\n"
                    '> "Schedule appointment for **Tan Wei Ming** tomorrow for **fever**."'
                ),
            }
        ]
    if "sched_pending" not in st.session_state:
        st.session_state.sched_pending = None

    # ── Layout: Chat + Appointments sidebar ──────────────────
    col_chat, col_appts = st.columns([3, 2])

    with col_appts:
        with st.container(border=True):
            st.markdown("#### 📋 Appointments")
            appointments = _fetch_appointments()
            if appointments:
                for a in appointments:
                    icon = _STATUS_ICON.get(a.get("status", ""), "⚪")
                    with st.container(border=True):
                        st.markdown(f"{icon} **{a.get('patient_name', 'Unknown')}**")
                        st.caption(
                            f"📆 {a.get('appointment_date', '')}  "
                            f"🕐 {a.get('appointment_time', '')}  "
                        )
                        if a.get("reason"):
                            st.caption(f"Reason: {a['reason']}")
            else:
                st.info("No appointments yet.")
            if st.button("🔄 Refresh", key="sched_refresh_appts"):
                st.rerun()

    with col_chat:
        # ── Handle clickable slot-button clicks (before rendering) ──
        # Streamlit buttons trigger a rerun; check if one was pressed
        pending = st.session_state.get("sched_pending")
        if pending and st.session_state.get("_sched_picked_slot"):
            picked = st.session_state.pop("_sched_picked_slot")
            result = create_appointment(
                patient_id=pending["patient_id"],
                patient_name=pending["patient_name"],
                appt_date=pending["date"],
                appt_time=picked,
                reason=pending["reason"],
            )
            st.session_state.sched_pending = None
            if result["success"]:
                confirm_msg = (
                    f"✅ **Appointment booked!**\n\n"
                    f"| Detail | Value |\n"
                    f"|--------|-------|\n"
                    f"| **Patient** | {result['patient_name']} |\n"
                    f"| **Date** | {result['appointment_date']} |\n"
                    f"| **Time** | {result['appointment_time']} |\n"
                    f"| **Reason** | {pending['reason'] or 'General consultation'} |\n"
                    f"| **Appointment ID** | #{result['appointment_id']} |"
                )
                # ── Reset chat after successful booking ──────
                st.session_state.sched_messages = [
                    {"role": "assistant", "content": confirm_msg},
                ]
                st.success("✅ Appointment booked successfully! Chat has been reset.")
                st.rerun()
            else:
                confirm_msg = f"❌ Could not book: {result.get('error', 'Unknown error')}"
                st.session_state.sched_messages.append(
                    {"role": "user", "content": f"Book slot `{picked}`"}
                )
                st.session_state.sched_messages.append(
                    {"role": "assistant", "content": confirm_msg}
                )
            st.rerun()

        # ── Chat message history ─────────────────────────────
        with st.container(border=True):
            st.markdown("#### 💬 Chat")
            for msg in st.session_state.sched_messages:
                with st.chat_message(msg["role"]):
                    st.markdown(msg["content"])

        # ── Clickable slot-picker buttons (shown when pending) ──
        pending = st.session_state.get("sched_pending")
        if pending:
            with st.container(border=True):
                st.markdown("### 🕐 Pick a Time Slot")
                st.markdown(f"**Date:** {pending['date']}")
                st.markdown(f"**Patient:** {pending['patient_name']}")
                st.divider()

                # Render slot buttons in a grid (4 columns)
                cols = st.columns(4)
                for i, slot in enumerate(pending["available_slots"]):
                    with cols[i % 4]:
                        if st.button(
                            f"🕐 {slot}",
                            key=f"slot_btn_{slot}",
                            use_container_width=True,
                        ):
                            # Store picked slot and rerun to trigger booking above
                            st.session_state["_sched_picked_slot"] = slot
                            st.rerun()

                # Cancel button
                if st.button("❌ Cancel", key="sched_cancel_btn"):
                    st.session_state.sched_pending = None
                    st.session_state.sched_messages.append(
                        {"role": "assistant", "content": "Booking cancelled. Send a new request anytime."}
                    )
                    st.rerun()

        # ── Chat text input ──────────────────────────────────
        user_input = st.chat_input(
            "e.g. Schedule for Ali tomorrow for cough",
            key="sched_chat_input",
        )

        if user_input:
            st.session_state.sched_messages.append(
                {"role": "user", "content": user_input}
            )
            with st.spinner("🤖 Checking schedule …"):
                response = _handle_message(user_input)

            # Check if _handle_message already reset chat (successful booking)
            if st.session_state.pop("_sched_booking_success", False):
                st.success("✅ Appointment booked successfully! Chat has been reset.")
            else:
                st.session_state.sched_messages.append(
                    {"role": "assistant", "content": response}
                )
            st.rerun()
