"""
reservation_page.py  ─  Medi‑Flow Orchestrator  ─  Reservations Page

Features:
  • New Reservation form (with patient selector & scheduling)
  • My Reservations table with AI Risk Detection
  • Keyword-based risk classifier (HIGH / MEDIUM / LOW)
  • Colour-coded risk badges and status indicators
  • Filter by date, status, risk level
  • Auto-refresh via cached data (15 s TTL)

Entry point: render()
"""

import re
from datetime import date as _date

import pandas as pd
import requests
import streamlit as st

# ── Backend ──────────────────────────────────────────────────
API_BASE = "http://127.0.0.1:8000"


def _headers() -> dict:
    return {"Authorization": f"Bearer {st.session_state.token}"}


# ═════════════════════════════════════════════════════════════
#  AI Risk Detection
# ═════════════════════════════════════════════════════════════

# Keyword → risk level mapping (checked in priority order)
_HIGH_KEYWORDS = [
    "chest pain", "difficulty breathing", "severe bleeding",
    "unconscious", "stroke", "heart attack", "seizure",
    "anaphylaxis", "cardiac arrest", "coma",
]
_MEDIUM_KEYWORDS = [
    "fever", "infection", "persistent cough", "vomiting",
    "abdominal pain", "high blood pressure", "dizziness",
    "shortness of breath", "diarrhoea", "dehydration",
]
_LOW_KEYWORDS = [
    "headache", "mild cough", "skin rash", "back pain",
    "sore throat", "runny nose", "allergies", "fatigue",
    "muscle ache", "routine checkup", "follow up",
]


def detect_risk_level(symptom_text: str) -> dict:
    """
    Analyse a symptom / reason string and classify into a risk level.

    Returns:
        {
            "risk_level": "HIGH" | "MEDIUM" | "LOW",
            "alert_message": "..."   # contextual warning
        }
    """
    if not symptom_text:
        return {"risk_level": "LOW", "alert_message": "No symptom information provided."}

    text = symptom_text.lower()

    # Check HIGH first (most critical)
    for kw in _HIGH_KEYWORDS:
        if kw in text:
            return {
                "risk_level": "HIGH",
                "alert_message": f"⚠️ Critical symptom detected: {kw.title()}. Prioritise this patient.",
            }

    # Then MEDIUM
    for kw in _MEDIUM_KEYWORDS:
        if kw in text:
            return {
                "risk_level": "MEDIUM",
                "alert_message": f"⚡ Moderate symptom detected: {kw.title()}. Monitor closely.",
            }

    # Then LOW (explicit match)
    for kw in _LOW_KEYWORDS:
        if kw in text:
            return {
                "risk_level": "LOW",
                "alert_message": "✅ Low-risk case. Standard care applies.",
            }

    # Default to LOW if no keyword matches
    return {"risk_level": "LOW", "alert_message": "✅ No high-risk indicators found."}


# ── Risk badge helpers ───────────────────────────────────────
_RISK_COLOURS = {"HIGH": "#DC3545", "MEDIUM": "#FD7E14", "LOW": "#28A745"}
_RISK_ICONS   = {"HIGH": "🔴", "MEDIUM": "🟠", "LOW": "🟢"}


def _risk_badge(level: str) -> str:
    colour = _RISK_COLOURS.get(level, "#999")
    icon = _RISK_ICONS.get(level, "⚪")
    return (
        f'{icon} <span style="background:{colour};color:#fff;padding:2px 10px;'
        f'border-radius:10px;font-size:0.85em;font-weight:600;">{level}</span>'
    )


# ── Status helpers ───────────────────────────────────────────
_STATUS_ICON = {
    "scheduled": "🟢", "in_progress": "🔵",
    "completed": "✅", "cancelled": "🔴",
}


# ── Data fetching ────────────────────────────────────────────
@st.cache_data(ttl=15, show_spinner=False)
def _fetch_reservations(_token: str):
    try:
        resp = requests.get(
            f"{API_BASE}/api/reservations",
            headers={"Authorization": f"Bearer {_token}"},
            timeout=10,
        )
        if resp.status_code == 200:
            return resp.json()
    except requests.RequestException:
        pass
    return []


