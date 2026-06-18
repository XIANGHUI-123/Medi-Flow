"""
ai_reminder_page.py  ─  Medi‑Flow Orchestrator  ─  AI Patient Reminder System

Unified view for pharmacists to:
  • Review all patients with pending prescriptions
  • Generate AI reminder messages per medicine
  • Edit reminder text before sending
  • Send reminders one‑by‑one with full control
  • View doctor notes, medicine info, and status

Colour coding:
  🔵 Blue  = AI‑suggested message (auto‑generated, untouched)
  🟢 Green = Pharmacist‑edited message
  ⚫ Gray  = Sent (delivered)

Entry point: render()
"""

from __future__ import annotations

from datetime import datetime

import requests
import streamlit as st

# ── Backend ──────────────────────────────────────────────────
API_BASE = "http://127.0.0.1:8000"


def _headers() -> dict:
    return {"Authorization": f"Bearer {st.session_state.token}"}


# ═══════════════════════════════════════════════════════════
#  CSS
# ═══════════════════════════════════════════════════════════

_CSS = """
<style>
/* Badges */
.rm-badge{display:inline-block;padding:3px 10px;border-radius:10px;font-size:13px;font-weight:600;color:#fff}
.rm-blue{background:#2196F3}
.rm-green{background:#4CAF50}
.rm-gray{background:#9E9E9E}
.rm-orange{background:#FFA726}
.rm-red{background:#EF5350}

/* Status pills */
.rm-pill{display:inline-block;padding:2px 8px;border-radius:8px;font-size:12px;font-weight:500;color:#fff}

/* Dividers */
.rm-hr{margin:8px 0;border:none;border-top:1px solid #e0e0e0}

/* Patient info grid */
.rm-info{display:grid;grid-template-columns:1fr 1fr;gap:4px 16px;font-size:14px}
.rm-info b{color:#555}

/* Medicine card */
.rm-med-card{border:1px solid #e0e0e0;border-radius:10px;padding:14px;margin:8px 0;
             background:#fafafa;transition:border-color .2s}
.rm-med-card:hover{border-color:#90CAF9}

/* Sent success */
.rm-sent{border-left:4px solid #4CAF50;padding-left:10px;margin:4px 0;background:#E8F5E9;
         border-radius:0 8px 8px 0;padding:8px 12px}
</style>
"""

# ── Order status config ──────────────────────────────────────
_STATUS_CFG = {
    "pending":     {"icon": "🟡", "color": "#FFA726", "label": "Pending"},
    "sent":        {"icon": "🟢", "color": "#66BB6A", "label": "Sent"},
    "in_progress": {"icon": "🔵", "color": "#42A5F5", "label": "In Progress"},
    "completed":   {"icon": "✅", "color": "#4CAF50", "label": "Completed"},
}


# ═══════════════════════════════════════════════════════════
#  Data helpers
# ═══════════════════════════════════════════════════════════

def _load_prescriptions() -> list[dict]:
    """Fetch pharmacy orders from backend (enriched with patient info & doctor notes)."""
    try:
        r = requests.get(f"{API_BASE}/api/orders/pharmacy", headers=_headers(), timeout=15)
        if r.status_code == 200:
            return r.json()
    except requests.RequestException:
        pass
    return []


def _load_consultations(patient_id: int) -> list[dict]:
    """Fetch last 5 consultations for a patient."""
    try:
        r = requests.get(
            f"{API_BASE}/api/patients/{patient_id}/consultations",
            headers=_headers(), timeout=10,
        )
        if r.status_code == 200:
            return r.json()
    except requests.RequestException:
        pass
    return []


def _generate_ai_reminder(order_id: int) -> dict:
    """Call backend AI to generate a reminder message for a prescription."""
    try:
        r = requests.post(
            f"{API_BASE}/api/pharmacy/send-reminder",
            data={"order_id": order_id},
            headers=_headers(),
            timeout=30,
        )
        if r.status_code == 200:
            return r.json()
    except requests.RequestException:
        pass
    return {
        "message": "Could not generate AI reminder. Please write one manually.",
        "type": "general",
        "sent": False,
    }


