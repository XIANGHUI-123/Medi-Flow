"""
speech_service.py  ─  Speech‑to‑text conversion.

Uses the ``SpeechRecognition`` library with Google's free Web Speech API
for the MVP.  Accepts common audio formats (WAV, MP3, FLAC, OGG, WEBM)
and converts them to WAV via *pydub* when necessary.

Public API:
    transcribe_audio(audio_bytes, filename, language) -> str
"""

import io
import os
import tempfile
import logging

import speech_recognition as sr
from pydub import AudioSegment

logger = logging.getLogger(__name__)

# Recognised file extensions and their pydub format names
_FORMAT_MAP = {
    ".wav":  "wav",
    ".mp3":  "mp3",
    ".flac": "flac",
    ".ogg":  "ogg",
    ".webm": "webm",
    ".m4a":  "mp4",   # pydub treats m4a as mp4
    ".wma":  "wma",
}

# Supported languages for Google Web Speech API
SUPPORTED_LANGUAGES = {
    "auto":    None,        # auto-detect (default)
    "en":      "en-US",
    "ms":      "ms-MY",     # Malay
    "zh":      "zh-CN",     # Mandarin Chinese
    "ta":      "ta-IN",     # Tamil
    "ar":      "ar-SA",     # Arabic
    "hi":      "hi-IN",     # Hindi
    "id":      "id-ID",     # Indonesian
    "ja":      "ja-JP",     # Japanese
    "ko":      "ko-KR",     # Korean
    "th":      "th-TH",     # Thai
}


def transcribe_audio(
    audio_bytes: bytes,
    filename: str = "audio.wav",
    language: str = "auto",
) -> str:
    """
    Convert spoken audio to text.

    Parameters
    ----------
    audio_bytes : bytes
        Raw bytes of the uploaded audio file.
    filename : str
        Original filename (used to detect format from extension).
    language : str
        Language code hint (e.g. "en", "ms", "zh", "auto").
        When "auto", Google will attempt to detect the language.

    Returns
    -------
    str
        The transcribed text, or an error message prefixed with ``[ERROR]``.
    """
    ext = os.path.splitext(filename)[1].lower()
    fmt = _FORMAT_MAP.get(ext, "wav")

    # Resolve the language code for Google Web Speech API
    lang_code = SUPPORTED_LANGUAGES.get(language)

    try:
        # ── Convert to WAV if not already ────────────────────
        audio_segment = AudioSegment.from_file(io.BytesIO(audio_bytes), format=fmt)
        wav_buffer = io.BytesIO()
        audio_segment.export(wav_buffer, format="wav")
        wav_buffer.seek(0)

        # ── Recognise speech ─────────────────────────────────
        recognizer = sr.Recognizer()
        with sr.AudioFile(wav_buffer) as source:
            audio_data = recognizer.record(source)

        # Using Google Web Speech API (free, no key needed for MVP)
        if lang_code:
            text = recognizer.recognize_google(audio_data, language=lang_code)
        else:
            text = recognizer.recognize_google(audio_data)
        logger.info("Transcription successful (%d chars, lang=%s)", len(text), language)
        return text

    except sr.UnknownValueError:
        msg = "Speech was not clear enough to transcribe."
        logger.warning(msg)
        return f"[ERROR] {msg}"

    except sr.RequestError as exc:
        msg = f"Speech recognition service unavailable: {exc}"
        logger.error(msg)
        return f"[ERROR] {msg}"

    except Exception as exc:
        msg = f"Audio processing failed: {exc}"
        logger.error(msg, exc_info=True)
        return f"[ERROR] {msg}"