@st.cache_data(ttl=60, show_spinner=False)
def _fetch_patients(_token: str):
    try:
        resp = requests.get(
            f"{API_BASE}/api/patients",
            headers={"Authorization": f"Bearer {_token}"},
            timeout=10,
        )
        if resp.status_code == 200:
            return resp.json()
    except requests.RequestException:
        pass
    return []


# ── Fetch appointment bookings (from AI Scheduler) ──────────
@st.cache_data(ttl=15, show_spinner=False)
def _fetch_appointments(_token: str):
    """Load appointments booked via the AI Schedule Assistant."""
    try:
        resp = requests.get(
            f"{API_BASE}/api/appointments",
            headers={"Authorization": f"Bearer {_token}"},
            timeout=10,
        )
        if resp.status_code == 200:
            return resp.json()
    except requests.RequestException:
        pass
    return []


# ═════════════════════════════════════════════════════════════
#  Main entry point
# ═════════════════════════════════════════════════════════════
def render():
    st.title("📅 Operation Reservations")

    token = st.session_state.get("token", "")

    # Two tabs: New Reservation, My Appointments
    tab_new, tab_appts = st.tabs(
        ["➕ New Reservation", "🗓️ My Appointments"]
    )

    # ─────────────────────────────────────────────────────────
    #  TAB 1 — Book New Reservation
    # ─────────────────────────────────────────────────────────
    with tab_new:
        _render_new_reservation(token)

    # ─────────────────────────────────────────────────────────
    #  TAB 2 — My Appointments (booked via AI Scheduler)
    # ─────────────────────────────────────────────────────────
    with tab_appts:
        _render_my_appointments(token)


# ═════════════════════════════════════════════════════════════
#  TAB 1 — New Reservation Form
# ═════════════════════════════════════════════════════════════
def _render_new_reservation(token: str):
    patients = _fetch_patients(token)
    patient_opts = {
        f"{p['name']} (ID {p['patient_id']})": p["patient_id"]
        for p in patients
    }

    with st.container(border=True):
        st.markdown("#### 🗓️ Book Operation / Procedure")

        sel_patient = st.selectbox(
            "Patient",
            list(patient_opts.keys()) or ["No patients"],
            key="res_patient",
        )

        operation = st.text_input(
            "Operation / Procedure / Reason",
            placeholder="e.g. Appendectomy, Chest pain follow-up, MRI Scan …",
            key="res_operation",
        )

        # ── Live risk preview while typing ───────────────────
        if operation and operation.strip():
            risk = detect_risk_level(operation)
            st.markdown(
                _risk_badge(risk["risk_level"]) + f"&nbsp;&nbsp;{risk['alert_message']}",
                unsafe_allow_html=True,
            )

        c1, c2, c3 = st.columns(3)
        with c1:
            sched_date = st.date_input(
                "Scheduled Date", key="res_date", min_value=_date.today(),
            )
        with c2:
            sched_time = st.time_input("Scheduled Time", key="res_time")
        with c3:
            duration = st.number_input(
                "Duration (min)", min_value=15, max_value=480,
                value=60, step=15, key="res_duration",
            )

        notes = st.text_area(
            "Notes (optional)", key="res_notes",
            placeholder="Pre-op instructions, allergies, symptoms …",
        )

    if st.button("✅ Book Reservation", type="primary", key="btn_book_res",
                 use_container_width=True):
        pid = patient_opts.get(sel_patient)
        if pid is None:
            st.warning("Please select a patient.")
        elif not operation.strip():
            st.warning("Please enter the operation / reason.")
        else:
            resp = requests.post(
                f"{API_BASE}/api/reservations",
                data={
                    "patient_id": pid,
                    "operation_type": operation.strip(),
                    "scheduled_date": sched_date.isoformat(),
                    "scheduled_time": sched_time.strftime("%H:%M"),
                    "duration_min": int(duration),
                    "notes": notes.strip(),
                },
                headers=_headers(),
                timeout=15,
            )
            if resp.status_code == 200:
                _fetch_reservations.clear()
                st.success("✅ Reservation booked successfully!")
                st.rerun()
            else:
                st.error(resp.json().get("detail", resp.text))


