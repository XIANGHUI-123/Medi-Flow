"""
streamlit_app.py  ─  Medi‑Flow Orchestrator  ─  Streamlit Frontend

Pages:
  1. Login / Register
  2. Doctor Dashboard     – record voice, upload voice, paste transcript,
                            upload patient images, view orders
  3. Laboratory Dashboard – view & update lab test orders
  4. Pharmacy Dashboard   – view & update prescription orders

Run:
    streamlit run streamlit_app.py
"""

import io
import json
import requests
import streamlit as st
from audio_recorder_streamlit import audio_recorder
import consultation_page
import my_orders_page
import reservation_page
import ai_schedule_assistant
import pandemic_heatmap_page
import pharmacist_dashboard

# ── Backend URL (FastAPI) ────────────────────────────────────
API_BASE = "http://127.0.0.1:8000"


# ═════════════════════════════════════════════════════════════
#  SESSION STATE HELPERS
# ═════════════════════════════════════════════════════════════

def init_session():
    """Initialise session state defaults."""
    defaults = {
        "token": None,
        "user_id": None,
        "user_name": None,
        "user_role": None,
        "page": "login",
        "doctor_page": "home",
    }
    for k, v in defaults.items():
        if k not in st.session_state:
            st.session_state[k] = v


def api_headers() -> dict:
    """Return Authorization header dict."""
    return {"Authorization": f"Bearer {st.session_state.token}"}


def logout():
    """Clear session and return to login page."""
    for k in ("token", "user_id", "user_name", "user_role"):
        st.session_state[k] = None
    st.session_state.page = "login"


# ═════════════════════════════════════════════════════════════
#  PAGE: LOGIN / REGISTER
# ═════════════════════════════════════════════════════════════

def page_login():
    st.title("🏥 Medi‑Flow Orchestrator")
    st.subheader("Login")

    tab_login, tab_register = st.tabs(["Login", "Register"])

    # ── Login tab ────────────────────────────────────────────
    with tab_login:
        email = st.text_input("Email", key="login_email")
        password = st.text_input("Password", type="password", key="login_pwd")
        if st.button("Login", type="primary"):
            resp = requests.post(
                f"{API_BASE}/api/auth/login",
                data={"username": email, "password": password},
                timeout=15,
            )
            if resp.status_code == 200:
                body = resp.json()
                st.session_state.token     = body["access_token"]
                st.session_state.user_id   = body["user_id"]
                st.session_state.user_name = body["name"]
                st.session_state.user_role = body["role"]
                st.session_state.page      = "dashboard"
                st.rerun()
            else:
                st.error(f"Login failed: {resp.json().get('detail', resp.text)}")

    # ── Register tab ─────────────────────────────────────────
    with tab_register:
        name  = st.text_input("Full name", key="reg_name")
        email = st.text_input("Email", key="reg_email")
        pwd   = st.text_input("Password", type="password", key="reg_pwd")
        role  = st.selectbox("Role", ["doctor", "lab_staff", "pharmacy_staff"], key="reg_role")
        if st.button("Register"):
            resp = requests.post(
                f"{API_BASE}/api/auth/register",
                data={"name": name, "email": email, "password": pwd, "role": role},
                timeout=15,
            )
            if resp.status_code == 200:
                st.success("Registered! Please log in.")
            else:
                st.error(resp.json().get("detail", resp.text))


# ═════════════════════════════════════════════════════════════
#  PAGE: DOCTOR DASHBOARD (sidebar‑driven)
# ═════════════════════════════════════════════════════════════

