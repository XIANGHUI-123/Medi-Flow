"""
main.py  ─  FastAPI backend for Medi‑Flow Orchestrator.

Endpoints:
  POST   /api/auth/register          – register a new user
  POST   /api/auth/login             – obtain JWT token
  GET    /api/patients               – list patients
  POST   /api/patients               – create a patient
  POST   /api/transcripts/text       – submit a text transcript
  POST   /api/transcripts/voice      – upload a voice recording
  POST   /api/transcripts/image      – upload a patient image
  GET    /api/orders                  – list all orders (filtered by role)
  GET    /api/orders/lab              – lab orders only
  GET    /api/orders/pharmacy         – pharmacy orders only
  PATCH  /api/orders/{order_id}/status – update order status

Run:
    uvicorn main:app --reload
"""

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, Depends, HTTPException, UploadFile, File, Form, Query
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy.orm import Session

from database import get_db, init_db
from models import User, Patient, Transcript, Order, LabOrder, Prescription, Reservation, Appointment, Visit
from auth import (
    hash_password,
    verify_password,
    create_access_token,
    get_current_user,
    require_role,
)
from ai_service import analyze_transcript, generate_medical_report
from speech_service import transcribe_audio
from image_analysis import analyze_patient_image
from order_engine import generate_orders

# ── Logging ──────────────────────────────────────────────────
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


# ── Application lifespan (startup / shutdown) ────────────────
@asynccontextmanager
async def lifespan(app: FastAPI):
    """Create tables on startup (idempotent)."""
    logger.info("Initialising database tables …")
    init_db()
    yield


app = FastAPI(
    title="Medi‑Flow Orchestrator",
    version="1.0.0",
    description="Reduce delays between consultation, lab, and pharmacy.",
    lifespan=lifespan,
)

# ── CORS (allow Streamlit frontend) ─────────────────────────
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ═════════════════════════════════════════════════════════════
#  AUTH ROUTES
# ═════════════════════════════════════════════════════════════

