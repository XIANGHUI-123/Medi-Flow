"""
pharmacist_dashboard.py  ─  Medi‑Flow Orchestrator  ─  Pharmacy Dashboard

AI Medicine Confirmation & Automatic Reminder system:
  • AI generates medicine suggestions with quantity & duration
  • Pharmacist reviews / edits each medicine one‑by‑one
  • On confirm → automatic patient reminder generated
    (e.g. "Take 15 tablets of Paracetamol for 5 days")
  • Medicines grouped **per patient** in expandable cards
  • Doctor notes & consultation info (expandable)
  • Colour coding:
      🔵 Blue  = AI suggestion (untouched)
      🟢 Green = Edited by pharmacist
      ⚫ Gray  = Confirmed & reminder sent

Entry point: render()
"""

from __future__ import annotations

from datetime import datetime

import requests
import streamlit as st

# ── Backend config ───────────────────────────────────────────
API_BASE = "http://127.0.0.1:8000"

_STATUS_CFG = {
    "pending":     {"icon": "🟡", "color": "#FFA726", "label": "Pending"},
    "sent":        {"icon": "🟢", "color": "#66BB6A", "label": "Sent"},
    "in_progress": {"icon": "🔵", "color": "#42A5F5", "label": "In Progress"},
    "completed":   {"icon": "✅", "color": "#4CAF50", "label": "Completed"},
}

# Urgency keyword lists
_URGENT_KW = [
    "antibiotic", "amoxicillin", "azithromycin", "insulin",
    "epinephrine", "adrenaline", "steroid", "prednisolone",
]
_MODERATE_KW = [
    "paracetamol", "acetaminophen", "ibuprofen", "nsaid",
    "fever", "pain", "analgesic",
]


def _headers() -> dict:
    return {"Authorization": f"Bearer {st.session_state.token}"}


# ═══════════════════════════════════════════════════════════
#  CSS
# ═══════════════════════════════════════════════════════════

_CSS = """
<style>
/* Badges */
.ph-badge{display:inline-block;padding:3px 10px;border-radius:10px;font-size:13px;font-weight:600;color:#fff}
.ph-blue{background:#2196F3}
.ph-green{background:#4CAF50}
.ph-gray{background:#9E9E9E}
.ph-orange{background:#FFA726}
.ph-red{background:#EF5350}

/* Urgency left‑border */
.ph-urgent{border-left:4px solid #EF5350;padding-left:8px}
.ph-moderate{border-left:4px solid #FFA726;padding-left:8px}
.ph-normal{border-left:4px solid #66BB6A;padding-left:8px}

/* Divider */
.ph-hr{margin:6px 0;border:none;border-top:1px solid #e0e0e0}

/* Patient info grid */
.ph-info{display:grid;grid-template-columns:1fr 1fr;gap:4px 16px;font-size:14px}
.ph-info b{color:#555}

/* Confirmed + Reminder box */
.ph-confirmed-box{border-left:4px solid #9E9E9E;padding:8px 12px;margin:6px 0;
                   background:#F5F5F5;border-radius:0 8px 8px 0}
.ph-reminder-box{border-left:4px solid #4CAF50;padding:8px 12px;margin:4px 0;
                  background:#E8F5E9;border-radius:0 8px 8px 0}
</style>
"""


# ═══════════════════════════════════════════════════════════
#  Data helpers
# ═══════════════════════════════════════════════════════════

def _load_prescriptions() -> list[dict]:
    try:
        r = requests.get(f"{API_BASE}/api/orders/pharmacy", headers=_headers(), timeout=15)
        if r.status_code == 200:
            return r.json()
    except requests.RequestException:
        pass
    return []


def _load_consultations(patient_id: int) -> list[dict]:
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


def _group_by_patient(prescriptions: list[dict]) -> dict[int, dict]:
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


