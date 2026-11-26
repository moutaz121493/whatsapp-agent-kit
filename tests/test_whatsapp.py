"""Unit and integration tests for whatsapp-agent-kit."""
from __future__ import annotations

import hashlib
import hmac
import json

from fastapi.testclient import TestClient

from app.main import APP_SECRET, VERIFY_TOKEN, app

client = TestClient(app)


def _sign(body: bytes) -> str:
    return "sha256=" + hmac.new(APP_SECRET.encode(), body, hashlib.sha256).hexdigest()


def test_webhook_challenge_verification() -> None:
    r = client.get(
        "/webhook/whatsapp",
        params={"hub.mode": "subscribe", "hub.verify_token": VERIFY_TOKEN, "hub.challenge": "12345"},
    )
    assert r.status_code == 200
    assert r.text == "12345"


def test_webhook_rejects_bad_signature() -> None:
    r = client.post("/webhook/whatsapp", content=b"{}", headers={"X-Hub-Signature-256": "sha256=deadbeef"})
    assert r.status_code == 403


def test_webhook_allowlist_and_hitl_flow() -> None:
    payload = {
        "entry": [
            {
                "changes": [
                    {
                        "value": {
                            "messages": [
                                {"from": "+491700000001", "type": "text", "text": {"body": "Restart worker-queue"}},
                                {"from": "+491709999999", "type": "text", "text": {"body": "Check status"}},
                            ]
                        }
                    }
                ]
            }
        ]
    }
    raw = json.dumps(payload).encode()
    r = client.post("/webhook/whatsapp", content=raw, headers={"X-Hub-Signature-256": _sign(raw)})
    assert r.status_code == 200
    data = r.json()
    assert data["processed"] == 2
    assert data["outcomes"][0]["status"] == "awaiting_approval"
    assert data["outcomes"][1]["status"] == "denied_not_allowlisted"

    code = data["outcomes"][0]["approval_code"]
    r2 = client.post("/demo/send", json={"sender": "+491700000001", "kind": "text", "text": f"YES {code}"})
    assert r2.status_code == 200
    assert r2.json()["status"] == "executed"


def test_voice_note_demo_endpoint() -> None:
    r = client.post(
        "/demo/send",
        json={"sender": "+491700000001", "kind": "voice", "text": "Check homelab container health"},
    )
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "completed"
    assert "transcript" in body
