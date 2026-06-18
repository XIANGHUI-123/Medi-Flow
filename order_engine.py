"""
order_engine.py  ─  Automated medical order generation.

Takes the structured output from ``ai_service.analyze_transcript`` and
creates the appropriate database records:
  • Lab orders   → orders + lab_orders tables
  • Prescriptions → orders + prescriptions tables

Public API:
    generate_orders(ai_result, patient_id, doctor_id, db) -> list[dict]
"""

import logging
from datetime import datetime
from sqlalchemy.orm import Session

from models import Order, LabOrder, Prescription

logger = logging.getLogger(__name__)


def generate_orders(
    ai_result: dict,
    patient_id: int,
    doctor_id: int,
    db: Session,
) -> list[dict]:
    """
    Create order records from AI analysis results.

    Parameters
    ----------
    ai_result : dict
        Must contain ``lab_tests`` (list[str]) and ``medications`` (list[str]).
    patient_id : int
        The patient this consultation belongs to.
    doctor_id : int
        The doctor who triggered the analysis.
    db : Session
        Active SQLAlchemy session.

    Returns
    -------
    list[dict]
        Summary of all orders created, suitable for API response.
    """
    created_orders: list[dict] = []

    # ── 1. Generate lab test orders ──────────────────────────
    for test_name in ai_result.get("lab_tests", []):
        order = Order(
            patient_id=patient_id,
            doctor_id=doctor_id,
            department="laboratory",
            order_type=test_name.title(),
            details=f"AI-detected lab test: {test_name}",
            status="sent",
        )
        db.add(order)
        db.flush()   # get the auto‑generated order_id

        lab = LabOrder(
            order_id=order.order_id,
            test_name=test_name.title(),
            urgency="routine",
        )
        db.add(lab)

        created_orders.append({
            "order_id":   order.order_id,
            "department": "Laboratory",
            "type":       test_name.title(),
            "status":     "Sent",
            "timestamp":  order.created_at.isoformat() if order.created_at else datetime.utcnow().isoformat(),
        })
        logger.info("Lab order created: %s (order #%d)", test_name, order.order_id)

    # ── 2. Generate medication / prescription orders ─────────
    for med_name in ai_result.get("medications", []):
        order = Order(
            patient_id=patient_id,
            doctor_id=doctor_id,
            department="pharmacy",
            order_type=med_name.title(),
            details=f"AI-detected medication: {med_name}",
            status="sent",
        )
        db.add(order)
        db.flush()

        rx = Prescription(
            order_id=order.order_id,
            medicine_name=med_name.title(),
            dosage="As directed",
            duration="As directed",
        )
        db.add(rx)

        created_orders.append({
            "order_id":   order.order_id,
            "department": "Pharmacy",
            "type":       med_name.title(),
            "status":     "Sent",
            "timestamp":  order.created_at.isoformat() if order.created_at else datetime.utcnow().isoformat(),
        })
        logger.info("Prescription created: %s (order #%d)", med_name, order.order_id)

    # ── 3. Generate orders from image analysis suggestions ───
    # (These come as single strings, not lists)
    suggested_test = ai_result.get("suggested_test")
    suggested_med  = ai_result.get("suggested_medicine")

    if suggested_test and suggested_test not in [t.lower() for t in ai_result.get("lab_tests", [])]:
        order = Order(
            patient_id=patient_id,
            doctor_id=doctor_id,
            department="laboratory",
            order_type=suggested_test.title(),
            details=f"AI-suggested test from image analysis: {suggested_test}",
            status="sent",
        )
        db.add(order)
        db.flush()
        lab = LabOrder(
            order_id=order.order_id,
            test_name=suggested_test.title(),
            urgency="routine",
        )
        db.add(lab)
        created_orders.append({
            "order_id":   order.order_id,
            "department": "Laboratory",
            "type":       suggested_test.title(),
            "status":     "Sent",
            "timestamp":  order.created_at.isoformat() if order.created_at else datetime.utcnow().isoformat(),
        })

    if suggested_med and suggested_med not in [m.lower() for m in ai_result.get("medications", [])]:
        order = Order(
            patient_id=patient_id,
            doctor_id=doctor_id,
            department="pharmacy",
            order_type=suggested_med.title(),
            details=f"AI-suggested medicine from image analysis: {suggested_med}",
            status="sent",
        )
        db.add(order)
        db.flush()
        rx = Prescription(
            order_id=order.order_id,
            medicine_name=suggested_med.title(),
            dosage="As directed",
            duration="As directed",
        )
        db.add(rx)
        created_orders.append({
            "order_id":   order.order_id,
            "department": "Pharmacy",
            "type":       suggested_med.title(),
            "status":     "Sent",
            "timestamp":  order.created_at.isoformat() if order.created_at else datetime.utcnow().isoformat(),
        })

    # ── Commit all changes ───────────────────────────────────
    db.commit()
    logger.info("Total orders created: %d", len(created_orders))
    return created_orders