def page_doctor_dashboard():
    # ── Sidebar navigation ───────────────────────────────────
    with st.sidebar:
        st.image("https://img.icons8.com/color/96/hospital.png", width=60)
        st.title("Medi‑Flow")
        st.caption(f"👨‍⚕️ Dr. {st.session_state.user_name}")
        st.divider()

        menu_items = {
            "home":         "🏠 Homepage",
            "consultation": "🩺 Consultation",
            "reservations": "📅 Reservations",
            "orders":       "📋 My Orders",
            "ai_schedule":  "📅 AI Scheduler",
            "heatmap":      "🌡️ Pandemic Heatmap",
        }

        for key, label in menu_items.items():
            if st.button(label, key=f"nav_{key}", use_container_width=True,
                         type="primary" if st.session_state.doctor_page == key else "secondary"):
                st.session_state.doctor_page = key
                st.rerun()

        st.divider()
        if st.button("🚪 Logout", key="doc_logout", use_container_width=True):
            logout()
            st.rerun()

    # ── Route to sub‑page ────────────────────────────────────
    page = st.session_state.doctor_page
    if page == "home":
        _doctor_home()
    elif page == "consultation":
        _doctor_consultation()
    elif page == "reservations":
        _doctor_reservations()
    elif page == "orders":
        _doctor_orders()
    elif page == "ai_schedule":
        ai_schedule_assistant.render()
    elif page == "heatmap":
        pandemic_heatmap_page.render()


# ─────────────────────────────────────────────────────────────
#  Sub‑page: Homepage (Doctor Profile)
# ─────────────────────────────────────────────────────────────
def _doctor_home():
    st.title("🏠 Welcome Back!")
    st.divider()

    col1, col2 = st.columns([1, 2])
    with col1:
        st.markdown(
            "<div style='text-align:center; padding:20px; background:#f0f2f6; "
            "border-radius:16px;'>"
            "<p style='font-size:64px; margin:0;'>👨‍⚕️</p>"
            f"<h3 style='margin:8px 0 4px;'>Dr. {st.session_state.user_name}</h3>"
            f"<p style='color:grey;'>User ID: {st.session_state.user_id}</p>"
            "<span style='background:#2196F3; color:white; padding:4px 12px; "
            "border-radius:12px; font-size:14px;'>Doctor</span>"
            "</div>",
            unsafe_allow_html=True,
        )

    with col2:
        st.subheader("Quick Actions")
        qa1, qa2, qa3 = st.columns(3)
        with qa1:
            if st.button("🩺 New Consultation", use_container_width=True):
                st.session_state.doctor_page = "consultation"
                st.rerun()
        with qa2:
            if st.button("🔍 Search Patient", use_container_width=True):
                st.session_state.doctor_page = "patients"
                st.rerun()
        with qa3:
            if st.button("📅 Book Operation", use_container_width=True):
                st.session_state.doctor_page = "reservations"
                st.rerun()

        st.divider()

        # Summary stats
        st.subheader("📊 Today's Summary")
        c1, c2, c3 = st.columns(3)
        try:
            orders_resp = requests.get(f"{API_BASE}/api/orders", headers=api_headers(), timeout=10)
            orders = orders_resp.json() if orders_resp.status_code == 200 else []
            res_resp = requests.get(f"{API_BASE}/api/reservations", headers=api_headers(), timeout=10)
            reservations = res_resp.json() if res_resp.status_code == 200 else []
        except requests.RequestException:
            orders, reservations = [], []

        with c1:
            st.metric("Total Orders", len(orders))
        with c2:
            pending = sum(1 for o in orders if o.get("status") in ("pending", "sent"))
            st.metric("Pending Orders", pending)
        with c3:
            active_res = sum(1 for r in reservations if r.get("status") == "scheduled")
            st.metric("Upcoming Operations", active_res)


# ─────────────────────────────────────────────────────────────
#  Sub‑page: Consultation (moved from old main dashboard)
# ─────────────────────────────────────────────────────────────
def _doctor_consultation():
    consultation_page.render()


