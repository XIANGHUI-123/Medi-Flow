"""
consultation_page.py  ─  Medi‑Flow Orchestrator  ─  Consultation Page

Clean, section-based consultation workflow matching the Orders page design.

Sections:
  1. Patient Search
  2. New Patient Registration (expandable)
  3. Patient Profile Card
  4. Consultation Input (tabs: Voice Record, Audio Upload, Transcript, Image)
  5. AI Analysis trigger
  6. AI Results display
  7. Order Confirmation (checkboxes)
  8. Order Routing

Called from streamlit_app.py → _doctor_consultation()
"""

import io
import re
import json
import requests
import streamlit as st
from audio_recorder_streamlit import audio_recorder

# ── Backend URL ──────────────────────────────────────────────
API_BASE = "http://127.0.0.1:8000"


def _headers() -> dict:
    return {"Authorization": f"Bearer {st.session_state.token}"}


# ═════════════════════════════════════════════════════════════
#  MAIN ENTRY POINT
# ═════════════════════════════════════════════════════════════

def render():
    """Render the full consultation page."""

    # ── Session state defaults ───────────────────────────────
    _defaults = {
        "cx_patient": None,           # selected patient dict
        "cx_ai_result": None,         # AI analysis response
        "cx_confirm_result": None,    # order confirmation response
        "cx_source": "text",          # input source (voice/text/image)
        "cx_step": "input",           # input → review → done
    }
    for k, v in _defaults.items():
        if k not in st.session_state:
            st.session_state[k] = v

    st.title("🩺 Consultation")
    st.caption("Search or register a patient, provide consultation input, review AI analysis, and send orders.")

    step = st.session_state.cx_step
    patient = st.session_state.cx_patient

    # ─────────────────────────────────────────────────────────
    # SECTION 1 — PATIENT SEARCH
    # ─────────────────────────────────────────────────────────
    with st.container(border=True):
        st.subheader("🔍 Patient Search")

        col_input, col_btn = st.columns([4, 1])
        with col_input:
            search_q = st.text_input(
                "Search by Name or IC Number",
                placeholder="e.g. Ali  or  900101-01-1234",
                key="cx_search_q",
                label_visibility="collapsed",
            )
        with col_btn:
            search_clicked = st.button("🔎 Search", type="primary",
                                       key="cx_btn_search", use_container_width=True)

        if search_clicked:
            if not search_q.strip():
                st.warning("Please enter a name or IC number.")
            else:
                try:
                    resp = requests.get(
                        f"{API_BASE}/api/patients/search",
                        params={"q": search_q.strip()},
                        headers=_headers(), timeout=10,
                    )
                    if resp.status_code == 200:
                        st.session_state["_cx_results"] = resp.json()
                    else:
                        st.error("Search failed.")
                except requests.RequestException:
                    st.warning("Backend not reachable.")

        # Display search results
        results = st.session_state.get("_cx_results", [])
        if results:
            for p in results:
                with st.container(border=True):
                    c1, c2, c3 = st.columns([3, 3, 1])
                    with c1:
                        st.markdown(f"**{p['name']}**")
                        st.caption(f"IC: {p.get('ic_number') or 'N/A'}  ·  ID: {p['patient_id']}")
                    with c2:
                        st.caption(
                            f"Age: {p.get('age') or '—'}  ·  "
                            f"📞 {p.get('phone_number') or '—'}  ·  "
                            f"Allergies: {p.get('allergies') or 'None'}"
                        )
                    with c3:
                        if st.button("Select", key=f"cx_sel_{p['patient_id']}",
                                     type="primary", use_container_width=True):
                            st.session_state.cx_patient = p
                            st.session_state.cx_step = "input"
                            st.session_state["_cx_results"] = []
                            st.rerun()

        elif search_clicked and len(results) == 0:
            st.info("No patients found.")

        # "+ Register New Patient" button (visible when no patient selected or search empty)
        if not patient:
            st.markdown("")  # spacer

    # ─────────────────────────────────────────────────────────
    # SECTION 2 — NEW PATIENT REGISTRATION (expandable)
    # ─────────────────────────────────────────────────────────
    if not patient:
        with st.expander("➕ Register New Patient", expanded=False):
            with st.form("cx_register_form"):
                st.subheader("📝 New Patient Registration")
                r1, r2 = st.columns(2)
                with r1:
                    reg_name = st.text_input("Full Name *", key="cx_reg_name")
                    reg_ic = st.text_input("IC Number", placeholder="e.g. 900101-01-1234",
                                           key="cx_reg_ic")
                    reg_dob = st.date_input("Date of Birth", value=None, key="cx_reg_dob",
                                            min_value=__import__("datetime").date(1900, 1, 1))
                    reg_phone = st.text_input("Phone Number", placeholder="e.g. 012-3456789",
                                              key="cx_reg_phone")
                with r2:
                    reg_address = st.text_input("Home Address", key="cx_reg_address")
                    reg_allergies = st.text_input("Allergies",
                                                  placeholder="e.g. Penicillin, Peanuts",
                                                  key="cx_reg_allergies")
                    reg_history = st.text_area("Medical History", key="cx_reg_history",
                                               placeholder="Previous conditions, surgeries …",
                                               height=120)

                submitted = st.form_submit_button("💾 Save Patient", type="primary",
                                                  use_container_width=True)

            if submitted:
                if not reg_name.strip():
                    st.warning("Patient name is required.")
                else:
                    calc_age = None
                    dob_str = ""
                    if reg_dob:
                        from datetime import date as _d
                        today = _d.today()
                        calc_age = today.year - reg_dob.year - (
                            (today.month, today.day) < (reg_dob.month, reg_dob.day)
                        )
                        dob_str = reg_dob.isoformat()

                    payload = {
                        "name": reg_name.strip(),
                        "age": calc_age,
                        "ic_number": reg_ic.strip() or "",
                        "date_of_birth": dob_str,
                        "phone_number": reg_phone.strip() or "",
                        "home_address": reg_address.strip() or "",
                        "allergies": reg_allergies.strip() or "",
                        "medical_history": reg_history.strip() or "",
                    }
                    try:
                        resp = requests.post(f"{API_BASE}/api/patients",
                                             data=payload, headers=_headers(), timeout=15)
                        if resp.status_code == 200:
                            pid = resp.json()["patient_id"]
                            # Fetch full record
                            pr = requests.get(f"{API_BASE}/api/patients/{pid}",
                                              headers=_headers(), timeout=10)
                            st.session_state.cx_patient = pr.json() if pr.status_code == 200 else {
                                "patient_id": pid, "name": reg_name.strip(),
                                "age": calc_age, "ic_number": reg_ic.strip(),
                            }
                            st.session_state.cx_step = "input"
                            st.success(f"✅ Patient registered (ID: {pid})")
                            st.rerun()
                        else:
                            st.error(resp.json().get("detail", resp.text))
                    except requests.RequestException:
                        st.warning("Backend not reachable.")

        # Stop here until a patient is selected
        return

    # ─────────────────────────────────────────────────────────
    # SECTION 3 — PATIENT PROFILE
    # ─────────────────────────────────────────────────────────
    with st.container(border=True):
        st.subheader("🧑‍⚕️ Patient Profile")
        c1, c2, c3 = st.columns(3)
        with c1:
            st.markdown(f"**Name:** {patient.get('name', '—')}")
            st.markdown(f"**IC Number:** {patient.get('ic_number') or '—'}")
            st.markdown(f"**Patient ID:** {patient.get('patient_id', '—')}")
        with c2:
            st.markdown(f"**Age:** {patient.get('age') or '—'}")
            st.markdown(f"**DOB:** {patient.get('date_of_birth') or '—'}")
            st.markdown(f"**Phone:** {patient.get('phone_number') or '—'}")
        with c3:
            allergy_text = patient.get("allergies") or "None"
            if allergy_text.lower() not in ("none", "none recorded", ""):
                st.warning(f"⚠️ **Allergies:** {allergy_text}")
            else:
                st.markdown("**Allergies:** None")
            hist = patient.get("medical_history") or "—"
            st.markdown(f"**History:** {hist[:120]}{'…' if len(hist) > 120 else ''}")

        # Change patient link
        if st.button("🔄 Change Patient", key="cx_change_patient"):
            st.session_state.cx_patient = None
            st.session_state.cx_ai_result = None
            st.session_state.cx_confirm_result = None
            st.session_state.cx_step = "input"
            st.rerun()

    # Route by step
    if step == "input":
        _render_input(patient)
    elif step == "review":
        _render_review(patient)
    elif step == "done":
        _render_done(patient)


