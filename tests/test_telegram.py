"""Telegram channel: allowlist, text, voice (STT + spoken reply), group messages ignored."""
from __future__ import annotations

from app.telegram import TelegramBot


class FakeBot(TelegramBot):
    def __init__(self, tmp_path, **kw):
        super().__init__("T", offset_file=tmp_path / "off", **kw)
        self.sent, self.voices = [], []
    def call(self, method, payload=None, timeout=20):
        if method == "sendMessage":
            self.sent.append(payload["text"]); return {}
        if method == "getFile":
            return {"file_path": "voice/1.oga"}
        return {}
    def download(self, file_id):
        return b"OggS-fake"
    def send_voice(self, chat_id, ogg):
        self.voices.append(ogg)


def _upd(uid, **msg):
    return {"update_id": 1, "message": {"chat": {"id": uid, "type": "private"}, "from": {"id": uid}, **msg}}


def test_unknown_user_is_refused_and_told_id(tmp_path, monkeypatch):
    monkeypatch.setenv("TELEGRAM_ALLOWED_IDS", "111")
    bot = FakeBot(tmp_path, handle_text=lambda s, t: {"reply": "x"})
    assert bot.handle_update(_upd(222, text="hi"))["status"] == "denied"
    assert "222" in bot.sent[0]


def test_text_goes_through_bridge(tmp_path, monkeypatch):
    monkeypatch.setenv("TELEGRAM_ALLOWED_IDS", "111")
    seen = {}
    bot = FakeBot(tmp_path, handle_text=lambda s, t: seen.update(s=s, t=t) or {"reply": "All good"})
    bot.handle_update(_upd(111, text="status?"))
    assert seen == {"s": "tg:111", "t": "status?"} and bot.sent == ["All good"]


def test_voice_note_transcribed_and_spoken_reply(tmp_path, monkeypatch):
    monkeypatch.setenv("TELEGRAM_ALLOWED_IDS", "111")
    bot = FakeBot(tmp_path, handle_text=lambda s, t: {"reply": "Paperless is healthy"},
                  transcribe=lambda d, m, n: {"transcript": "is paperless ok"}, speak=lambda text: b"OggS-reply")
    bot.handle_update(_upd(111, voice={"file_id": "f1", "mime_type": "audio/ogg"}))
    assert bot.sent == ["🎙 is paperless ok", "Paperless is healthy"] and bot.voices == [b"OggS-reply"]


def test_group_messages_ignored(tmp_path, monkeypatch):
    monkeypatch.setenv("TELEGRAM_ALLOWED_IDS", "111")
    bot = FakeBot(tmp_path, handle_text=lambda s, t: {"reply": "x"})
    assert bot.handle_update({"update_id": 2, "message": {"chat": {"id": -5, "type": "group"}, "from": {"id": 111}, "text": "hi"}}) is None
