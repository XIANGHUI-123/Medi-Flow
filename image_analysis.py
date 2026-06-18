"""
image_analysis.py  ─  Patient image analysis for symptom detection.

Workflow:
  1.  Accept an uploaded image (JPEG / PNG).
  2.  Generate a textual description of the image using basic CV heuristics.
  3.  Send the description to the AI service for medical triage.

For the MVP the "vision" step is a lightweight colour / texture analysis
combined with an AI prompt.  A production system would use a dedicated
medical vision model.

Public API:
    analyze_patient_image(image_bytes, filename) -> dict
"""

import io
import base64
import logging

from PIL import Image
from ai_service import analyze_image_description

logger = logging.getLogger(__name__)


async def analyze_patient_image(image_bytes: bytes, filename: str = "image.jpg") -> dict:
    """
    Analyze a patient‑uploaded image for visible symptoms.

    Returns a dict:
        symptom            – e.g. "possible skin infection"
        confidence         – 0.0 … 1.0
        suggested_test     – e.g. "blood test"
        suggested_medicine – e.g. "antibiotic cream"
    """
    try:
        # ── Open and validate the image ──────────────────────
        img = Image.open(io.BytesIO(image_bytes))
        img.verify()                         # ensure it's a valid image
        img = Image.open(io.BytesIO(image_bytes))  # re‑open after verify

        # ── Build a textual description for the AI ───────────
        width, height = img.size
        mode = img.mode
        description = _build_image_description(img)

        # ── Encode to base64 for potential vision API use ────
        b64_image = base64.b64encode(image_bytes).decode()

        # Compose a prompt with the image metadata + description
        prompt = (
            f"I have a patient photo ({width}x{height}, {mode} mode). "
            f"Visual analysis: {description}. "
            f"The image file is named '{filename}'. "
            "Based on this, estimate the most likely visible symptom, "
            "confidence, suggested lab test, and suggested medicine."
        )

        # ── Delegate to AI service ───────────────────────────
        result = await analyze_image_description(prompt)
        logger.info("Image analysis complete for %s", filename)
        return result

    except Exception as exc:
        logger.error("Image analysis failed: %s", exc, exc_info=True)
        return {
            "symptom": "analysis error",
            "confidence": 0.0,
            "suggested_test": "general examination",
            "suggested_medicine": "consult doctor",
        }


# ─────────────────────────────────────────────────────────────
# Internal helpers
# ─────────────────────────────────────────────────────────────
def _build_image_description(img: Image.Image) -> str:
    """
    Produce a short textual description of the image based on
    simple colour‑distribution heuristics.

    This is a lightweight proxy – a real system would use a
    medical‑grade vision model.
    """
    # Resize for fast processing
    thumb = img.copy()
    thumb.thumbnail((100, 100))
    if thumb.mode != "RGB":
        thumb = thumb.convert("RGB")

    pixels = list(thumb.getdata())
    total = len(pixels) if pixels else 1

    # Count pixels in broad colour buckets
    red_count = sum(1 for r, g, b in pixels if r > 150 and g < 100 and b < 100)
    pink_count = sum(1 for r, g, b in pixels if r > 180 and g < 160 and b > 150)
    dark_count = sum(1 for r, g, b in pixels if r < 60 and g < 60 and b < 60)
    yellow_count = sum(1 for r, g, b in pixels if r > 180 and g > 160 and b < 80)

    parts = []
    if red_count / total > 0.15:
        parts.append("significant redness detected (possible inflammation or rash)")
    if pink_count / total > 0.10:
        parts.append("pinkish areas noted (possible irritation)")
    if dark_count / total > 0.20:
        parts.append("dark patches present (possible bruising or necrosis)")
    if yellow_count / total > 0.10:
        parts.append("yellowish areas detected (possible infection or jaundice sign)")

    if not parts:
        parts.append("no strong colour anomalies detected; general skin appearance")

    return "; ".join(parts)