# ═════════════════════════════════════════════════════════════
#  SECTION 4 + 5 — CONSULTATION INPUT + ANALYSE BUTTON
# ═════════════════════════════════════════════════════════════

def _render_input(patient: dict):
    """Section 4: Consultation Input tabs  +  Section 5: Analyse button."""
    patient_id = patient["patient_id"]

    with st.container(border=True):
        st.subheader("📝 Consultation Input")

        tab_rec, tab_audio, tab_text, tab_img = st.tabs([
            "🎙️ Voice Recording",
            "📁 Upload Audio",
            "⌨️ Transcript Input",
            "📷 Patient Image",
        ])

        # Shared language selector options
        lang_map = {
            "Auto-detect": "auto", "English": "en",
            "Malay (Bahasa Melayu)": "ms", "Mandarin (中文)": "zh",
            "Tamil (தமிழ்)": "ta", "Arabic (العربية)": "ar",
            "Hindi (हिन्दी)": "hi", "Indonesian": "id",
            "Japanese (日本語)": "ja", "Korean (한국어)": "ko",
            "Thai (ไทย)": "th",
        }

        # ── Tab 1: Voice Recording ───────────────────────────
        with tab_rec:
            st.caption("Click the microphone to start / stop recording. Works in any language.")
            lang_sel = st.selectbox("Language hint", list(lang_map.keys()), key="cx_lang_rec")

            recorded_audio = audio_recorder(
                text="", recording_color="#e74c3c", neutral_color="#1f77b4",
                icon_size="2x", key="cx_recorder",
            )
            if recorded_audio:
                st.audio(recorded_audio, format="audio/wav")
                st.success("✅ Recording captured")

            st.markdown("")
            if recorded_audio and st.button("🧠 Analyse Consultation", type="primary",
                                             key="cx_analyse_rec", use_container_width=True):
                _send_audio(patient_id, recorded_audio, None, lang_map[lang_sel])

        # ── Tab 2: Upload Audio ──────────────────────────────
        with tab_audio:
            st.caption("Upload WAV, MP3, M4A, WEBM, OGG, or FLAC.")
            lang_sel2 = st.selectbox("Language hint", list(lang_map.keys()), key="cx_lang_up")

            audio_file = st.file_uploader(
                "Upload audio file",
                type=["wav", "mp3", "m4a", "webm", "ogg", "flac"],
                key="cx_audio_file",
            )
            if audio_file:
                st.audio(audio_file)

            st.markdown("")
            if audio_file and st.button("🧠 Analyse Consultation", type="primary",
                                         key="cx_analyse_audio", use_container_width=True):
                _send_audio(patient_id, None, audio_file, lang_map[lang_sel2])

        # ── Tab 3: Transcript / Typed Notes ──────────────────
        with tab_text:
            st.caption("Type or paste consultation notes in any language. AI will translate & analyse.")
            lang_sel3 = st.selectbox("Language hint", list(lang_map.keys()), key="cx_lang_txt")

            typed_notes = st.text_area(
                "Consultation notes",
                height=180,
                placeholder="E.g. Pesakit demam tinggi dan sakit tekak.\n"
                            "Perlu ujian darah dan CBC.\n"
                            "Preskripsi antibiotik dan paracetamol.",
                key="cx_typed_notes",
            )

            st.markdown("")
            if typed_notes and typed_notes.strip():
                if st.button("🧠 Analyse Consultation", type="primary",
                             key="cx_analyse_text", use_container_width=True):
                    _send_text(patient_id, typed_notes.strip(), lang_map[lang_sel3])

        # ── Tab 4: Patient Image ─────────────────────────────
        with tab_img:
            st.caption("Upload a photo of the patient's condition (skin rash, wound, swelling, etc.).")

            image_file = st.file_uploader(
                "Upload image", type=["jpg", "jpeg", "png", "bmp"],
                key="cx_image_file",
            )
            if image_file:
                st.image(image_file, caption="Uploaded image", width=300)

            st.markdown("")
            if image_file and st.button("🧠 Analyse Image", type="primary",
                                         key="cx_analyse_img", use_container_width=True):
                _send_image(patient_id, image_file)