# ═════════════════════════════════════════════════════════════
#  TAB 2 — Reservation List + AI Risk Table
# ═════════════════════════════════════════════════════════════
def _render_reservation_list(token: str):
    reservations = _fetch_reservations(token)

    if not reservations:
        st.info("No reservations yet. Book one from the **New Reservation** tab.")
        return

    # ── Attach AI risk to each reservation ───────────────────
    for r in reservations:
        # Combine operation_type + notes for richer risk analysis
        symptom_text = (r.get("operation_type", "") + " " + (r.get("notes") or "")).strip()
        risk = detect_risk_level(symptom_text)
        r["_risk_level"] = risk["risk_level"]
        r["_alert"]      = risk["alert_message"]

    # ── Filters ──────────────────────────────────────────────
    with st.container(border=True):
        st.markdown("#### 🔍 Filters")
        f1, f2, f3 = st.columns(3)

        with f1:
            status_filter = st.selectbox(
                "Status",
                ["All", "Scheduled", "In Progress", "Completed", "Cancelled"],
                key="res_filter_status",
            )
        with f2:
            risk_filter = st.selectbox(
                "AI Risk Level",
                ["All", "HIGH", "MEDIUM", "LOW"],
                key="res_filter_risk",
            )
        with f3:
            name_search = st.text_input(
                "Patient name",
                placeholder="e.g. Tan Wei Ming",
                key="res_filter_name",
            )

    # ── Apply filters ────────────────────────────────────────
    filtered = reservations

    _STATUS_MAP = {
        "Scheduled": "scheduled", "In Progress": "in_progress",
        "Completed": "completed", "Cancelled": "cancelled",
    }
    if status_filter != "All":
        s_val = _STATUS_MAP.get(status_filter, status_filter.lower())
        filtered = [r for r in filtered if r.get("status") == s_val]

    if risk_filter != "All":
        filtered = [r for r in filtered if r.get("_risk_level") == risk_filter]

    if name_search and name_search.strip():
        q = name_search.strip().lower()
        filtered = [r for r in filtered if q in (r.get("patient_name") or "").lower()]

    # ── Summary metrics ──────────────────────────────────────
    with st.container(border=True):
        m1, m2, m3, m4 = st.columns(4)
        m1.metric("Total", len(filtered))
        m2.metric("🔴 High Risk",   sum(1 for r in filtered if r["_risk_level"] == "HIGH"))
        m3.metric("🟠 Medium Risk", sum(1 for r in filtered if r["_risk_level"] == "MEDIUM"))
        m4.metric("🟢 Low Risk",    sum(1 for r in filtered if r["_risk_level"] == "LOW"))

    # ── Orders table (dataframe) ─────────────────────────────
    with st.container(border=True):
        st.markdown("#### 📊 Reservations Overview")

        rows = []
        for r in filtered:
            status = r.get("status", "scheduled")
            s_icon = _STATUS_ICON.get(status, "⚪")
            risk_icon = _RISK_ICONS.get(r["_risk_level"], "⚪")
            rows.append({
                "Time":       f"{r.get('scheduled_date', '')}  {r.get('scheduled_time', '')}",
                "Patient":    r.get("patient_name", "Unknown"),
                "Reason":     r.get("operation_type", ""),
                "AI Risk":    f"{risk_icon} {r['_risk_level']}",
                "Status":     f"{s_icon} {status.replace('_', ' ').title()}",
                "Duration":   f"{r.get('duration_min', 60)} min",
            })

        if rows:
            df = pd.DataFrame(rows)
            st.dataframe(df, use_container_width=True, hide_index=True, key="res_table")
        else:
            st.info("No reservations match the current filters.")

    # ── Detailed cards (sorted: HIGH first) ──────────────────
    _RISK_ORDER = {"HIGH": 0, "MEDIUM": 1, "LOW": 2}
    sorted_res = sorted(filtered, key=lambda r: _RISK_ORDER.get(r["_risk_level"], 9))

    with st.container(border=True):
        st.markdown("#### 📋 Detailed View")

        for r in sorted_res:
            risk_level = r["_risk_level"]
            status     = r.get("status", "scheduled")
            s_icon     = _STATUS_ICON.get(status, "⚪")

            with st.container(border=True):
                c1, c2, c3, c4 = st.columns([2.5, 3, 2, 2])

                with c1:
                    st.markdown(f"**{r.get('patient_name', 'Unknown')}**")
                    st.caption(
                        f"📆 {r.get('scheduled_date', '')}  "
                        f"🕐 {r.get('scheduled_time', '')}  "
                        f"⏱️ {r.get('duration_min', 60)} min"
                    )

                with c2:
                    st.markdown(f"**{r.get('operation_type', '')}**")
                    if r.get("notes"):
                        st.caption(f"Notes: {r['notes']}")

                with c3:
                    st.markdown(_risk_badge(risk_level), unsafe_allow_html=True)
                    st.caption(r["_alert"])

                with c4:
                    st.write(f"{s_icon} **{status.replace('_', ' ').title()}**")
                    new_st = st.selectbox(
                        "Update",
                        ["scheduled", "in_progress", "completed", "cancelled"],
                        key=f"res_st_{r['reservation_id']}",
                    )
                    if st.button("Update", key=f"res_upd_{r['reservation_id']}"):
                        uresp = requests.patch(
                            f"{API_BASE}/api/reservations/{r['reservation_id']}/status",
                            data={"status": new_st},
                            headers=_headers(),
                            timeout=10,
                        )
                        if uresp.status_code == 200:
                            _fetch_reservations.clear()
                            st.success("Updated!")
                            st.rerun()
                        else:
                            st.error(uresp.json().get("detail", uresp.text))

    # ── Auto-refresh ─────────────────────────────────────────
    st.caption("Reservations refresh automatically every 15 seconds.")
    if st.button("🔄 Refresh Now", key="res_refresh"):
        _fetch_reservations.clear()
        st.rerun()


