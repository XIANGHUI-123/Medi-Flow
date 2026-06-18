"""
my_orders_page.py  ─  Medi‑Flow Orchestrator  ─  My Orders Page

Displays all doctor orders in a clean, categorized layout with:
  • Filters (patient name, department, status)
  • Combined orders table
  • Separate Laboratory / Pharmacy sections
  • Colour-coded status indicators
  • Auto-refresh support

Entry point: render()
"""

import pandas as pd
import requests
import streamlit as st

# ── Backend ──────────────────────────────────────────────────
API_BASE = "http://127.0.0.1:8000"


def _headers() -> dict:
    return {"Authorization": f"Bearer {st.session_state.token}"}


# ── Status helpers ───────────────────────────────────────────
_STATUS_ICON = {
    "pending":     "🟡",
    "sent":        "🟢",
    "in_progress": "🔵",
    "completed":   "✅",
}

_STATUS_COLOURS = {
    "pending":     "#FFA500",
    "sent":        "#28A745",
    "in_progress": "#007BFF",
    "completed":   "#6C757D",
}


def _badge(status: str) -> str:
    """Return an HTML badge for a given status."""
    colour = _STATUS_COLOURS.get(status, "#999")
    icon = _STATUS_ICON.get(status, "⚪")
    label = status.replace("_", " ").title()
    return (
        f'{icon} <span style="background:{colour};color:#fff;padding:2px 8px;'
        f'border-radius:10px;font-size:0.85em;">{label}</span>'
    )


# ── Data fetching ────────────────────────────────────────────
@st.cache_data(ttl=15, show_spinner=False)
def _fetch_orders(_token: str):
    """Fetch orders from backend; cached for 15 s for auto-refresh."""
    try:
        resp = requests.get(
            f"{API_BASE}/api/orders",
            headers={"Authorization": f"Bearer {_token}"},
            timeout=10,
        )
        if resp.status_code == 200:
            return resp.json()
    except requests.RequestException:
        pass
    return []


# ── Render helpers ───────────────────────────────────────────
def _render_table(orders: list, key_suffix: str = ""):
    """Render a dataframe table from a list of order dicts."""
    if not orders:
        st.info("No orders found.")
        return

    rows = []
    for o in orders:
        icon = "🔬" if o.get("department") == "laboratory" else "💊"
        status = o.get("status", "pending")
        rows.append({
            "Order ID":   o.get("order_id"),
            "Patient":    o.get("patient_name", "Unknown"),
            "Department": f"{icon} {(o.get('department') or '').replace('_', ' ').title()}",
            "Order Type": o.get("order_type", ""),
            "Details":    o.get("details", ""),
            "Status":     f"{_STATUS_ICON.get(status, '⚪')} {status.replace('_', ' ').title()}",
            "Created":    (o.get("created_at") or "")[:16].replace("T", "  "),
        })

    df = pd.DataFrame(rows)
    st.dataframe(
        df,
        use_container_width=True,
        hide_index=True,
        key=f"orders_table_{key_suffix}",
    )


def _render_cards(orders: list):
    """Render order cards (used inside categorised sections)."""
    if not orders:
        st.info("No orders in this category.")
        return

    for o in orders:
        status = o.get("status", "pending")
        with st.container(border=True):
            c1, c2, c3, c4 = st.columns([1, 2.5, 3, 2])
            with c1:
                st.markdown(f"**#{o.get('order_id')}**")
            with c2:
                st.markdown(f"**{o.get('patient_name', 'Unknown')}**")
                st.caption(f"Patient ID: {o.get('patient_id')}")
            with c3:
                st.markdown(f"**{o.get('order_type', '')}**")
                st.caption(o.get("details") or "—")
            with c4:
                st.markdown(_badge(status), unsafe_allow_html=True)
                created = (o.get("created_at") or "")[:16].replace("T", "  ")
                st.caption(f"🕐 {created}")


# ═════════════════════════════════════════════════════════════
#  Main entry point
# ═════════════════════════════════════════════════════════════
def render():
    # ── Section 1: Page Title ────────────────────────────────
    st.title("📋 My Orders")

    # ── Fetch data ───────────────────────────────────────────
    token = st.session_state.get("token", "")
    all_orders = _fetch_orders(token)

    if not all_orders:
        st.info("No orders yet. Submit a consultation to generate orders.")
        return

    # ── Section 2: Filters ───────────────────────────────────
    with st.container(border=True):
        st.markdown("#### 🔍 Filters")
        f1, f2, f3 = st.columns(3)

        with f1:
            search_name = st.text_input(
                "Patient name",
                placeholder="e.g. Tan Wei Ming",
                key="ord_filter_name",
            )
        with f2:
            dept_filter = st.selectbox(
                "Department",
                options=["All", "Laboratory", "Pharmacy"],
                key="ord_filter_dept",
            )
        with f3:
            status_filter = st.selectbox(
                "Status",
                options=["All", "Pending", "Sent", "In Progress", "Completed"],
                key="ord_filter_status",
            )

    # ── Apply filters ────────────────────────────────────────
    filtered = all_orders

    if search_name and search_name.strip():
        q = search_name.strip().lower()
        filtered = [o for o in filtered if q in (o.get("patient_name") or "").lower()]

    if dept_filter != "All":
        dept_val = dept_filter.lower()  # "laboratory" or "pharmacy"
        filtered = [o for o in filtered if o.get("department") == dept_val]

    _STATUS_MAP = {
        "Pending": "pending",
        "Sent": "sent",
        "In Progress": "in_progress",
        "Completed": "completed",
    }
    if status_filter != "All":
        s_val = _STATUS_MAP.get(status_filter, status_filter.lower())
        filtered = [o for o in filtered if o.get("status") == s_val]

    # ── Summary metrics ──────────────────────────────────────
    with st.container(border=True):
        m1, m2, m3, m4 = st.columns(4)
        m1.metric("Total Orders", len(filtered))
        m2.metric("🟡 Pending",   sum(1 for o in filtered if o.get("status") == "pending"))
        m3.metric("🟢 Sent",      sum(1 for o in filtered if o.get("status") == "sent"))
        m4.metric("✅ Completed",  sum(1 for o in filtered if o.get("status") == "completed"))

    # ── Section 3: All Orders Table ──────────────────────────
    with st.container(border=True):
        st.markdown("#### 📊 All Orders")
        _render_table(filtered, key_suffix="all")

    # ── Section 4: Categorised Sections ──────────────────────
    lab_orders  = [o for o in filtered if o.get("department") == "laboratory"]
    pharm_orders = [o for o in filtered if o.get("department") == "pharmacy"]

    col_lab, col_pharm = st.columns(2)

    with col_lab:
        with st.container(border=True):
            st.markdown("#### 🔬 Laboratory Orders")
            st.caption(f"{len(lab_orders)} order(s)")
            _render_cards(lab_orders)

    with col_pharm:
        with st.container(border=True):
            st.markdown("#### 💊 Pharmacy Orders")
            st.caption(f"{len(pharm_orders)} order(s)")
            _render_cards(pharm_orders)

    # ── Section 6: Auto-refresh ──────────────────────────────
    st.caption("Orders refresh automatically every 15 seconds.")
    if st.button("🔄 Refresh Now", key="ord_refresh"):
        _fetch_orders.clear()
        st.rerun()