# ═════════════════════════════════════════════════════════════
#  SECTION 6 + 7 — AI RESULTS + ORDER CONFIRMATION
# ═════════════════════════════════════════════════════════════

def _render_review(patient: dict):
    """Display AI results and order confirmation checkboxes."""
    patient_id = patient["patient_id"]
    ai_data = st.session_state.cx_ai_result or {}
    ai = ai_data.get("ai_analysis", {})

    # ── Section 6: AI Analysis Results ───────────────────────
    with st.container(border=True):
        st.subheader("🧠 AI Analysis Results")

        # Language / translation info
        detected = ai_data.get("detected_language", "")
        if detected:
            st.caption(f"🌐 Detected language: **{detected}**")

        original = ai_data.get("original_text", "")
        translated = ai_data.get("translated_text", "")
        if original and translated and original != translated:
            with st.expander("🔄 View Translation"):
                tc1, tc2 = st.columns(2)
                with tc1:
                    st.markdown(f"**Original ({detected}):**")
                    st.text_area("", value=original, height=80, disabled=True, key="cx_orig")
                with tc2:
                    st.markdown("**English:**")
                    st.text_area("", value=translated, height=80, disabled=True, key="cx_trans")

        # Medical report
        report_text = ai_data.get("report", "")
        if report_text:
            with st.expander("📋 Medical Report", expanded=True):
                st.markdown(report_text)

        # ── Detected Symptoms (editable) ─────────────────────
        st.markdown("---")
        st.markdown("**Detected Symptoms**")
        d1, d2 = st.columns(2)
        with d1:
            edited_symptom = st.text_input("Symptom", value=ai.get("symptom", ""),
                                           key="cx_ed_symptom")
            edited_confidence = st.slider("Confidence", 0.0, 1.0,
                                          value=float(ai.get("confidence", 0.0)),
                                          step=0.05, key="cx_ed_conf")
        with d2:
            edited_test = st.text_input("Suggested Test", value=ai.get("suggested_test", ""),
                                        key="cx_ed_test")
            edited_medicine = st.text_input("Suggested Medicine",
                                            value=ai.get("suggested_medicine", ""),
                                            key="cx_ed_med")

        edited_summary = st.text_input("Summary", value=ai.get("summary", ""),
                                        key="cx_ed_summary")

    # ── Section 7: Order Confirmation ────────────────────────
    with st.container(border=True):
        st.subheader("📦 Order Confirmation")

        ai_labs = _split_items(ai.get("lab_tests", []), ai.get("suggested_test", ""))
        ai_meds = _split_items(ai.get("medications", []), ai.get("suggested_medicine", ""))

        o1, o2 = st.columns(2)

        # Lab orders
        with o1:
            st.markdown("**🔬 Lab Orders → Laboratory**")
            selected_labs = []
            for i, lab in enumerate(ai_labs):
                if st.checkbox(lab, value=True, key=f"cx_lab_{i}"):
                    selected_labs.append(lab)
            custom_lab = st.text_input("➕ Add custom lab test", key="cx_custom_lab",
                                        placeholder="e.g. Liver function test")
            if custom_lab.strip():
                selected_labs.append(custom_lab.strip())
            if not ai_labs and not custom_lab.strip():
                st.caption("_No lab tests suggested._")

        # Pharmacy orders
        with o2:
            st.markdown("**💊 Pharmacy Orders → Pharmacy**")
            selected_meds = []
            for i, med in enumerate(ai_meds):
                if st.checkbox(med, value=True, key=f"cx_med_{i}"):
                    selected_meds.append(med)
            custom_med = st.text_input("➕ Add custom medication", key="cx_custom_med",
                                        placeholder="e.g. Paracetamol 500mg")
            if custom_med.strip():
                selected_meds.append(custom_med.strip())
            if not ai_meds and not custom_med.strip():
                st.caption("_No medications suggested._")

        # Action buttons
        st.markdown("---")
        btn1, btn2 = st.columns(2)
        with btn1:
            if st.button("⬅️ Back to Input", key="cx_btn_back", use_container_width=True):
                st.session_state.cx_ai_result = None
                st.session_state.cx_step = "input"
                st.rerun()
        with btn2:
            if st.button("📤 Send Orders", type="primary", key="cx_btn_send",
                         use_container_width=True):
                with st.spinner("📦 Creating and routing orders …"):
                    _confirm_orders(
                        patient_id=patient_id,
                        ai_data=ai_data,
                        symptom=edited_symptom,
                        confidence=edited_confidence,
                        suggested_test=edited_test,
                        suggested_medicine=edited_medicine,
                        lab_tests=selected_labs,
                        medications=selected_meds,
                        summary=edited_summary,
                    )


