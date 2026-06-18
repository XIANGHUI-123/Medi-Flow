"""
models.py  ─  SQLAlchemy ORM models for Medi‑Flow Orchestrator.

Tables:
  users, patients, transcripts, orders, lab_orders, prescriptions,
  reservations, appointments, visits
"""

from datetime import datetime
from sqlalchemy import (
    Column, Integer, String, Text, DateTime, Date, Enum, ForeignKey,
)
from sqlalchemy.orm import relationship
from database import Base


# ── Users ────────────────────────────────────────────────────
class User(Base):
    __tablename__ = "users"

    user_id    = Column(Integer, primary_key=True, autoincrement=True)
    name       = Column(String(120), nullable=False)
    email      = Column(String(255), nullable=False, unique=True)
    password   = Column(String(255), nullable=False)          # bcrypt hash
    role       = Column(
        Enum("doctor", "lab_staff", "pharmacy_staff", name="user_role"),
        nullable=False,
    )
    created_at = Column(DateTime, default=datetime.utcnow)

    # Relationships
    transcripts = relationship("Transcript", back_populates="doctor")
    orders      = relationship("Order",      back_populates="doctor")


# ── Patients ─────────────────────────────────────────────────
class Patient(Base):
    __tablename__ = "patients"

    patient_id      = Column(Integer, primary_key=True, autoincrement=True)
    ic_number       = Column(String(20), unique=True)
    name            = Column(String(120), nullable=False)
    age             = Column(Integer)
    date_of_birth   = Column(Date)
    phone_number    = Column(String(20))
    home_address    = Column(Text)
    allergies       = Column(Text)
    medical_history = Column(Text)
    created_at      = Column(DateTime, default=datetime.utcnow)

    # Relationships
    transcripts = relationship("Transcript", back_populates="patient")
    orders      = relationship("Order",      back_populates="patient")


# ── Transcripts ──────────────────────────────────────────────
class Transcript(Base):
    __tablename__ = "transcripts"

    transcript_id = Column(Integer, primary_key=True, autoincrement=True)
    patient_id    = Column(Integer, ForeignKey("patients.patient_id"), nullable=False)
    doctor_id     = Column(Integer, ForeignKey("users.user_id"),       nullable=False)
    text          = Column(Text, nullable=False)
    source        = Column(
        Enum("voice", "text", "image", name="transcript_source"),
        default="text",
    )
    created_at    = Column(DateTime, default=datetime.utcnow)

    # Relationships
    patient = relationship("Patient", back_populates="transcripts")
    doctor  = relationship("User",    back_populates="transcripts")


# ── Orders (lab or pharmacy) ────────────────────────────────
class Order(Base):
    __tablename__ = "orders"

    order_id   = Column(Integer, primary_key=True, autoincrement=True)
    patient_id = Column(Integer, ForeignKey("patients.patient_id"), nullable=False)
    doctor_id  = Column(Integer, ForeignKey("users.user_id"),       nullable=False)
    department = Column(
        Enum("laboratory", "pharmacy", name="department_type"),
        nullable=False,
    )
    order_type = Column(String(120), nullable=False)
    details    = Column(Text)
    status     = Column(
        Enum("pending", "sent", "in_progress", "completed", name="order_status"),
        default="pending",
    )
    created_at = Column(DateTime, default=datetime.utcnow)

    # Relationships
    patient      = relationship("Patient",      back_populates="orders")
    doctor       = relationship("User",         back_populates="orders")
    lab_order    = relationship("LabOrder",     back_populates="order", uselist=False)
    prescription = relationship("Prescription", back_populates="order", uselist=False)


# ── Lab Orders (extended detail) ────────────────────────────
class LabOrder(Base):
    __tablename__ = "lab_orders"

    lab_order_id = Column(Integer, primary_key=True, autoincrement=True)
    order_id     = Column(Integer, ForeignKey("orders.order_id"), nullable=False)
    test_name    = Column(String(120), nullable=False)
    urgency      = Column(
        Enum("routine", "urgent", name="urgency_level"),
        default="routine",
    )
    result       = Column(Text)
    completed_at = Column(DateTime)

    order = relationship("Order", back_populates="lab_order")


# ── Prescriptions (extended detail) ─────────────────────────
class Prescription(Base):
    __tablename__ = "prescriptions"

    prescription_id = Column(Integer, primary_key=True, autoincrement=True)
    order_id        = Column(Integer, ForeignKey("orders.order_id"), nullable=False)
    medicine_name   = Column(String(200), nullable=False)
    dosage          = Column(String(120))
    duration        = Column(String(120))
    dispensed_at    = Column(DateTime)

    order = relationship("Order", back_populates="prescription")


# ── Reservations (operation / procedure scheduling) ─────────
class Reservation(Base):
    __tablename__ = "reservations"

    reservation_id = Column(Integer, primary_key=True, autoincrement=True)
    patient_id     = Column(Integer, ForeignKey("patients.patient_id"), nullable=False)
    doctor_id      = Column(Integer, ForeignKey("users.user_id"),       nullable=False)
    operation_type = Column(String(200), nullable=False)
    scheduled_date = Column(Date, nullable=False)
    scheduled_time = Column(String(10), nullable=False)       # e.g. "09:30"
    duration_min   = Column(Integer, default=60)
    notes          = Column(Text)
    status         = Column(
        Enum("scheduled", "in_progress", "completed", "cancelled", name="reservation_status"),
        default="scheduled",
    )
    created_at     = Column(DateTime, default=datetime.utcnow)

    # Relationships
    patient = relationship("Patient")
    doctor  = relationship("User")


# ── Appointments (AI chat-booked consultations) ─────────────
class Appointment(Base):
    __tablename__ = "appointments"

    appointment_id   = Column(Integer, primary_key=True, autoincrement=True)
    patient_id       = Column(Integer, ForeignKey("patients.patient_id"), nullable=False)
    doctor_id        = Column(Integer, ForeignKey("users.user_id"),       nullable=False)
    patient_name     = Column(String(100), nullable=False)
    appointment_date = Column(Date, nullable=False)
    appointment_time = Column(String(10), nullable=False)     # e.g. "10:00"
    reason           = Column(Text)
    status           = Column(
        Enum("scheduled", "completed", "cancelled", name="appointment_status"),
        default="scheduled",
    )
    created_at       = Column(DateTime, default=datetime.utcnow)

    # Relationships
    patient = relationship("Patient")
    doctor  = relationship("User")


# ── Visits (patient visits with diagnosis for pandemic tracking) ──
class Visit(Base):
    __tablename__ = "visits"

    visit_id   = Column(Integer, primary_key=True, autoincrement=True)
    patient_id = Column(Integer, ForeignKey("patients.patient_id"), nullable=False)
    doctor_id  = Column(Integer, ForeignKey("users.user_id"),       nullable=False)
    diagnosis  = Column(String(200), nullable=False)
    severity   = Column(
        Enum("low", "medium", "high", name="visit_severity"),
        default="low",
    )
    visit_date = Column(Date, nullable=False)
    notes      = Column(Text)
    created_at = Column(DateTime, default=datetime.utcnow)

    patient = relationship("Patient")
    doctor  = relationship("User")