@app.post("/api/auth/register", tags=["Auth"])
def register(
    name: str = Form(...),
    email: str = Form(...),
    password: str = Form(...),
    role: str = Form(...),
    db: Session = Depends(get_db),
):
    """Register a new user (doctor / lab_staff / pharmacy_staff)."""
    if role not in ("doctor", "lab_staff", "pharmacy_staff"):
        raise HTTPException(400, "Invalid role")
    if db.query(User).filter(User.email == email).first():
        raise HTTPException(400, "Email already registered")

    user = User(
        name=name,
        email=email,
        password=hash_password(password),
        role=role,
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    return {"message": "User registered", "user_id": user.user_id}


@app.post("/api/auth/login", tags=["Auth"])
def login(
    username: str = Form(...),   # OAuth2 spec uses 'username'
    password: str = Form(...),
    db: Session = Depends(get_db),
):
    """Authenticate and return a JWT access token."""
    user = db.query(User).filter(User.email == username).first()
    if not user or not verify_password(password, user.password):
        raise HTTPException(401, "Invalid credentials")

    token = create_access_token({"user_id": user.user_id, "role": user.role})
    return {
        "access_token": token,
        "token_type": "bearer",
        "user_id": user.user_id,
        "name": user.name,
        "role": user.role,
    }


# ═════════════════════════════════════════════════════════════
#  PATIENT ROUTES
# ═════════════════════════════════════════════════════════════

@app.get("/api/patients", tags=["Patients"])
def list_patients(
    db: Session = Depends(get_db),
    _current_user: User = Depends(get_current_user),
):
    """Return all patients."""
    patients = db.query(Patient).all()
    return [
        {
            "patient_id": p.patient_id,
            "ic_number": p.ic_number,
            "name": p.name,
            "age": p.age,
            "date_of_birth": p.date_of_birth.isoformat() if p.date_of_birth else None,
            "phone_number": p.phone_number,
            "home_address": p.home_address,
            "allergies": p.allergies,
            "medical_history": p.medical_history,
        }
        for p in patients
    ]


@app.post("/api/patients", tags=["Patients"])
def create_patient(
    name: str = Form(...),
    age: int = Form(None),
    ic_number: str = Form(None),
    date_of_birth: str = Form(None),
    phone_number: str = Form(None),
    home_address: str = Form(None),
    allergies: str = Form(None),
    medical_history: str = Form(""),
    db: Session = Depends(get_db),
    _current_user: User = Depends(get_current_user),
):
    """Create a new patient record."""
    from datetime import date as date_type

    dob = None
    if date_of_birth:
        try:
            dob = date_type.fromisoformat(date_of_birth)
        except ValueError:
            raise HTTPException(400, "Invalid date_of_birth. Use YYYY-MM-DD.")

    # Check IC uniqueness
    if ic_number and ic_number.strip():
        existing = db.query(Patient).filter(Patient.ic_number == ic_number.strip()).first()
        if existing:
            raise HTTPException(400, f"IC Number {ic_number} already registered to {existing.name}.")

    patient = Patient(
        name=name,
        age=age,
        ic_number=ic_number.strip() if ic_number else None,
        date_of_birth=dob,
        phone_number=phone_number.strip() if phone_number else None,
        home_address=home_address.strip() if home_address else None,
        allergies=allergies.strip() if allergies else None,
        medical_history=medical_history,
    )
    db.add(patient)
    db.commit()
    db.refresh(patient)
    return {"message": "Patient created", "patient_id": patient.patient_id}


# ═════════════════════════════════════════════════════════════
#  TRANSCRIPT & ANALYSIS ROUTES
# ═════════════════════════════════════════════════════════════

@app.post("/api/transcripts/text", tags=["Transcripts"])
async def submit_text_transcript(
    patient_id: int = Form(...),
    text: str = Form(...),
    current_user: User = Depends(require_role("doctor")),
):
    """
    Doctor pastes a consultation transcript.
    → AI analysis only (no orders). Use /report/confirm to finalize.
    """
    ai_result = await analyze_transcript(text)

    return {
        "text": text,
        "source": "text",
        "ai_analysis": ai_result,
    }


@app.post("/api/transcripts/voice", tags=["Transcripts"])
async def submit_voice_recording(
    patient_id: int = Form(...),
    audio: UploadFile = File(...),
    current_user: User = Depends(require_role("doctor")),
):
    """
    Doctor uploads a voice recording.
    → speech-to-text → AI analysis (no orders). Use /report/confirm to finalize.
    """
    audio_bytes = await audio.read()

    text = transcribe_audio(audio_bytes, audio.filename or "audio.wav")
    if text.startswith("[ERROR]"):
        raise HTTPException(400, text)

    ai_result = await analyze_transcript(text)

    return {
        "transcribed_text": text,
        "text": text,
        "source": "voice",
        "ai_analysis": ai_result,
    }


@app.post("/api/transcripts/image", tags=["Transcripts"])
async def submit_patient_image(
    patient_id: int = Form(...),
    image: UploadFile = File(...),
    current_user: User = Depends(require_role("doctor")),
):
    """
    Doctor uploads a patient photo (skin rash, wound, etc.).
    → image analysis only (no orders). Use /report/confirm to finalize.
    """
    image_bytes = await image.read()

    analysis = await analyze_patient_image(image_bytes, image.filename or "image.jpg")

    # Normalize to same shape as other AI results
    ai_result = {
        "lab_tests":          [analysis.get("suggested_test", "")] if analysis.get("suggested_test") else [],
        "medications":       [analysis.get("suggested_medicine", "")] if analysis.get("suggested_medicine") else [],
        "summary":           f"Image analysis: {analysis.get('symptom', 'unknown')}",
        "symptom":           analysis.get("symptom", "unknown"),
        "confidence":        analysis.get("confidence", 0.0),
        "suggested_test":    analysis.get("suggested_test", ""),
        "suggested_medicine": analysis.get("suggested_medicine", ""),
    }

    return {
        "text": f"Image analysis: {analysis.get('symptom', 'unknown')}",
        "source": "image",
        "ai_analysis": ai_result,
    }


@app.post("/api/transcripts/transcribe", tags=["Transcripts"])
async def transcribe_only(
    language: str = Form("auto"),
    audio: UploadFile = File(...),
    current_user: User = Depends(require_role("doctor")),
):
    """
    Transcribe audio to text only (no AI analysis).
    Doctor can review/edit the transcription before proceeding.
    """
    audio_bytes = await audio.read()
    if len(audio_bytes) == 0:
        raise HTTPException(400, "Empty audio file.")

    text = transcribe_audio(audio_bytes, audio.filename or "audio.wav", language)
    if text.startswith("[ERROR]"):
        raise HTTPException(400, text)

    return {"transcribed_text": text}


@app.post("/api/transcripts/report", tags=["Transcripts"])
async def submit_smart_report(
    patient_id: int = Form(...),
    text: str = Form(None),
    language: str = Form("auto"),
    audio: UploadFile = File(None),
    db: Session = Depends(get_db),
    current_user: User = Depends(require_role("doctor")),
):
    """
    Doctor submits voice recording or typed text (any language).
    → transcribe (if voice) → AI analysis → returns results for review.
    Orders are NOT created here; use /report/confirm after doctor review.
    """
    source = "text"
    raw_text = ""

    if audio is not None:
        audio_bytes = await audio.read()
        if len(audio_bytes) > 0:
            source = "voice"
            raw_text = transcribe_audio(
                audio_bytes,
                audio.filename or "audio.wav",
                language,
            )
            if raw_text.startswith("[ERROR]"):
                raise HTTPException(400, raw_text)

    if text and text.strip():
        if raw_text:
            raw_text = raw_text + "\n\n" + text.strip()
        else:
            raw_text = text.strip()

    if not raw_text:
        raise HTTPException(400, "Please provide either voice or text input.")

    # AI: detect language, translate, generate report & extract intents
    report_result = await generate_medical_report(raw_text)

    ai_result = {
        "lab_tests":          report_result.get("lab_tests", []),
        "medications":       report_result.get("medications", []),
        "summary":           report_result.get("summary", ""),
        "symptom":           report_result.get("symptom", "unknown"),
        "confidence":        report_result.get("confidence", 0.0),
        "suggested_test":    report_result.get("suggested_test", ""),
        "suggested_medicine": report_result.get("suggested_medicine", ""),
    }

    return {
        "detected_language": report_result.get("detected_language", "unknown"),
        "original_text":     report_result.get("original_text", raw_text),
        "translated_text":   report_result.get("translated_text", raw_text),
        "report":            report_result.get("report", ""),
        "ai_analysis":       ai_result,
        "source":            source,
    }


@app.post("/api/transcripts/report/confirm", tags=["Transcripts"])
def confirm_smart_report(
    patient_id: int = Form(...),
    text: str = Form(...),
    source: str = Form("text"),
    symptom: str = Form(""),
    confidence: float = Form(0.0),
    suggested_test: str = Form(""),
    suggested_medicine: str = Form(""),
    lab_tests: str = Form("[]"),
    medications: str = Form("[]"),
    summary: str = Form(""),
    report: str = Form(""),
    db: Session = Depends(get_db),
    current_user: User = Depends(require_role("doctor")),
):
    """
    Doctor confirms (possibly edited) AI results.
    → stores transcript → creates orders.
    """
    import json as _json

    # Store transcript
    transcript = Transcript(
        patient_id=patient_id,
        doctor_id=current_user.user_id,
        text=text.strip(),
        source=source,
    )
    db.add(transcript)
    db.commit()
    db.refresh(transcript)

    # Parse list fields (sent as JSON strings from the form)
    try:
        lab_list = _json.loads(lab_tests) if lab_tests else []
    except (ValueError, TypeError):
        lab_list = []
    try:
        med_list = _json.loads(medications) if medications else []
    except (ValueError, TypeError):
        med_list = []

    ai_result = {
        "lab_tests":          lab_list,
        "medications":       med_list,
        "summary":           summary,
        "symptom":           symptom,
        "confidence":        confidence,
        "suggested_test":    suggested_test,
        "suggested_medicine": suggested_medicine,
    }
    orders = generate_orders(ai_result, patient_id, current_user.user_id, db)

    # ── Auto-create Visit for Pandemic Heatmap linkage ───────
    from datetime import date as _date_type

    # Derive diagnosis from symptom or summary
    _diag = (symptom.strip() or summary.strip() or "General consultation")[:200]
    # Derive severity from confidence: >=0.8→high, >=0.5→medium, else low
    if confidence >= 0.8:
        _sev = "high"
    elif confidence >= 0.5:
        _sev = "medium"
    else:
        _sev = "low"

    auto_visit = Visit(
        patient_id=patient_id,
        doctor_id=current_user.user_id,
        diagnosis=_diag,
        severity=_sev,
        visit_date=_date_type.today(),
        notes=f"Auto-linked from consultation (transcript #{transcript.transcript_id}). "
              f"Summary: {summary[:300]}" if summary else None,
    )
    db.add(auto_visit)
    db.commit()
    db.refresh(auto_visit)

    return {
        "transcript_id":  transcript.transcript_id,
        "report":         report,
        "ai_analysis":    ai_result,
        "orders_created": orders,
        "visit_id":       auto_visit.visit_id,
    }


# ═════════════════════════════════════════════════════════════
#  ORDER ROUTES
# ═════════════════════════════════════════════════════════════

@app.get("/api/orders", tags=["Orders"])
def list_orders(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    List orders visible to the current user's role.
    Doctors see all their orders; lab/pharmacy staff see their department.
    """
    query = db.query(Order)
    if current_user.role == "doctor":
        query = query.filter(Order.doctor_id == current_user.user_id)
    elif current_user.role == "lab_staff":
        query = query.filter(Order.department == "laboratory")
    elif current_user.role == "pharmacy_staff":
        query = query.filter(Order.department == "pharmacy")

    orders = query.order_by(Order.created_at.desc()).all()
    return [_order_to_dict(o, db) for o in orders]


@app.get("/api/orders/lab", tags=["Orders"])
def list_lab_orders(
    db: Session = Depends(get_db),
    _current_user: User = Depends(require_role("doctor", "lab_staff")),
):
    """Return all laboratory orders."""
    orders = (
        db.query(Order)
        .filter(Order.department == "laboratory")
        .order_by(Order.created_at.desc())
        .all()
    )
    return [_order_to_dict(o, db) for o in orders]


@app.get("/api/orders/pharmacy", tags=["Orders"])
def list_pharmacy_orders(
    db: Session = Depends(get_db),
    _current_user: User = Depends(require_role("doctor", "pharmacy_staff")),
):
    """Return all pharmacy / prescription orders."""
    orders = (
        db.query(Order)
        .filter(Order.department == "pharmacy")
        .order_by(Order.created_at.desc())
        .all()
    )
    return [_order_to_dict(o, db) for o in orders]


# ═════════════════════════════════════════════════════════════
#  PHARMACIST AI ENDPOINTS
# ═════════════════════════════════════════════════════════════

@app.post("/api/pharmacy/calculate-quantity", tags=["Pharmacy AI"])
def calculate_medicine_quantity(
    order_id: int = Form(...),
    db: Session = Depends(get_db),
    _current_user: User = Depends(require_role("pharmacy_staff")),
):
    """
    AI analyses the prescription + latest consultation transcript
    and returns a suggested quantity to prepare.
    """
    import asyncio
    from ai_service import _call_ai

    order = db.query(Order).filter(
        Order.order_id == order_id,
        Order.department == "pharmacy",
    ).first()
    if not order:
        raise HTTPException(404, "Pharmacy order not found.")
    if not order.prescription:
        raise HTTPException(404, "No prescription linked to this order.")

    presc = order.prescription
    patient = db.query(Patient).filter(Patient.patient_id == order.patient_id).first()

    # Fetch the most recent consultation transcript for this patient
    transcript = (
        db.query(Transcript)
        .filter(Transcript.patient_id == order.patient_id)
        .order_by(Transcript.created_at.desc())
        .first()
    )
    consultation_notes = transcript.text if transcript else "No consultation notes available."

    system_prompt = (
        "You are a clinical pharmacy assistant in Malaysia. "
        "Given a prescription and the doctor's consultation notes, "
        "calculate the total quantity of medicine to prepare.\n\n"
        "IMPORTANT RULES:\n"
        "- If dosage or duration says 'As directed' or is vague, you MUST infer "
        "a standard clinical dosage and duration based on the medicine name and "
        "the patient's symptoms from the consultation notes.\n"
        "- Use standard Malaysian pharmacy guidelines for common medicines:\n"
        "  • Paracetamol/Acetaminophen: 500mg, 3x daily, 5 days = 15 tablets\n"
        "  • Ibuprofen/NSAIDs: 400mg, 3x daily, 5 days = 15 tablets\n"
        "  • Antibiotics (Amoxicillin): 500mg, 3x daily, 7 days = 21 capsules\n"
        "  • Antihistamines (Cetirizine): 10mg, 1x daily, 7 days = 7 tablets\n"
        "  • Cough syrup/Expectorant: 10ml, 3x daily, 5 days = 150ml\n"
        "  • Decongestants: 1 tablet, 3x daily, 5 days = 15 tablets\n"
        "  • Calamine lotion: 1 bottle (100ml)\n"
        "  • Hydration salts (ORS): 1 sachet, 3x daily, 3 days = 9 sachets\n"
        "- The quantity must ALWAYS be a positive number, never 0.\n"
        "- If the medicine is a category (e.g. 'Antibiotics'), pick the most "
        "common specific medicine and calculate for that.\n\n"
        "Reply with ONLY a JSON object:\n"
        '{"quantity": <number>, "unit": "<tablets/capsules/ml/sachets/bottles>", '
        '"calculation": "<brief explanation of your dosage x frequency x days>"}'
    )
    user_content = (
        f"Medicine: {presc.medicine_name}\n"
        f"Dosage: {presc.dosage}\n"
        f"Duration: {presc.duration}\n"
        f"Patient: {patient.name if patient else 'Unknown'}\n"
        f"Allergies: {patient.allergies or 'None known' if patient else 'Unknown'}\n"
        f"Consultation Notes:\n{consultation_notes[:1500]}"
    )

    try:
        raw = asyncio.run(_call_ai(system_prompt, user_content, max_tokens=300))
    except RuntimeError:
        loop = asyncio.get_event_loop()
        raw = loop.run_until_complete(
            _call_ai(system_prompt, user_content, max_tokens=300)
        )

    if not raw:
        # Fallback: infer a standard quantity from the medicine name
        fb_qty, fb_unit, fb_calc = _fallback_quantity(presc.medicine_name)
        return {
            "order_id": order_id,
            "quantity": fb_qty,
            "unit": fb_unit,
            "calculation": fb_calc,
        }

    # Try to parse JSON from the AI response
    import json as _json
    try:
        start = raw.find("{")
        end = raw.rfind("}") + 1
        if start >= 0 and end > start:
            result = _json.loads(raw[start:end])
            result["order_id"] = order_id
            # Guard against AI returning 0
            if not result.get("quantity") or result["quantity"] == 0:
                fb_qty, fb_unit, fb_calc = _fallback_quantity(presc.medicine_name)
                result["quantity"] = fb_qty
                result["unit"] = fb_unit
                result["calculation"] = fb_calc
            return result
    except (ValueError, TypeError):
        pass

    fb_qty, fb_unit, fb_calc = _fallback_quantity(presc.medicine_name)
    return {
        "order_id": order_id,
        "quantity": fb_qty,
        "unit": fb_unit,
        "calculation": fb_calc,
    }


def _fallback_quantity(medicine_name: str) -> tuple:
    """Infer a standard quantity from the medicine name when AI is unavailable."""
    name = (medicine_name or "").lower()
    # Keyword → (quantity, unit, explanation)
    _DEFAULTS = [
        (["paracetamol", "acetaminophen"],            15, "tablets",  "Standard: 500mg × 3/day × 5 days"),
        (["ibuprofen", "nsaid"],                      15, "tablets",  "Standard: 400mg × 3/day × 5 days"),
        (["antibiotic", "amoxicillin", "azithromycin"],21, "capsules","Standard: 500mg × 3/day × 7 days"),
        (["antihistamin", "cetirizine", "loratadine"], 7, "tablets",  "Standard: 10mg × 1/day × 7 days"),
        (["cough", "expectorant", "expectoran", "dextromethorphan"],150,"ml",       "Standard: 10ml × 3/day × 5 days"),
        (["decongestant"],                            15, "tablets",  "Standard: 1 tab × 3/day × 5 days"),
        (["calamine", "lotion", "cream", "ointment"],  1, "bottle",   "Standard: 1 bottle (100ml)"),
        (["hydration", "ors", "oral rehydration"],     9, "sachets",  "Standard: 1 sachet × 3/day × 3 days"),
        (["pain", "analgesic"],                       15, "tablets",  "Standard: 1 tab × 3/day × 5 days"),
        (["suppressant"],                             15, "tablets",  "Standard: 1 tab × 3/day × 5 days"),
        (["fever"],                                   15, "tablets",  "Standard: 500mg × 3/day × 5 days"),
    ]
    for keywords, qty, unit, calc in _DEFAULTS:
        if any(kw in name for kw in keywords):
            return qty, unit, calc
    return 15, "tablets", "Standard estimate: 1 tab × 3/day × 5 days"


@app.post("/api/pharmacy/send-reminder", tags=["Pharmacy AI"])
def send_patient_reminder(
    order_id: int = Form(...),
    db: Session = Depends(get_db),
    _current_user: User = Depends(require_role("pharmacy_staff")),
):
    """
    AI generates a patient reminder message based on the prescription status.
    If medicine duration is ending/finished -> remind to refill or checkup.
    """
    import asyncio
    from ai_service import _call_ai

    order = db.query(Order).filter(
        Order.order_id == order_id,
        Order.department == "pharmacy",
    ).first()
    if not order:
        raise HTTPException(404, "Pharmacy order not found.")
    if not order.prescription:
        raise HTTPException(404, "No prescription linked to this order.")

    presc = order.prescription
    patient = db.query(Patient).filter(Patient.patient_id == order.patient_id).first()
    patient_name = patient.name if patient else "Patient"

    system_prompt = (
        "You are a friendly healthcare assistant. "
        "Generate a short, professional SMS-style reminder message for a patient. "
        "The message should:\n"
        "- Address the patient by name\n"
        "- Mention their medicine and dosage\n"
        "- If the medicine course is ending or completed, remind them to "
        "schedule a follow-up checkup\n"
        "- If the medicine is ongoing, gently remind them to take it as prescribed\n"
        "- Be warm, concise, and professional (max 160 characters if possible)\n"
        "Reply with ONLY a JSON object: "
        '{"message": "<the reminder text>", "type": "<refill|followup|ongoing>"}'
    )
    user_content = (
        f"Patient: {patient_name}\n"
        f"Medicine: {presc.medicine_name}\n"
        f"Dosage: {presc.dosage}\n"
        f"Duration: {presc.duration}\n"
        f"Order Status: {order.status}\n"
        f"Prescribed Date: {order.created_at.isoformat() if order.created_at else 'Unknown'}\n"
        f"Dispensed: {'Yes' if presc.dispensed_at else 'Not yet'}"
    )

    try:
        raw = asyncio.run(_call_ai(system_prompt, user_content, max_tokens=300))
    except RuntimeError:
        loop = asyncio.get_event_loop()
        raw = loop.run_until_complete(
            _call_ai(system_prompt, user_content, max_tokens=300)
        )

    if not raw:
        fallback_msg = (
            f"Hi {patient_name}, your {presc.medicine_name} ({presc.dosage}) "
            f"prescription is {order.status}. Please schedule a follow-up "
            f"checkup if needed. — Medi-Flow Pharmacy"
        )
        return {
            "order_id": order_id,
            "patient_name": patient_name,
            "message": fallback_msg,
            "type": "followup",
            "sent": True,
        }

    import json as _json
    try:
        start = raw.find("{")
        end = raw.rfind("}") + 1
        if start >= 0 and end > start:
            result = _json.loads(raw[start:end])
            result["order_id"] = order_id
            result["patient_name"] = patient_name
            result["sent"] = True
            return result
    except (ValueError, TypeError):
        pass

    return {
        "order_id": order_id,
        "patient_name": patient_name,
        "message": raw[:300],
        "type": "general",
        "sent": True,
    }


@app.patch("/api/orders/{order_id}/status", tags=["Orders"])
def update_order_status(
    order_id: int,
    status: str = Form(...),
    db: Session = Depends(get_db),
    _current_user: User = Depends(get_current_user),
):
    """Update the status of an order (pending → in_progress → completed)."""
    valid = {"pending", "sent", "in_progress", "completed"}
    if status not in valid:
        raise HTTPException(400, f"Status must be one of {valid}")

    order = db.query(Order).filter(Order.order_id == order_id).first()
    if not order:
        raise HTTPException(404, "Order not found")

    order.status = status
    db.commit()
    return {"message": "Status updated", "order_id": order_id, "status": status}


# ── helper ───────────────────────────────────────────────────
def _order_to_dict(order: Order, db: Session) -> dict:
    """Serialize an Order (with its patient, lab, or prescription detail)."""
    patient = db.query(Patient).filter(Patient.patient_id == order.patient_id).first()
    result = {
        "order_id":    order.order_id,
        "patient_id":  order.patient_id,
        "patient_name": patient.name if patient else "Unknown",
        "department":  order.department,
        "order_type":  order.order_type,
        "details":     order.details,
        "status":      order.status,
        "created_at":  order.created_at.isoformat() if order.created_at else None,
    }
    if order.department == "laboratory" and order.lab_order:
        result["test_name"] = order.lab_order.test_name
        result["urgency"]   = order.lab_order.urgency
        result["result"]    = order.lab_order.result
    if order.department == "pharmacy" and order.prescription:
        result["medicine"]  = order.prescription.medicine_name
        result["dosage"]    = order.prescription.dosage
        result["duration"]  = order.prescription.duration
        # Extra patient details for the pharmacy dashboard
        if patient:
            result["phone_number"]    = patient.phone_number
            result["home_address"]    = patient.home_address
            result["allergies"]       = patient.allergies
            result["medical_history"] = patient.medical_history
        # Latest consultation / doctor notes
        transcript = (
            db.query(Transcript)
            .filter(Transcript.patient_id == order.patient_id)
            .order_by(Transcript.created_at.desc())
            .first()
        )
        if transcript:
            doctor = db.query(User).filter(User.user_id == transcript.doctor_id).first()
            result["doctor_notes"]     = transcript.text
            result["doctor_name"]      = doctor.name if doctor else "Unknown"
            result["consultation_date"] = (
                transcript.created_at.isoformat() if transcript.created_at else None
            )
    return result


# ═════════════════════════════════════════════════════════════
#  PATIENT CONSULTATIONS (for pharmacist doctor‑notes view)
# ═════════════════════════════════════════════════════════════

@app.get("/api/patients/{patient_id}/consultations", tags=["Patients"])
def get_patient_consultations(
    patient_id: int,
    db: Session = Depends(get_db),
    _current_user: User = Depends(get_current_user),
):
    """Return the latest consultation transcripts for a patient."""
    transcripts = (
        db.query(Transcript)
        .filter(Transcript.patient_id == patient_id)
        .order_by(Transcript.created_at.desc())
        .limit(5)
        .all()
    )
    results = []
    for t in transcripts:
        doctor = db.query(User).filter(User.user_id == t.doctor_id).first()
        results.append({
            "transcript_id": t.transcript_id,
            "text":          t.text,
            "source":        t.source,
            "doctor_name":   doctor.name if doctor else "Unknown",
            "created_at":    t.created_at.isoformat() if t.created_at else None,
        })
    return results


# ═════════════════════════════════════════════════════════════
#  PATIENT SEARCH
# ═════════════════════════════════════════════════════════════

@app.get("/api/patients/search", tags=["Patients"])
def search_patients(
    q: str = Query("", description="Search by name, IC number, or patient ID"),
    db: Session = Depends(get_db),
    _current_user: User = Depends(get_current_user),
):
    """Search patients by name (partial match), IC number, or patient ID."""
    query = db.query(Patient)
    if q.strip():
        term = q.strip()
        if term.isdigit():
            query = query.filter(Patient.patient_id == int(term))
        else:
            # Search by name OR IC number
            query = query.filter(
                (Patient.name.ilike(f"%{term}%")) |
                (Patient.ic_number.ilike(f"%{term}%"))
            )
    patients = query.order_by(Patient.name).limit(50).all()
    return [
        {
            "patient_id": p.patient_id,
            "ic_number": p.ic_number,
            "name": p.name,
            "age": p.age,
            "date_of_birth": p.date_of_birth.isoformat() if p.date_of_birth else None,
            "phone_number": p.phone_number,
            "home_address": p.home_address,
            "allergies": p.allergies,
            "medical_history": p.medical_history,
            "created_at": p.created_at.isoformat() if p.created_at else None,
        }
        for p in patients
    ]


@app.get("/api/patients/{patient_id}", tags=["Patients"])
def get_patient(
    patient_id: int,
    db: Session = Depends(get_db),
    _current_user: User = Depends(get_current_user),
):
    """Get a single patient's full details including order history."""
    patient = db.query(Patient).filter(Patient.patient_id == patient_id).first()
    if not patient:
        raise HTTPException(404, "Patient not found")
    orders = db.query(Order).filter(Order.patient_id == patient_id).order_by(Order.created_at.desc()).all()
    return {
        "patient_id": patient.patient_id,
        "ic_number": patient.ic_number,
        "name": patient.name,
        "age": patient.age,
        "date_of_birth": patient.date_of_birth.isoformat() if patient.date_of_birth else None,
        "phone_number": patient.phone_number,
        "home_address": patient.home_address,
        "allergies": patient.allergies,
        "medical_history": patient.medical_history,
        "created_at": patient.created_at.isoformat() if patient.created_at else None,
        "orders": [_order_to_dict(o, db) for o in orders],
    }


# ═════════════════════════════════════════════════════════════
#  RESERVATION / OPERATION SCHEDULING
# ═════════════════════════════════════════════════════════════

@app.post("/api/reservations", tags=["Reservations"])
def create_reservation(
    patient_id: int = Form(...),
    operation_type: str = Form(...),
    scheduled_date: str = Form(...),
    scheduled_time: str = Form(...),
    duration_min: int = Form(60),
    notes: str = Form(""),
    db: Session = Depends(get_db),
    current_user: User = Depends(require_role("doctor")),
):
    """Book an operation / procedure for a patient."""
    from datetime import date as date_type
    try:
        parsed_date = date_type.fromisoformat(scheduled_date)
    except ValueError:
        raise HTTPException(400, "Invalid date format. Use YYYY-MM-DD.")

    reservation = Reservation(
        patient_id=patient_id,
        doctor_id=current_user.user_id,
        operation_type=operation_type,
        scheduled_date=parsed_date,
        scheduled_time=scheduled_time,
        duration_min=duration_min,
        notes=notes,
    )
    db.add(reservation)
    db.commit()
    db.refresh(reservation)
    return {"message": "Reservation created", "reservation_id": reservation.reservation_id}


@app.get("/api/reservations", tags=["Reservations"])
def list_reservations(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """List reservations. Doctors see their own; others see all."""
    query = db.query(Reservation)
    if current_user.role == "doctor":
        query = query.filter(Reservation.doctor_id == current_user.user_id)
    reservations = query.order_by(Reservation.scheduled_date.desc()).all()
    result = []
    for r in reservations:
        patient = db.query(Patient).filter(Patient.patient_id == r.patient_id).first()
        result.append({
            "reservation_id": r.reservation_id,
            "patient_id": r.patient_id,
            "patient_name": patient.name if patient else "Unknown",
            "operation_type": r.operation_type,
            "scheduled_date": r.scheduled_date.isoformat(),
            "scheduled_time": r.scheduled_time,
            "duration_min": r.duration_min,
            "notes": r.notes,
            "status": r.status,
            "created_at": r.created_at.isoformat() if r.created_at else None,
        })
    return result


@app.patch("/api/reservations/{reservation_id}/status", tags=["Reservations"])
def update_reservation_status(
    reservation_id: int,
    status: str = Form(...),
    db: Session = Depends(get_db),
    _current_user: User = Depends(get_current_user),
):
    """Update a reservation's status."""
    valid = {"scheduled", "in_progress", "completed", "cancelled"}
    if status not in valid:
        raise HTTPException(400, f"Status must be one of {valid}")
    reservation = db.query(Reservation).filter(Reservation.reservation_id == reservation_id).first()
    if not reservation:
        raise HTTPException(404, "Reservation not found")
    reservation.status = status
    db.commit()
    return {"message": "Reservation updated", "reservation_id": reservation_id, "status": status}


# ═════════════════════════════════════════════════════════════
#  APPOINTMENTS  (AI chat-booked consultations)
# ═════════════════════════════════════════════════════════════

@app.post("/api/appointments", tags=["Appointments"])
def create_appointment(
    patient_id: int = Form(...),
    patient_name: str = Form(...),
    appointment_date: str = Form(...),
    appointment_time: str = Form(...),
    reason: str = Form(""),
    db: Session = Depends(get_db),
    current_user: User = Depends(require_role("doctor")),
):
    """Book a consultation appointment for a patient."""
    from datetime import date as date_type
    try:
        parsed_date = date_type.fromisoformat(appointment_date)
    except ValueError:
        raise HTTPException(400, "Invalid date format. Use YYYY-MM-DD.")

    # Check for time-slot conflict on the same date for this doctor
    conflict = (
        db.query(Appointment)
        .filter(
            Appointment.doctor_id == current_user.user_id,
            Appointment.appointment_date == parsed_date,
            Appointment.appointment_time == appointment_time,
            Appointment.status != "cancelled",
        )
        .first()
    )
    if conflict:
        raise HTTPException(
            409,
            f"Time slot {appointment_time} on {appointment_date} is already booked."
        )

    appt = Appointment(
        patient_id=patient_id,
        doctor_id=current_user.user_id,
        patient_name=patient_name,
        appointment_date=parsed_date,
        appointment_time=appointment_time,
        reason=reason,
    )
    db.add(appt)
    db.commit()
    db.refresh(appt)
    return {
        "message": "Appointment created",
        "appointment_id": appt.appointment_id,
        "patient_name": appt.patient_name,
        "appointment_date": appt.appointment_date.isoformat(),
        "appointment_time": appt.appointment_time,
        "reason": appt.reason,
    }


@app.get("/api/appointments", tags=["Appointments"])
def list_appointments(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """List appointments. Doctors see their own."""
    query = db.query(Appointment)
    if current_user.role == "doctor":
        query = query.filter(Appointment.doctor_id == current_user.user_id)
    appointments = query.order_by(Appointment.appointment_date.desc()).all()
    return [
        {
            "appointment_id": a.appointment_id,
            "patient_id": a.patient_id,
            "patient_name": a.patient_name,
            "appointment_date": a.appointment_date.isoformat(),
            "appointment_time": a.appointment_time,
            "reason": a.reason,
            "status": a.status,
            "created_at": a.created_at.isoformat() if a.created_at else None,
        }
        for a in appointments
    ]


@app.get("/api/appointments/schedule", tags=["Appointments"])
def get_schedule(
    date: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_role("doctor")),
):
    """Return booked time-slots for the current doctor on a given date."""
    from datetime import date as date_type
    try:
        parsed_date = date_type.fromisoformat(date)
    except ValueError:
        raise HTTPException(400, "Invalid date format. Use YYYY-MM-DD.")

    booked = (
        db.query(Appointment)
        .filter(
            Appointment.doctor_id == current_user.user_id,
            Appointment.appointment_date == parsed_date,
            Appointment.status != "cancelled",
        )
        .all()
    )
    return {
        "date": date,
        "booked_slots": [
            {
                "time": a.appointment_time,
                "patient_name": a.patient_name,
                "reason": a.reason,
            }
            for a in booked
        ],
    }


# ═════════════════════════════════════════════════════════════
#  VISITS  (patient visits for pandemic heatmap)
# ═════════════════════════════════════════════════════════════

@app.post("/api/visits", tags=["Visits"])
def create_visit(
    patient_id: int = Form(...),
    diagnosis: str = Form(...),
    severity: str = Form("low"),
    visit_date: str = Form(...),
    notes: str = Form(""),
    db: Session = Depends(get_db),
    current_user: User = Depends(require_role("doctor")),
):
    """Record a patient visit with diagnosis and severity."""
    from datetime import date as date_type
    patient = db.query(Patient).filter(Patient.patient_id == patient_id).first()
    if not patient:
        raise HTTPException(404, "Patient not found.")
    if severity not in ("low", "medium", "high"):
        raise HTTPException(400, "Severity must be low, medium, or high.")
    try:
        parsed_date = date_type.fromisoformat(visit_date)
    except ValueError:
        raise HTTPException(400, "Invalid date format. Use YYYY-MM-DD.")

    visit = Visit(
        patient_id=patient_id,
        doctor_id=current_user.user_id,
        diagnosis=diagnosis.strip(),
        severity=severity,
        visit_date=parsed_date,
        notes=notes.strip() if notes else None,
    )
    db.add(visit)
    db.commit()
    db.refresh(visit)
    return {
        "message": "Visit recorded",
        "visit_id": visit.visit_id,
        "patient_name": patient.name,
        "diagnosis": visit.diagnosis,
        "severity": visit.severity,
        "visit_date": visit.visit_date.isoformat(),
    }


@app.get("/api/visits", tags=["Visits"])
def list_visits(
    start_date: str = Query(None),
    end_date: str = Query(None),
    diagnosis: str = Query(None),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """List visits with optional date range and diagnosis filter."""
    from datetime import date as date_type
    query = db.query(Visit, Patient).join(Patient, Visit.patient_id == Patient.patient_id)

    if start_date:
        try:
            query = query.filter(Visit.visit_date >= date_type.fromisoformat(start_date))
        except ValueError:
            raise HTTPException(400, "Invalid start_date.")
    if end_date:
        try:
            query = query.filter(Visit.visit_date <= date_type.fromisoformat(end_date))
        except ValueError:
            raise HTTPException(400, "Invalid end_date.")
    if diagnosis:
        query = query.filter(Visit.diagnosis.ilike(f"%{diagnosis}%"))

    rows = query.order_by(Visit.visit_date.desc()).all()
    return [
        {
            "visit_id": v.visit_id,
            "patient_id": v.patient_id,
            "patient_name": p.name,
            "home_address": p.home_address or "",
            "diagnosis": v.diagnosis,
            "severity": v.severity,
            "visit_date": v.visit_date.isoformat(),
            "notes": v.notes,
        }
        for v, p in rows
    ]


# ═════════════════════════════════════════════════════════════
#  HEALTH CHECK
# ═════════════════════════════════════════════════════════════

@app.get("/", tags=["Health"])
def health():
    return {"status": "ok", "service": "Medi-Flow Orchestrator"}


# ── Run with:  python main.py  ──────────────────────────────
if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="127.0.0.1", port=8000, reload=True)