# ═════════════════════════════════════════════════════════════
#  SECTION 8 — ORDER ROUTING (done screen)
# ═════════════════════════════════════════════════════════════

def _render_done(patient: dict):
    """Show routed orders and success state."""
    result = st.session_state.cx_confirm_result or {}
    ai = result.get("ai_analysis", {})
    orders = result.get("orders_created", [])

    st.success("✅ Orders created and routed successfully!")

    # ── Confirmed diagnosis ──────────────────────────────────
    with st.container(border=True):
        st.subheader("🩺 Confirmed Diagnosis")
        c1, c2 = st.columns(2)
        with c1:
            st.metric("Symptom", ai.get("symptom", "N/A"))
            st.metric("Confidence", f"{ai.get('confidence', 0):.0%}")
        with c2:
            st.metric("Suggested Test", ai.get("suggested_test", "N/A"))
            st.metric("Suggested Medicine", ai.get("suggested_medicine", "N/A"))

    # ── Medical report ───────────────────────────────────────
    report = result.get("report", "")
    if report:
        with st.container(border=True):
            st.subheader("📋 Medical Report")
            st.markdown(report)

    # ── Routed orders ────────────────────────────────────────
    with st.container(border=True):
        st.subheader("📦 Order Routing")

        lab_orders = [o for o in orders if o.get("department") == "Laboratory"]
        pharm_orders = [o for o in orders if o.get("department") == "Pharmacy"]

        o1, o2 = st.columns(2)
        with o1:
            st.markdown("**🔬 Lab Orders → Laboratory Dashboard**")
            if lab_orders:
                for o in lab_orders:
                    st.write(f"✅ {o['type']}  _(Order #{o['order_id']})_")
            else:
                st.caption("_No lab orders._")

        with o2:
            st.markdown("**💊 Pharmacy Orders → Pharmacy Dashboard**")
            if pharm_orders:
                for o in pharm_orders:
                    st.write(f"✅ {o['type']}  _(Order #{o['order_id']})_")
            else:
                st.caption("_No pharmacy orders._")

    # ── New consultation button ──────────────────────────────
    st.markdown("")
    if st.button("🔄 New Consultation", type="primary", key="cx_btn_new",
                 use_container_width=True):
        st.session_state.cx_patient = None
        st.session_state.cx_ai_result = None
        st.session_state.cx_confirm_result = None
        st.session_state.cx_step = "input"
        st.session_state.cx_source = "text"
        st.rerun()