# ─────────────────────────────────────────────────────────────
#  Sub‑page: Patient Search
# ─────────────────────────────────────────────────────────────
def _doctor_patient_search():
    st.title("🔍 Patient Search")

    search_query = st.text_input(
        "Search by patient name, IC number, or ID",
        placeholder="Type a name, IC number, or patient ID …",
        key="patient_search_q",
    )

    if st.button("🔎 Search", type="primary", key="btn_search_patient"):
        if not search_query.strip():
            st.warning("Enter a name, IC, or ID to search.")
        else:
            try:
                resp = requests.get(
                    f"{API_BASE}/api/patients/search",
                    params={"q": search_query.strip()},
                    headers=api_headers(),
                    timeout=10,
                )
                if resp.status_code == 200:
                    results = resp.json()
                    if results:
                        st.success(f"Found {len(results)} patient(s)")
                        for p in results:
                            with st.container(border=True):
                                c1, c2, c3 = st.columns([2, 2, 2])
                                with c1:
                                    st.markdown(f"### {p['name']}")
                                    st.caption(f"Patient ID: {p['patient_id']}")
                                    st.write(f"**IC:** {p.get('ic_number') or 'N/A'}")
                                with c2:
                                    st.write(f"**Age:** {p.get('age') or 'N/A'}")
                                    st.write(f"**DOB:** {p.get('date_of_birth') or 'N/A'}")
                                    st.write(f"**📞** {p.get('phone_number') or 'N/A'}")
                                with c3:
                                    if p.get("allergies"):
                                        st.warning(f"⚠️ Allergies: {p['allergies']}")
                                    st.write(f"**History:** {p.get('medical_history') or '_None_'}")
                                if st.button(f"📄 View Full Record", key=f"view_p_{p['patient_id']}"):
                                    _show_patient_detail(p["patient_id"])
                    else:
                        st.info("No patients matched your search.")
                else:
                    st.error("Search failed.")
            except requests.RequestException:
                st.warning("Could not reach backend.")

    # Also show a quick list of all patients
    with st.expander("📋 Browse All Patients"):
        patients = _fetch_patients()
        if patients:
            for p in patients:
                st.write(f"**{p['name']}** (ID {p['patient_id']}) — IC: {p.get('ic_number') or 'N/A'} — Age: {p.get('age', 'N/A')}")
        else:
            st.info("No patients in the system.")


def _show_patient_detail(patient_id: int):
    """Display a patient's full record with order history."""
    try:
        resp = requests.get(
            f"{API_BASE}/api/patients/{patient_id}",
            headers=api_headers(),
            timeout=10,
        )
        if resp.status_code == 200:
            p = resp.json()
            st.info(f"**{p['name']}** — Age: {p.get('age', 'N/A')}  |  IC: {p.get('ic_number') or 'N/A'}")
            c1, c2 = st.columns(2)
            with c1:
                st.write(f"**DOB:** {p.get('date_of_birth') or 'N/A'}")
                st.write(f"**Phone:** {p.get('phone_number') or 'N/A'}")
                st.write(f"**Address:** {p.get('home_address') or 'N/A'}")
            with c2:
                st.write(f"**Allergies:** {p.get('allergies') or 'None'}")
                st.write(f"**Medical History:** {p.get('medical_history') or '_None_'}")
                st.write(f"**Registered:** {p.get('created_at', 'N/A')}")
            orders = p.get("orders", [])
            if orders:
                st.write(f"**Order History ({len(orders)}):**")
                for o in orders:
                    icon = "🔬" if o["department"] == "laboratory" else "💊"
                    st.write(
                        f"  {icon} {o['order_type']} — {o['status']} "
                        f"({o.get('created_at', '')})"
                    )
            else:
                st.write("_No orders yet._")
        else:
            st.error("Could not load patient details.")
    except requests.RequestException:
        st.warning("Backend not reachable.")


# ─────────────────────────────────────────────────────────────
#  Sub‑page: Reservations (Operation Scheduling)
# ─────────────────────────────────────────────────────────────
def _doctor_reservations():
    reservation_page.render()


# ─────────────────────────────────────────────────────────────
#  Sub‑page: My Orders
# ─────────────────────────────────────────────────────────────
def _doctor_orders():
    my_orders_page.render()


# ── Doctor helpers ───────────────────────────────────────────

def _fetch_patients() -> list:
    try:
        resp = requests.get(f"{API_BASE}/api/patients", headers=api_headers(), timeout=10)
        if resp.status_code == 200:
            return resp.json()
    except requests.RequestException:
        st.warning("Could not fetch patients – is the backend running?")
    return []