def _group_by_patient(prescriptions: list[dict]) -> dict[int, dict]:
    """Group prescriptions by patient_id, attaching patient metadata."""
    groups: dict[int, dict] = {}
    for p in prescriptions:
        pid = p.get("patient_id", 0)
        if pid not in groups:
            groups[pid] = {
                "patient_id":        pid,
                "patient_name":      p.get("patient_name", "Unknown"),
                "phone_number":      p.get("phone_number", ""),
                "home_address":      p.get("home_address", ""),
                "allergies":         p.get("allergies", ""),
                "medical_history":   p.get("medical_history", ""),
                "doctor_notes":      p.get("doctor_notes", ""),
                "doctor_name":       p.get("doctor_name", ""),
                "consultation_date": p.get("consultation_date", ""),
                "medicines":         [],
            }
        groups[pid]["medicines"].append(p)
    return groups


# ═══════════════════════════════════════════════════════════
#  Badge helpers
# ═══════════════════════════════════════════════════════════

def _order_status_badge(status: str) -> str:
    cfg = _STATUS_CFG.get(status, _STATUS_CFG["pending"])
    return (
        f"<span class='rm-pill' style='background:{cfg['color']}'>"
        f"{cfg['icon']} {cfg['label']}</span>"
    )


def _reminder_state_badge(oid: int) -> str:
    """
    Return a colour‑coded badge for the reminder state of a medicine.
      Blue  = AI message generated (untouched)
      Green = Pharmacist edited the message
      Gray  = Already sent
    """
    sent_key = f"rm_sent_{oid}"
    edited_key = f"rm_edited_{oid}"
    ai_key = f"rm_ai_{oid}"

    if sent_key in st.session_state:
        return "<span class='rm-badge rm-gray'>⚫ Sent</span>"
    if edited_key in st.session_state:
        return "<span class='rm-badge rm-green'>🟢 Edited</span>"
    if ai_key in st.session_state:
        return "<span class='rm-badge rm-blue'>🔵 AI Suggested</span>"
    return "<span class='rm-badge rm-gray'>⏳ Awaiting</span>"


# ═══════════════════════════════════════════════════════════
#  MAIN ENTRY POINT
# ═══════════════════════════════════════════════════════════

def render():
    st.markdown(_CSS, unsafe_allow_html=True)

    st.title("📩 AI Patient Reminder System")
    st.caption(
        "Generate, review, and send personalised AI reminders to patients — "
        "one medicine at a time, with full pharmacist control."
    )

    all_rx = _load_prescriptions()
    if not all_rx:
        st.info("No prescription orders at the moment.")
        return

    # ── Filter to non‑completed (needing reminders) ─────────
    reminder_rx = [p for p in all_rx if p.get("status") != "completed"]

    # ── Search & filter bar ──────────────────────────────────
    with st.container(border=True):
        fc1, fc2, fc3 = st.columns(3)
        with fc1:
            search_q = st.text_input(
                "🔍 Search patient or medicine",
                placeholder="Type name or medicine …",
                key="rm_search",
            )
        with fc2:
            status_f = st.selectbox(
                "Filter by status",
                ["All Pending", "pending", "sent", "in_progress"],
                key="rm_status_f",
            )
        with fc3:
            sort_opt = st.selectbox(
                "Sort by",
                ["Patient Name (A‑Z)", "Patient Name (Z‑A)", "Most Medicines", "Newest"],
                key="rm_sort",
            )

    # Apply search
    filtered = reminder_rx
    if search_q:
        q = search_q.lower()
        filtered = [
            p for p in filtered
            if q in p.get("patient_name", "").lower()
            or q in p.get("medicine", "").lower()
        ]
    # Apply status filter
    if status_f != "All Pending":
        filtered = [p for p in filtered if p.get("status") == status_f]

    groups = _group_by_patient(filtered)
    sorted_groups = list(groups.values())

    # Apply sort
    if sort_opt == "Patient Name (A‑Z)":
        sorted_groups.sort(key=lambda g: g["patient_name"].lower())
    elif sort_opt == "Patient Name (Z‑A)":
        sorted_groups.sort(key=lambda g: g["patient_name"].lower(), reverse=True)
    elif sort_opt == "Most Medicines":
        sorted_groups.sort(key=lambda g: len(g["medicines"]), reverse=True)
    elif sort_opt == "Newest":
        sorted_groups.sort(
            key=lambda g: max(
                (m.get("created_at", "") for m in g["medicines"]), default=""
            ),
            reverse=True,
        )

    # ── Metrics bar ──────────────────────────────────────────
    all_groups = _group_by_patient(reminder_rx)
    total_patients = len(all_groups)
    total_rx = len(reminder_rx)
    ai_generated = sum(
        1 for p in reminder_rx if f"rm_ai_{p.get('order_id', 0)}" in st.session_state
    )
    sent_count = sum(
        1 for p in reminder_rx if f"rm_sent_{p.get('order_id', 0)}" in st.session_state
    )

    with st.container(border=True):
        mc = st.columns(5)
        mc[0].metric("👥 Patients", total_patients)
        mc[1].metric("💊 Prescriptions", total_rx)
        mc[2].metric("🤖 AI Generated", ai_generated)
        mc[3].metric("📩 Sent", sent_count)
        mc[4].metric("⏳ Remaining", total_rx - sent_count)

    if not sorted_groups:
        st.info("No prescriptions match the current filters.")
        return

    # ── Render patient cards ─────────────────────────────────
    for grp in sorted_groups:
        _render_patient_card(grp)


