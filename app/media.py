"""Multimodal intake adapter (voice notes & images) with offline mock transcription for demos."""
from __future__ import annotations

from typing import Any


def transcribe_voice_note(media_id: str, simulated_transcript: str | None = None) -> dict[str, Any]:
    """Transcribe a WhatsApp voice note.

    In production, fetch the OGG/Opus media URL via Meta Graph API and pass it to Whisper/Gemini.
    In demo/CI mode, returns the simulated transcript cleanly so the full pipeline runs offline.
    """
    text = (simulated_transcript or "").strip() or "Check homelab container health status"
    return {
        "media_id": media_id,
        "provider": "mock-whisper",
        "transcript": text,
    }