# ═════════════════════════════════════════════════════════════
#  PAGE: LABORATORY DASHBOARD
# ═════════════════════════════════════════════════════════════

def page_lab_dashboard():
    with st.sidebar:
        st.image("https://img.icons8.com/color/96/hospital.png", width=60)
        st.title("Medi‑Flow")
        st.caption(f"🔬 {st.session_state.user_name}")
        st.divider()
        st.markdown("**🔬 Lab Orders**")
        st.divider()
        if st.button("🚪 Logout", key="lab_logout", use_container_width=True):
            logout()
            st.rerun()

    st.title("🔬 Laboratory Dashboard")
    st.subheader("Pending Lab Test Orders")

    try:
        resp = requests.get(f"{API_BASE}/api/orders/lab", headers=api_headers(), timeout=10)
        if resp.status_code == 200:
            orders = resp.json()
            if not orders:
                st.info("No lab orders at the moment.")
                return

            for o in orders:
                status_icon = {
                    "pending": "🟡", "sent": "🟢",
                    "in_progress": "🔵", "completed": "✅",
                }.get(o["status"], "⚪")

                with st.container():
                    col1, col2, col3 = st.columns([3, 2, 2])
                    with col1:
                        st.write(f"**Order #{o['order_id']}** — {o['order_type']}")
                        st.write(f"Patient: {o['patient_name']} (ID {o['patient_id']})")
                        if o.get("test_name"):
                            st.write(f"Test: {o['test_name']}  |  Urgency: {o.get('urgency', 'routine')}")
                    with col2:
                        st.write(f"{status_icon} **{o['status'].upper()}**")
                        st.write(f"Created: {o.get('created_at', 'N/A')}")
                    with col3:
                        new_status = st.selectbox(
                            "Update status",
                            ["sent", "in_progress", "completed"],
                            key=f"lab_status_{o['order_id']}",
                        )
                        if st.button("Update", key=f"lab_update_{o['order_id']}"):
                            _update_status(o["order_id"], new_status)

                    st.divider()
        else:
            st.error("Could not fetch lab orders.")
    except requests.RequestException:
        st.warning("Backend not reachable.")


# ═════════════════════════════════════════════════════════════
#  PAGE: PHARMACY DASHBOARD
# ═════════════════════════════════════════════════════════════

def page_pharmacy_dashboard():
    with st.sidebar:
        st.image("https://img.icons8.com/color/96/hospital.png", width=60)
        st.title("Medi‑Flow")
        st.caption(f"💊 {st.session_state.user_name}")
        st.divider()
        st.markdown("**💊 Prescriptions**")
        st.divider()
        if st.button("🚪 Logout", key="ph_logout", use_container_width=True):
            logout()
            st.rerun()

    pharmacist_dashboard.render()


# ── Shared helpers ───────────────────────────────────────────

def _update_status(order_id: int, new_status: str):
    """Call the API to update an order's status."""
    resp = requests.patch(
        f"{API_BASE}/api/orders/{order_id}/status",
        data={"status": new_status},
        headers=api_headers(),
        timeout=10,
    )
    if resp.status_code == 200:
        st.success(f"Order #{order_id} updated to **{new_status}**")
        st.rerun()
    else:
        st.error(resp.json().get("detail", resp.text))


# ═════════════════════════════════════════════════════════════
#  MAIN ROUTING
# ═════════════════════════════════════════════════════════════

def main():
    st.set_page_config(
        page_title="Medi‑Flow Orchestrator",
        page_icon="🏥",
        layout="wide",
    )
    init_session()

    # ── Not authenticated → show login ───────────────────────
    if st.session_state.token is None:
        page_login()
        return

    # ── Route by role ────────────────────────────────────────
    role = st.session_state.user_role
    if role == "doctor":
        page_doctor_dashboard()
    elif role == "lab_staff":
        page_lab_dashboard()
    elif role == "pharmacy_staff":
        page_pharmacy_dashboard()
    else:
        st.error("Unknown role. Please log in again.")
        logout()


if __name__ == "__main__":
    main()