# ═══════════════════════════════════════════════════════════
#  Patient card
# ═══════════════════════════════════════════════════════════

def _render_patient_card(grp: dict):
    pid  = grp["patient_id"]
    name = grp["patient_name"]
    meds = grp["medicines"]
    n    = len(meds)

    sent_for_patient = sum(
        1 for m in meds if f"rm_sent_{m.get('order_id', 0)}" in st.session_state
    )
    all_sent = sent_for_patient == n

    badge_icon = "✅" if all_sent else f"📩 {sent_for_patient}/{n}"
    label = f"**{name}**  —  {n} medicine{'s' if n != 1 else ''}  |  {badge_icon} reminders sent"

    with st.expander(label, expanded=not all_sent):

        # ── Patient info + Doctor notes ──────────────────────
        _render_patient_header(grp)

        st.divider()

        # ── Generate All AI Messages button ──────────────────
        need_ai = [
            m for m in meds
            if f"rm_ai_{m['order_id']}" not in st.session_state
            and f"rm_sent_{m['order_id']}" not in st.session_state
        ]
        if need_ai:
            if st.button(
                f"🤖 Generate All AI Reminders ({len(need_ai)} remaining)",
                key=f"rm_genall_{pid}",
                use_container_width=True,
            ):
                bar = st.progress(0, text="Generating AI reminders …")
                for i, m in enumerate(need_ai):
                    oid = m["order_id"]
                    result = _generate_ai_reminder(oid)
                    st.session_state[f"rm_ai_{oid}"] = result.get("message", "")
                    st.session_state[f"rm_type_{oid}"] = result.get("type", "general")
                    bar.progress((i + 1) / len(need_ai), text=f"{i + 1}/{len(need_ai)}")
                bar.empty()
                st.rerun()

        # ── Medicine rows ────────────────────────────────────
        for idx, med in enumerate(meds):
            _render_medicine_reminder(med, idx, pid)
            if idx < n - 1:
                st.markdown("<hr class='rm-hr'>", unsafe_allow_html=True)


# ═══════════════════════════════════════════════════════════
#  Patient header
# ═══════════════════════════════════════════════════════════

def _render_patient_header(grp: dict):
    pid = grp["patient_id"]
    info_col, notes_col = st.columns(2)

    with info_col:
        phone   = grp.get("phone_number") or "—"
        address = grp.get("home_address")  or "—"
        allergy = grp.get("allergies")     or "None known"
        st.markdown(
            f"<div class='rm-info'>"
            f"<div><b>📞 Phone:</b> {phone}</div>"
            f"<div><b>🏠 Address:</b> {address}</div>"
            f"<div><b>⚠️ Allergies:</b> {allergy}</div>"
            f"<div><b>🆔 Patient ID:</b> {pid}</div>"
            f"</div>",
            unsafe_allow_html=True,
        )

    with notes_col:
        doc_notes = grp.get("doctor_notes") or ""
        doc_name  = grp.get("doctor_name")  or "—"
        cons_date = grp.get("consultation_date") or ""
        if cons_date:
            try:
                cons_date = datetime.fromisoformat(cons_date).strftime(
                    "%d %b %Y, %I:%M %p"
                )
            except (ValueError, TypeError):
                pass

        if doc_notes:
            st.markdown(f"**🩺 Dr. {doc_name}** — _{cons_date}_")
            st.caption(doc_notes[:300] + ("…" if len(doc_notes) > 300 else ""))
            if len(doc_notes) > 300:
                with st.popover("📋 Full Doctor Notes"):
                    st.markdown(doc_notes)
        else:
            st.caption("No consultation notes available.")

        if st.button("📜 Consultation History", key=f"rm_cons_{pid}"):
            consults = _load_consultations(pid)
            if consults:
                for c in consults:
                    c_date = c.get("created_at", "")
                    if c_date:
                        try:
                            c_date = datetime.fromisoformat(c_date).strftime("%d %b %Y")
                        except (ValueError, TypeError):
                            pass
                    st.markdown(
                        f"**Dr. {c.get('doctor_name', '?')}** — {c_date}  \n"
                        f"_{c.get('text', '')[:200]}_"
                    )
            else:
                st.info("No consultation records found.")