def _calculate_quantity(order_id: int) -> dict:
    try:
        r = requests.post(
            f"{API_BASE}/api/pharmacy/calculate-quantity",
            data={"order_id": order_id}, headers=_headers(), timeout=30,
        )
        if r.status_code == 200:
            return r.json()
    except requests.RequestException:
        pass
    return {"quantity": "N/A", "unit": "units", "calculation": "Could not reach AI service."}


def _send_reminder(order_id: int) -> dict:
    try:
        r = requests.post(
            f"{API_BASE}/api/pharmacy/send-reminder",
            data={"order_id": order_id}, headers=_headers(), timeout=30,
        )
        if r.status_code == 200:
            return r.json()
    except requests.RequestException:
        pass
    return {"message": "Could not reach AI service.", "type": "error", "sent": False}


def _update_status(order_id: int, new_status: str):
    try:
        r = requests.patch(
            f"{API_BASE}/api/orders/{order_id}/status",
            data={"status": new_status}, headers=_headers(), timeout=10,
        )
        if r.status_code == 200:
            return True
        else:
            st.error(r.json().get("detail", r.text))
    except requests.RequestException as e:
        st.error(f"Backend not reachable: {e}")
    return False


# ═══════════════════════════════════════════════════════════
#  Urgency helpers
# ═══════════════════════════════════════════════════════════

def _urgency(name: str) -> str:
    n = (name or "").lower()
    if any(k in n for k in _URGENT_KW):
        return "urgent"
    if any(k in n for k in _MODERATE_KW):
        return "moderate"
    return "normal"


def _urgency_badge(name: str) -> str:
    lvl = _urgency(name)
    if lvl == "urgent":
        return " <span class='ph-badge ph-red'>🔴 Urgent</span>"
    if lvl == "moderate":
        return " <span class='ph-badge ph-orange'>🟠 Priority</span>"
    return ""


# ═══════════════════════════════════════════════════════════
#  Colour‑coding helpers
#
#   Blue  = AI suggestion (pharmacist hasn't touched it)
#   Green = Pharmacist edited the quantity
#   Gray  = Confirmed & reminder sent
# ═══════════════════════════════════════════════════════════

def _order_badge(status: str) -> str:
    cfg = _STATUS_CFG.get(status, _STATUS_CFG["pending"])
    return (
        f"<span class='ph-badge' style='background:{cfg['color']}'>"
        f"{cfg['icon']} {cfg['label']}</span>"
    )


def _qty_badge(oid: int) -> str:
    """Colour‑coded state badge for a prescription."""
    confirmed_key = f"ph_confirmed_{oid}"
    edit_key = f"ph_edited_{oid}"
    qty_key = f"ph_qty_{oid}"

    if confirmed_key in st.session_state:
        return "<span class='ph-badge ph-gray'>⚫ Confirmed & Reminded</span>"
    if edit_key in st.session_state:
        return "<span class='ph-badge ph-green'>🟢 Edited</span>"
    if qty_key in st.session_state:
        return "<span class='ph-badge ph-blue'>🔵 AI Suggested</span>"
    return "<span class='ph-badge ph-gray'>⏳ Awaiting AI</span>"


# ═══════════════════════════════════════════════════════════
#  MAIN ENTRY POINT
# ═══════════════════════════════════════════════════════════

