"""Multimodal intake adapter: WhatsApp voice notes -> text.

- Real mode (GROQ_API_KEY or STT_API_KEY set): audio goes to an OpenAI-compatible speech-to-text endpoint
  (default Groq `whisper-large-v3-turbo`). WhatsApp media is fetched from the Graph API with WHATSAPP_TOKEN.
- Demo/CI mode (no key, or a simulated transcript given): returns the simulated transcript so the pipeline runs offline.
"""
from __future__ import annotations

import json
import os
import time
import urllib.request
import uuid
from typing import Any

GRAPH = "https://graph.facebook.com/v21.0"
MAX_AUDIO_BYTES = 8 * 1024 * 1024


def _stt_key() -> str:
    return (os.getenv("STT_API_KEY") or os.getenv("GROQ_API_KEY") or "").strip()


def transcribe_audio_bytes(data: bytes, mime: str = "audio/ogg", filename: str = "voice.ogg") -> dict[str, Any]:
    """Send audio bytes to the speech-to-text API (multipart, stdlib only). Raises on network/API errors."""
    if len(data) > MAX_AUDIO_BYTES:
        raise ValueError("audio too large")
    base = os.getenv("STT_BASE_URL", "https://api.groq.com/openai/v1").rstrip("/")
    model = os.getenv("STT_MODEL", "whisper-large-v3-turbo")
    boundary = uuid.uuid4().hex
    parts = [
        f'--{boundary}\r\nContent-Disposition: form-data; name="model"\r\n\r\n{model}\r\n'.encode(),
        f'--{boundary}\r\nContent-Disposition: form-data; name="response_format"\r\n\r\njson\r\n'.encode(),
        f'--{boundary}\r\nContent-Disposition: form-data; name="file"; filename="{filename}"\r\nContent-Type: {mime}\r\n\r\n'.encode(),
        data, f"\r\n--{boundary}--\r\n".encode(),
    ]
    req = urllib.request.Request(
        f"{base}/audio/transcriptions", data=b"".join(parts), method="POST",
        headers={"Authorization": f"Bearer {_stt_key()}", "Content-Type": f"multipart/form-data; boundary={boundary}",
                 "User-Agent": "whatsapp-agent-kit/1.1"},
    )
    t0 = time.perf_counter()
    with urllib.request.urlopen(req, timeout=30) as resp:
        out = json.loads(resp.read().decode())
    return {"provider": f"stt:{model}", "transcript": (out.get("text") or "").strip(),
            "stt_ms": int((time.perf_counter() - t0) * 1000)}


def fetch_whatsapp_media(media_id: str) -> tuple[bytes, str]:
    """Download a WhatsApp media object (2 calls: metadata -> signed URL)."""
    token = os.getenv("WHATSAPP_TOKEN", "").strip()
    hdr = {"Authorization": f"Bearer {token}", "User-Agent": "whatsapp-agent-kit/1.1"}
    with urllib.request.urlopen(urllib.request.Request(f"{GRAPH}/{media_id}", headers=hdr), timeout=15) as r:
        meta = json.loads(r.read().decode())
    with urllib.request.urlopen(urllib.request.Request(meta["url"], headers=hdr), timeout=30) as r:
        return r.read(MAX_AUDIO_BYTES + 1), meta.get("mime_type", "audio/ogg")


def transcribe_voice_note(media_id: str, simulated_transcript: str | None = None) -> dict[str, Any]:
    """Transcribe a WhatsApp voice note; falls back to the simulated/demo transcript without credentials."""
    if simulated_transcript is None and _stt_key() and os.getenv("WHATSAPP_TOKEN", "").strip():
        data, mime = fetch_whatsapp_media(media_id)
        return {"media_id": media_id, **transcribe_audio_bytes(data, mime=mime.split(";")[0])}
    text = (simulated_transcript or "").strip() or "Check homelab container health status"
    return {"media_id": media_id, "provider": "mock-whisper", "transcript": text}


def send_text(to: str, body: str) -> bool:
    """Reply on WhatsApp (Cloud API). No-op (False) unless WHATSAPP_TOKEN and WHATSAPP_PHONE_NUMBER_ID are set."""
    token, phone_id = os.getenv("WHATSAPP_TOKEN", "").strip(), os.getenv("WHATSAPP_PHONE_NUMBER_ID", "").strip()
    if not (token and phone_id and to):
        return False
    payload = {"messaging_product": "whatsapp", "to": to.lstrip("+"), "type": "text", "text": {"body": body[:4000]}}
    req = urllib.request.Request(
        f"{GRAPH}/{phone_id}/messages", data=json.dumps(payload).encode(), method="POST",
        headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json", "User-Agent": "whatsapp-agent-kit/1.1"},
    )
    with urllib.request.urlopen(req, timeout=15) as r:
        return 200 <= r.status < 300