# ═══════════════════════════════════════════════════════════
#  Single medicine reminder row
# ═══════════════════════════════════════════════════════════

def _render_medicine_reminder(med: dict, idx: int, pid: int):
    oid      = med.get("order_id", 0)
    medicine = med.get("medicine", med.get("order_type", "N/A"))
    dosage   = med.get("dosage", "As directed")
    duration = med.get("duration", "As directed")
    status   = med.get("status", "pending")

    ai_key     = f"rm_ai_{oid}"
    edited_key = f"rm_edited_{oid}"
    sent_key   = f"rm_sent_{oid}"
    has_ai     = ai_key in st.session_state
    is_sent    = sent_key in st.session_state

    st.markdown("<div class='rm-med-card'>", unsafe_allow_html=True)

    # ── Medicine info row ────────────────────────────────────
    info_cols = st.columns([3, 2, 2, 2, 2])

    with info_cols[0]:
        st.markdown(f"**💊 {medicine}**")
    with info_cols[1]:
        st.markdown(f"📋 {dosage}")
    with info_cols[2]:
        st.markdown(f"⏱️ {duration}")
    with info_cols[3]:
        st.markdown(_order_status_badge(status), unsafe_allow_html=True)
    with info_cols[4]:
        st.markdown(_reminder_state_badge(oid), unsafe_allow_html=True)

    # ── AI Reminder message section ──────────────────────────
    if is_sent:
        # Already sent — show the sent message
        sent_msg = st.session_state[sent_key]
        st.markdown(
            f"<div class='rm-sent'>"
            f"✅ <b>Reminder sent:</b> {sent_msg}"
            f"</div>",
            unsafe_allow_html=True,
        )
    elif has_ai:
        # AI message available — show editable text area + send button
        ai_msg = st.session_state[ai_key]
        msg_col, btn_col = st.columns([5, 1])

        with msg_col:
            edited_msg = st.text_area(
                f"Reminder for {medicine}",
                value=ai_msg,
                height=80,
                key=f"rm_msg_{oid}",
                label_visibility="collapsed",
                placeholder="Edit the AI-generated reminder …",
            )
            # Track if pharmacist edited the message
            if edited_msg != ai_msg:
                st.session_state[edited_key] = True
            elif edited_key in st.session_state and edited_msg == ai_msg:
                del st.session_state[edited_key]

        with btn_col:
            st.markdown("")  # vertical spacing
            if st.button(
                "📩 Send",
                key=f"rm_send_{oid}_{idx}",
                type="primary",
                use_container_width=True,
                help=f"Send reminder for {medicine}",
            ):
                final_msg = st.session_state.get(f"rm_msg_{oid}", ai_msg)
                st.session_state[sent_key] = final_msg
                st.rerun()

    else:
        # No AI message yet — show generate button
        gen_col, spacer = st.columns([2, 4])
        with gen_col:
            if st.button(
                "🤖 Generate AI Reminder",
                key=f"rm_gen_{oid}_{idx}",
                use_container_width=True,
            ):
                with st.spinner("AI is composing a reminder …"):
                    result = _generate_ai_reminder(oid)
                    st.session_state[ai_key] = result.get("message", "")
                    st.session_state[f"rm_type_{oid}"] = result.get("type", "general")
                    st.rerun()

    st.markdown("</div>", unsafe_allow_html=True)