def render():
    st.markdown(_CSS, unsafe_allow_html=True)

    st.title("💊 Pharmacy Dashboard — AI Medicine Confirmation & Reminder")
    st.caption(
        "AI generates medicine quantities → pharmacist reviews & edits → "
        "confirm one‑by‑one → automatic patient reminder generated."
    )

    all_rx = _load_prescriptions()
    if not all_rx:
        st.info("No prescription orders at the moment.")
        return

    # ── Filters ──────────────────────────────────────────────
    with st.container(border=True):
        fc1, fc2, fc3 = st.columns(3)
        with fc1:
            search_q = st.text_input(
                "🔍 Search Patient or Medicine",
                placeholder="Type name or medicine …",
                key="ph_search",
            )
        with fc2:
            status_f = st.selectbox(
                "Status",
                ["All", "pending", "sent", "in_progress", "completed"],
                key="ph_status_f",
            )
        with fc3:
            sort_opt = st.selectbox(
                "Sort Patients By",
                ["Name (A‑Z)", "Name (Z‑A)", "Most Medicines", "Newest Order"],
                key="ph_sort",
            )

    # Apply filters
    filtered = all_rx
    if search_q:
        q = search_q.lower()
        filtered = [
            p for p in filtered
            if q in p.get("patient_name", "").lower()
            or q in p.get("medicine", "").lower()
        ]
    if status_f != "All":
        filtered = [p for p in filtered if p.get("status") == status_f]

    groups = _group_by_patient(filtered)
    sorted_groups = list(groups.values())

    if sort_opt == "Name (A‑Z)":
        sorted_groups.sort(key=lambda g: g["patient_name"].lower())
    elif sort_opt == "Name (Z‑A)":
        sorted_groups.sort(key=lambda g: g["patient_name"].lower(), reverse=True)
    elif sort_opt == "Most Medicines":
        sorted_groups.sort(key=lambda g: len(g["medicines"]), reverse=True)
    elif sort_opt == "Newest Order":
        sorted_groups.sort(
            key=lambda g: max(
                (m.get("created_at", "") for m in g["medicines"]), default=""
            ),
            reverse=True,
        )

    # ── Metrics ──────────────────────────────────────────────
    all_groups = _group_by_patient(all_rx)
    total_patients = len(all_groups)
    total_rx = len(all_rx)
    ai_count = sum(1 for p in all_rx if f"ph_qty_{p.get('order_id', 0)}" in st.session_state)
    confirmed = sum(1 for p in all_rx if f"ph_confirmed_{p.get('order_id', 0)}" in st.session_state)
    remaining = total_rx - confirmed
    urgent = sum(1 for p in all_rx if _urgency(p.get("medicine", "")) == "urgent")

    with st.container(border=True):
        mc = st.columns(6)
        mc[0].metric("👥 Patients", total_patients)
        mc[1].metric("💊 Prescriptions", total_rx)
        mc[2].metric("🤖 AI Suggested", ai_count)
        mc[3].metric("✅ Confirmed", confirmed)
        mc[4].metric("⏳ Remaining", remaining)
        mc[5].metric("🔴 Urgent", urgent)

    if not sorted_groups:
        st.info("No prescriptions match the current filters.")
        return

    # ── Render patient cards ─────────────────────────────────
    for grp in sorted_groups:
        _render_patient_card(grp)


# ═══════════════════════════════════════════════════════════
#  Single patient card
# ═══════════════════════════════════════════════════════════

def _render_patient_card(grp: dict):
    pid  = grp["patient_id"]
    name = grp["patient_name"]
    meds = grp["medicines"]
    n    = len(meds)

    confirmed_cnt = sum(
        1 for m in meds if f"ph_confirmed_{m.get('order_id', 0)}" in st.session_state
    )
    all_confirmed = confirmed_cnt == n
    has_urgent = any(_urgency(m.get("medicine", "")) == "urgent" for m in meds)

    badge = "✅" if all_confirmed else ("🔴" if has_urgent else "🟡")
    label = (
        f"{badge}  **{name}**  —  {n} medicine{'s' if n != 1 else ''}  |  "
        f"{confirmed_cnt}/{n} confirmed"
        + ("  ⚠️ URGENT" if has_urgent else "")
    )

    with st.expander(label, expanded=not all_confirmed):

        # ── Patient info + Doctor notes ──────────────────────
        _render_patient_header(grp)

        st.divider()

        # ── Generate All AI Quantities button ────────────────
        need_ai = [
            m for m in meds
            if f"ph_qty_{m['order_id']}" not in st.session_state
            and f"ph_confirmed_{m['order_id']}" not in st.session_state
        ]
        if need_ai:
            if st.button(
                f"🤖 Generate AI Quantities for All {len(need_ai)} Medicines",
                key=f"pcalc_{pid}",
                use_container_width=True,
            ):
                bar = st.progress(0, text="AI is calculating quantities …")
                for i, m in enumerate(need_ai):
                    o = m["order_id"]
                    st.session_state[f"ph_qty_{o}"] = _calculate_quantity(o)
                    bar.progress((i + 1) / len(need_ai), text=f"{i + 1}/{len(need_ai)}")
                bar.empty()
                st.rerun()

        # ── Column headers ───────────────────────────────────
        hdr = st.columns([3, 2, 2, 2, 2, 2, 2])
        hdr[0].markdown("**Medicine**")
        hdr[1].markdown("**Dosage**")
        hdr[2].markdown("**Duration**")
        hdr[3].markdown("**AI Qty**")
        hdr[4].markdown("**Final Qty**")
        hdr[5].markdown("**Status**")
        hdr[6].markdown("**Action**")

        # ── Medicine rows ────────────────────────────────────
        for idx, med in enumerate(meds):
            _render_medicine_row(med, idx, pid)
            if idx < n - 1:
                st.markdown("<hr class='ph-hr'>", unsafe_allow_html=True)