# ═════════════════════════════════════════════════════════════
#  HELPER FUNCTIONS
# ═════════════════════════════════════════════════════════════

def _split_items(items_list, extra=""):
    """Split compound AI suggestions into individual clean items."""
    seen, result = set(), []
    for raw in list(items_list) + ([extra] if extra else []):
        parts = re.split(r"\s*[,;&/]\s*|\s+and\s+", raw, flags=re.IGNORECASE)
        for p in parts:
            p = re.sub(r"[(){}\[\]\"'`]", "", p).strip().strip(".-:;, ")
            if p and p.lower() not in seen:
                seen.add(p.lower())
                result.append(p)
    return result


def _send_audio(patient_id: int, recorded_bytes, audio_file, language: str):
    """Transcribe + AI analyse audio input."""
    files = {}
    if recorded_bytes:
        files["audio"] = ("recording.wav", io.BytesIO(recorded_bytes), "audio/wav")
    elif audio_file:
        raw = audio_file.read()
        files["audio"] = (audio_file.name, io.BytesIO(raw), audio_file.type)

    if not files:
        st.warning("No audio provided.")
        return

    with st.spinner("🔄 Transcribing & analysing …"):
        resp = requests.post(
            f"{API_BASE}/api/transcripts/report",
            data={"patient_id": patient_id, "language": language},
            files=files,
            headers=_headers(), timeout=120,
        )
    if resp.status_code == 200:
        st.session_state.cx_ai_result = resp.json()
        st.session_state.cx_source = "voice"
        st.session_state.cx_step = "review"
        st.rerun()
    else:
        st.error(f"Error: {resp.json().get('detail', resp.text)}")