# ═════════════════════════════════════════════════════════════
#  TAB 3 — My Appointments (AI Scheduler bookings)
# ═════════════════════════════════════════════════════════════
def _render_my_appointments(token: str):
    """Display appointments booked via the AI Schedule Assistant."""
    appointments = _fetch_appointments(token)

    if not appointments:
        st.info(
            "No appointments yet. Use the **📅 AI Scheduler** to book appointments."
        )
        return

    # ── Build a clean DataFrame for display ──────────────────
    rows = []
    for a in appointments:
        status = a.get("status", "scheduled")
        s_icon = _STATUS_ICON.get(status, "⚪")
        rows.append({
            "Patient Name": a.get("patient_name", "Unknown"),
            "Date":         a.get("appointment_date", ""),
            "Time":         a.get("appointment_time", ""),
            "Reason":       a.get("reason", "") or "General consultation",
            "Status":       f"{s_icon} {status.title()}",
        })

    df = pd.DataFrame(rows)

    # ── Summary metrics ──────────────────────────────────────
    with st.container(border=True):
        c1, c2, c3, c4 = st.columns(4)
        c1.metric("Total", len(rows))
        c2.metric("🟢 Scheduled", sum(1 for a in appointments if a.get("status") == "scheduled"))
        c3.metric("✅ Completed", sum(1 for a in appointments if a.get("status") == "completed"))
        c4.metric("🔴 Cancelled", sum(1 for a in appointments if a.get("status") == "cancelled"))

    # ── Appointments table ───────────────────────────────────
    with st.container(border=True):
        st.markdown("#### 🗓️ My Appointments")
        st.dataframe(df, use_container_width=True, hide_index=True, key="appts_table")

    # ── Refresh button ───────────────────────────────────────
    st.caption("Appointments refresh automatically every 15 seconds.")
    if st.button("🔄 Refresh Now", key="appts_refresh"):
        _fetch_appointments.clear()
        st.rerun()
