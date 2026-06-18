# 🏥 Medi‑Flow Orchestrator — MVP

> Reduce delays between **consultation → laboratory → pharmacy** by detecting
> medical‑action intents from doctor‑patient interactions and automatically
> generating digital orders.

---

## Project Structure

```
project/
├── main.py              # FastAPI backend (all REST endpoints)
├── database.py          # MySQL connection via SQLAlchemy
├── models.py            # ORM models (users, patients, orders …)
├── auth.py              # JWT authentication & role middleware
├── ai_service.py        # External AI API integration (transcript + image)
├── speech_service.py    # Speech‑to‑text (SpeechRecognition + pydub)
├── image_analysis.py    # Patient image symptom analysis
├── order_engine.py      # Automated order generation from AI results
├── streamlit_app.py     # Streamlit frontend (4 pages)
├── schema.sql           # MySQL bootstrap script
├── requirements.txt     # Python dependencies
├── .env                 # Environment variables (credentials, DB config)
└── README.md            # ← you are here
```

---

## Prerequisites

| Tool   | Version |
|--------|---------|
| Python | 3.10+   |
| MySQL  | 8.0+    |
| ffmpeg | latest  |

> **ffmpeg** is needed by *pydub* for audio format conversion.
> Install via `choco install ffmpeg` (Windows) or `brew install ffmpeg` (macOS).

---

## Quick Start

### 1. Create a virtual environment

```bash
cd Hackathon
python -m venv venv
venv\Scripts\activate        # Windows
# source venv/bin/activate   # macOS / Linux
```

### 2. Install dependencies

```bash
pip install -r requirements.txt
```

### 3. Set up MySQL

1. Start your MySQL server.
2. Edit `.env` with your MySQL credentials (`DB_USER`, `DB_PASSWORD`).
3. Run the schema script:

```bash
mysql -u root -p < schema.sql
```

This creates the `mediflow` database, all tables, and seed data
(demo doctor, lab tech, pharmacist, and one patient).

### 4. Start the FastAPI backend

```bash
python main.py
```

The API will be available at **http://127.0.0.1:8000**.
Swagger docs at **http://127.0.0.1:8000/docs**.

### 5. Start the Streamlit frontend

Open a **second terminal** and run:

```bash
streamlit run streamlit_app.py
```

The UI opens at **http://localhost:8501**.

---

## Default Accounts (from schema.sql seed)

| Role            | Email                  | Password    |
|-----------------|------------------------|-------------|
| Doctor          | doctor@mediflow.com    | doctor123   |
| Lab Staff       | lab@mediflow.com       | doctor123   |
| Pharmacy Staff  | pharmacy@mediflow.com  | doctor123   |

> ⚠️ The seed passwords use a placeholder bcrypt hash.
> **Register new accounts through the app** for working logins,
> or run the register API endpoint.

---

## Working Workflow Demo

```
1. Login as Doctor
2. Select patient "Ali bin Abu"
3. Paste transcript:
     "Patient has high fever and sore throat.
      Please do blood test and CBC.
      Prescribe antibiotics and paracetamol."
4. Click "Analyse Transcript"
5. ✅ AI detects: blood test, cbc (lab) + antibiotics, paracetamol (pharmacy)
6. ✅ Orders auto-created and routed
7. Login as Lab Staff  → see lab orders
8. Login as Pharmacist → see prescriptions
```

---

## API Endpoints

| Method | Endpoint                          | Auth | Description                     |
|--------|-----------------------------------|------|---------------------------------|
| POST   | `/api/auth/register`              | —    | Register user                   |
| POST   | `/api/auth/login`                 | —    | Get JWT token                   |
| GET    | `/api/patients`                   | ✅   | List patients                   |
| POST   | `/api/patients`                   | ✅   | Create patient                  |
| POST   | `/api/transcripts/text`           | 🩺   | Submit text transcript          |
| POST   | `/api/transcripts/voice`          | 🩺   | Upload voice → transcribe       |
| POST   | `/api/transcripts/image`          | 🩺   | Upload image → analyse          |
| GET    | `/api/orders`                     | ✅   | List orders (role‑filtered)     |
| GET    | `/api/orders/lab`                 | 🔬   | Lab orders                      |
| GET    | `/api/orders/pharmacy`            | 💊   | Pharmacy orders                 |
| PATCH  | `/api/orders/{id}/status`         | ✅   | Update order status             |

Legend: ✅ any authenticated user · 🩺 doctor only · 🔬 doctor or lab · 💊 doctor or pharmacy

---

## Architecture

```
 ┌─────────────┐   HTTP    ┌──────────────┐   SQL    ┌───────┐
 │  Streamlit  │ ───────▶  │   FastAPI     │ ──────▶ │ MySQL │
 │  Frontend   │           │   Backend     │          └───────┘
 └─────────────┘           │               │
                           │  ┌──────────┐ │   HTTPS
                           │  │ AI Svc   │─│───────▶  Flex AI API
                           │  └──────────┘ │
                           │  ┌──────────┐ │
                           │  │ Speech   │ │   (Google Web Speech)
                           │  └──────────┘ │
                           └──────────────┘
```

---

## License

MIT — built for hackathon / educational purposes.