def _send_text(patient_id: int, text: str, language: str):
    """Send typed transcript to AI for analysis."""
    with st.spinner("🔄 Translating & generating report …"):
        resp = requests.post(
            f"{API_BASE}/api/transcripts/report",
            data={"patient_id": patient_id, "text": text, "language": language},
            headers=_headers(), timeout=120,
        )
    if resp.status_code == 200:
        st.session_state.cx_ai_result = resp.json()
        st.session_state.cx_source = "text"
        st.session_state.cx_step = "review"
        st.rerun()
    else:
        st.error(f"Error: {resp.json().get('detail', resp.text)}")


def _send_image(patient_id: int, image_file):
    """Send image to AI for analysis."""
    raw = image_file.read()
    with st.spinner("🔄 Analysing image …"):
        resp = requests.post(
            f"{API_BASE}/api/transcripts/image",
            data={"patient_id": patient_id},
            files={"image": (image_file.name, io.BytesIO(raw), image_file.type)},
            headers=_headers(), timeout=60,
        )
    if resp.status_code == 200:
        st.session_state.cx_ai_result = resp.json()
        st.session_state.cx_source = "image"
        st.session_state.cx_step = "review"
        st.rerun()
    else:
        st.error(f"Error: {resp.json().get('detail', resp.text)}")


def _confirm_orders(patient_id, ai_data, symptom, confidence,
                    suggested_test, suggested_medicine,
                    lab_tests, medications, summary):
    """Send confirmed results to backend → creates orders → routes them."""
    text = ai_data.get("translated_text",
           ai_data.get("original_text",
           ai_data.get("text", "")))
    source = st.session_state.cx_source

    data = {
        "patient_id": patient_id,
        "text": text,
        "source": source,
        "symptom": symptom,
        "confidence": confidence,
        "suggested_test": suggested_test,
        "suggested_medicine": suggested_medicine,
        "lab_tests": json.dumps(lab_tests),
        "medications": json.dumps(medications),
        "summary": summary,
        "report": ai_data.get("report", ""),
    }

    resp = requests.post(
        f"{API_BASE}/api/transcripts/report/confirm",
        data=data,
        headers=_headers(), timeout=30,
    )
    if resp.status_code == 200:
        st.session_state.cx_confirm_result = resp.json()
        st.session_state.cx_step = "done"
        st.rerun()
    else:
        st.error(f"Error: {resp.json().get('detail', resp.text)}")