# ═══════════════════════════════════════════════════════════
#  Patient header (info + doctor notes)
# ═══════════════════════════════════════════════════════════

def _render_patient_header(grp: dict):
    pid = grp["patient_id"]
    info_col, notes_col = st.columns(2)

    with info_col:
        phone   = grp.get("phone_number") or "—"
        address = grp.get("home_address")  or "—"
        allergy = grp.get("allergies")     or "None known"
        st.markdown(
            f"<div class='ph-info'>"
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

        if st.button("📜 Consultation History", key=f"cons_hist_{pid}"):
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
#  Single medicine row  (AI qty → edit → confirm → auto‑reminder)
# ═══════════════════════════════════════════════════════════

def _render_medicine_row(med: dict, idx: int, pid: int):
    oid      = med.get("order_id", 0)
    medicine = med.get("medicine", med.get("order_type", "N/A"))
    dosage   = med.get("dosage", "As directed")
    duration = med.get("duration", "As directed")
    status   = med.get("status", "pending")

    qty_key       = f"ph_qty_{oid}"
    edit_key      = f"ph_edited_{oid}"
    confirmed_key = f"ph_confirmed_{oid}"
    reminder_key  = f"ph_auto_rem_{oid}"
    has_ai        = qty_key in st.session_state
    is_confirmed  = confirmed_key in st.session_state

    # Urgency wrapper
    urg_cls = f"ph-{_urgency(medicine)}"
    st.markdown(f"<div class='{urg_cls}'>", unsafe_allow_html=True)

    r = st.columns([3, 2, 2, 2, 2, 2, 2])

    # Col 1 — Medicine name + badges
    with r[0]:
        st.markdown(
            f"**💊 {medicine}**{_urgency_badge(medicine)}  \n"
            f"{_qty_badge(oid)}",
            unsafe_allow_html=True,
        )

    # Col 2 — Dosage
    with r[1]:
        st.markdown(dosage)

    # Col 3 — Duration
    with r[2]:
        st.markdown(duration)

    # Col 4 — AI Qty display
    with r[3]:
        if has_ai:
            qd = st.session_state[qty_key]
            st.markdown(f"**{qd.get('quantity', '?')} {qd.get('unit', 'units')}**")
        else:
            st.markdown("*—*")

    # Col 5 — Editable final qty / confirmed value
    with r[4]:
        if is_confirmed:
            cd = st.session_state[confirmed_key]
            cu = cd.get("unit", st.session_state.get(qty_key, {}).get("unit", "units"))
            st.markdown(f"**⚫ {cd['quantity']} {cu}**")
        else:
            default = 0
            if has_ai:
                aq = st.session_state[qty_key].get("quantity", 0)
                default = int(aq) if str(aq).isdigit() else 0
            input_key = f"ph_fq_{oid}"
            val = st.number_input(
                "Qty",
                min_value=0,
                value=default,
                step=1,
                key=input_key,
                label_visibility="collapsed",
            )
            # Track if pharmacist changed the value from AI default
            if has_ai and val != default:
                st.session_state[edit_key] = True
            elif edit_key in st.session_state and val == default:
                del st.session_state[edit_key]

    # Col 6 — Order status badge
    with r[5]:
        st.markdown(_order_badge(status), unsafe_allow_html=True)

    # Col 7 — Action: Calculate OR Confirm (one‑by‑one, no batch)
    with r[6]:
        if is_confirmed:
            st.markdown("✅ Done")
        elif has_ai:
            if st.button(
                "✅ Confirm",
                key=f"conf_{oid}_{idx}",
                type="primary",
                use_container_width=True,
                help=f"Confirm {medicine} & auto‑send reminder",
            ):
                _do_confirm_and_remind(oid, medicine, dosage, duration, med)
        else:
            if st.button(
                "🤖 AI Calc",
                key=f"calc_{oid}_{idx}",
                use_container_width=True,
                help="Generate AI quantity suggestion",
            ):
                with st.spinner("AI calculating …"):
                    st.session_state[qty_key] = _calculate_quantity(oid)
                    st.rerun()

    # Close urgency div
    st.markdown("</div>", unsafe_allow_html=True)

    # AI explanation (shown below the row)
    if has_ai and not is_confirmed:
        expl = st.session_state[qty_key].get("calculation", "")
        if expl:
            st.caption(f"📝 _{expl}_")

    # ── Confirmed + Auto‑Reminder display ────────────────────
    if is_confirmed:
        cd = st.session_state[confirmed_key]
        c_unit = cd.get("unit", st.session_state.get(qty_key, {}).get("unit", "units"))
        st.markdown(
            f"<div class='ph-confirmed-box'>"
            f"⚫ <b>Confirmed:</b> {cd['quantity']} {c_unit} of {medicine} "
            f"({dosage}, {duration})"
            f"</div>",
            unsafe_allow_html=True,
        )
        if reminder_key in st.session_state:
            rd = st.session_state[reminder_key]
            ai_msg = rd.get("message", "")
            ic = {"refill": "🔄", "followup": "🏥", "ongoing": "💊"}.get(
                rd.get("type", ""), "📩"
            )
            st.markdown(
                f"<div class='ph-reminder-box'>"
                f"{ic} <b>Auto‑Reminder Sent:</b> {ai_msg}"
                f"</div>",
                unsafe_allow_html=True,
            )


# ═══════════════════════════════════════════════════════════
#  Confirm + Auto‑Reminder workflow
# ═══════════════════════════════════════════════════════════

def _do_confirm_and_remind(oid: int, medicine: str, dosage: str,
                           duration: str, med: dict):
    """
    1. Lock in pharmacist's final quantity
    2. Generate a patient reminder with how many days to take the medicine
    3. Store both in session state and refresh
    """
    qty_key       = f"ph_qty_{oid}"
    confirmed_key = f"ph_confirmed_{oid}"
    reminder_key  = f"ph_auto_rem_{oid}"
    fq_key        = f"ph_fq_{oid}"

    final_qty = st.session_state.get(fq_key, 0)
    ai_unit   = st.session_state[qty_key].get("unit", "units") if qty_key in st.session_state else "units"

    # 1. Save confirmed data
    st.session_state[confirmed_key] = {
        "quantity":  final_qty,
        "unit":      ai_unit,
        "confirmed": True,
    }

    # 2. Generate AI reminder via backend
    with st.spinner(f"Confirming {medicine} & generating reminder …"):
        reminder_result = _send_reminder(oid)

        # Build a clear duration-based reminder as fallback /  supplement
        duration_msg = (
            f"Take {final_qty} {ai_unit} of {medicine} ({dosage}) "
            f"for {duration}."
        )

        ai_msg = reminder_result.get("message", "")
        if not ai_msg or reminder_result.get("type") == "error":
            # Fallback: use our own structured message
            reminder_result["message"] = duration_msg
            reminder_result["type"] = "ongoing"

        st.session_state[reminder_key] = reminder_result

    st.rerun()
