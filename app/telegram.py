"""Telegram channel: long-polling bot (outbound HTTPS only, nothing exposed to the internet).

TELEGRAM_BOT_TOKEN     token from @BotFather (channel is off without it)
TELEGRAM_ALLOWED_IDS   comma-separated numeric Telegram user IDs; anyone else is refused and told their ID
Text and voice notes go through the same AgentBridge (prompt-injection screen, HITL `YES <CODE>`, budget caps).
With VOICE_REPLIES=1 a voice note also gets a spoken answer (Orpheus TTS -> OGG/Opus voice note).
"""
from __future__ import annotations

import json
import logging
import os
import threading
import time
import urllib.request
import uuid
from pathlib import Path
from typing import Any, Callable

log = logging.getLogger("whatsapp-agent-kit.telegram")
API = "https://api.telegram.org"


def allowed_ids() -> set[int]:
    return {int(x) for x in os.getenv("TELEGRAM_ALLOWED_IDS", "").replace(" ", "").split(",") if x.strip().lstrip("-").isdigit()}


class TelegramBot:
    def __init__(self, token: str, handle_text: Callable[[str, str], dict[str, Any]],
                 transcribe: Callable[[bytes, str, str], dict[str, Any]] | None = None,
                 speak: Callable[[str], bytes] | None = None, offset_file: str | Path = "/data/tg_offset"):
        self.token, self.handle_text, self.transcribe, self.speak = token, handle_text, transcribe, speak
        self.offset_file = Path(offset_file)
        self.offset = int(self.offset_file.read_text()) if self.offset_file.exists() else 0
        self.stop = threading.Event()

    # ---- Bot API helpers (stdlib only) ----
    def call(self, method: str, payload: dict[str, Any] | None = None, timeout: int = 20) -> Any:
        req = urllib.request.Request(f"{API}/bot{self.token}/{method}", data=json.dumps(payload or {}).encode(),
                                     headers={"Content-Type": "application/json"}, method="POST")
        with urllib.request.urlopen(req, timeout=timeout) as r:
            out = json.loads(r.read().decode())
        if not out.get("ok"):
            raise RuntimeError(out.get("description", "telegram error"))
        return out["result"]

    def download(self, file_id: str) -> bytes:
        path = self.call("getFile", {"file_id": file_id})["file_path"]
        with urllib.request.urlopen(f"{API}/file/bot{self.token}/{path}", timeout=30) as r:
            return r.read(8 * 1024 * 1024 + 1)

    def send_text(self, chat_id: int, text: str) -> None:
        self.call("sendMessage", {"chat_id": chat_id, "text": text[:4000] or "…"})

    def send_voice(self, chat_id: int, ogg: bytes) -> None:
        b = uuid.uuid4().hex
        body = b"".join([
            f'--{b}\r\nContent-Disposition: form-data; name="chat_id"\r\n\r\n{chat_id}\r\n'.encode(),
            f'--{b}\r\nContent-Disposition: form-data; name="voice"; filename="reply.ogg"\r\nContent-Type: audio/ogg\r\n\r\n'.encode(),
            ogg, f"\r\n--{b}--\r\n".encode()])
        req = urllib.request.Request(f"{API}/bot{self.token}/sendVoice", data=body, method="POST",
                                     headers={"Content-Type": f"multipart/form-data; boundary={b}"})
        urllib.request.urlopen(req, timeout=30).read()

    # ---- one update ----
    def handle_update(self, upd: dict[str, Any]) -> dict[str, Any] | None:
        msg = upd.get("message") or {}
        chat, user = msg.get("chat", {}), msg.get("from", {})
        if not msg or chat.get("type") != "private":
            return None   # ignore groups/channels entirely
        uid, chat_id = user.get("id"), chat.get("id")
        if uid not in allowed_ids():
            self.send_text(chat_id, f"Sorry, this is a private assistant. Your Telegram ID is {uid}.")
            log.warning("refused telegram user %s", uid)
            return {"status": "denied", "user": uid}
        voice = msg.get("voice") or msg.get("audio")
        if voice:
            if not self.transcribe:
                self.send_text(chat_id, "Voice notes are not enabled here; please type.")
                return {"status": "no_stt"}
            try:
                tr = self.transcribe(self.download(voice["file_id"]), voice.get("mime_type", "audio/ogg"), "voice.ogg")
            except Exception as exc:
                log.warning("telegram voice failed: %s", type(exc).__name__)
                self.send_text(chat_id, "Sorry, I couldn't understand that voice note. Please try again or type it.")
                return {"status": "stt_failed"}
            text = tr["transcript"]
            self.send_text(chat_id, f"🎙 {text}")
        else:
            text = (msg.get("text") or "").strip()
            if not text:
                return None
            if text in ("/start", "/help"):
                self.send_text(chat_id, "Hi! Ask me about the Pi by text or voice note, in English, German or Arabic. Changes need YES <CODE>.")
                return {"status": "help"}
        res = self.handle_text(f"tg:{uid}", text)
        self.send_text(chat_id, res.get("reply", ""))
        if voice and self.speak and res.get("reply"):
            try:
                self.send_voice(chat_id, self.speak(res["reply"]))
            except Exception as exc:   # text already sent, nothing is lost
                log.warning("telegram voice reply failed: %s", type(exc).__name__)
        return res

    # ---- long polling loop ----
    def run(self) -> None:
        try:
            self.call("deleteWebhook", {"drop_pending_updates": False})
        except Exception:
            pass
        backoff = 1
        while not self.stop.is_set():
            try:
                updates = self.call("getUpdates", {"offset": self.offset, "timeout": 50, "allowed_updates": ["message"]}, timeout=65)
                backoff = 1
            except Exception as exc:
                log.warning("telegram poll error: %s", type(exc).__name__)
                self.stop.wait(backoff); backoff = min(backoff * 2, 60)
                continue
            for upd in updates:
                self.offset = upd["update_id"] + 1
                try:
                    self.offset_file.write_text(str(self.offset))
                except OSError:
                    pass
                try:
                    self.handle_update(upd)
                except Exception as exc:
                    log.warning("telegram update failed: %s", type(exc).__name__)

    def start(self) -> threading.Thread:
        t = threading.Thread(target=self.run, name="telegram-poll", daemon=True)
        t.start()
        return t
