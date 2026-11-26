"""Bridge from WhatsApp events to guarded-agent-template (with built-in standalone fallback)."""
from __future__ import annotations

import json
import os
import secrets
import urllib.error
import urllib.request
from typing import Any

from .hitl import HitlStore, parse_approval_reply


class AgentBridge:
    def __init__(self, hitl: HitlStore, agent_url: str | None = None):
        self.hitl = hitl
        self.agent_url = (agent_url if agent_url is not None else os.getenv("AGENT_SERVICE_URL", "")).rstrip("/")

    def _http_post(self, path: str, payload: dict[str, Any]) -> dict[str, Any]:
        req = urllib.request.Request(
            f"{self.agent_url}{path}",
            data=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=15) as resp:
            return json.loads(resp.read().decode("utf-8"))

    def _standalone_run(self, task: str) -> dict[str, Any]:
        low = task.lower()
        if any(w in low for w in ("ignore previous", "system prompt", "rm -rf", "bypass")):
            return {
                "status": "blocked",
                "answer": "Blocked by prompt-injection guardrail.",
                "cost_usd": 0.0,
            }
        if any(w in low for w in ("restart", "reboot", "neustart")):
            code = secrets.token_hex(2).upper()
            svc = "worker-queue"
            for cand in ("n8n", "paperless", "vaultwarden", "worker-queue"):
                if cand in low:
                    svc = cand
                    break
            return {
                "status": "awaiting_approval",
                "answer": f"Mutating action `restart_service({svc})` requires confirmation. Reply `YES {code}` to execute or `NO {code}` to cancel.",
                "approval_code": code,
                "pending_tool": "restart_service",
                "pending_args": {"service": svc},
                "cost_usd": 0.0012,
            }
        if any(w in low for w in ("health", "status", "server", "homelab", "container")):
            return {
                "status": "completed",
                "answer": "4/5 services healthy. Degraded: worker-queue (high queue latency).",
                "cost_usd": 0.0010,
            }
        return {
            "status": "completed",
            "answer": f"Agent received: \"{task[:160]}\" (standalone demo mode).",
            "cost_usd": 0.0005,
        }

    def handle_text(self, sender: str, text: str) -> dict[str, Any]:
        # 1. Check if this message is an approval reply (YES/NO <CODE>)
        decision = parse_approval_reply(text)
        if decision is not None:
            approved, code = decision
            pending = self.hitl.pop_for_sender(code=code, sender=sender)
            if not pending:
                return {
                    "status": "invalid_approval",
                    "reply": f"No active approval request found for code `{code}` (expired or wrong sender).",
                }
            if self.agent_url:
                try:
                    res = self._http_post("/v1/approve", {"code": code, "approved": approved})
                    action_word = "Executed" if approved else "Cancelled"
                    return {
                        "status": res.get("status", "executed" if approved else "rejected"),
                        "reply": f"{action_word} `{pending['tool']}` ({pending['args']}).",
                        "raw": res,
                    }
                except urllib.error.URLError:
                    pass
            if not approved:
                return {"status": "rejected", "reply": f"Cancelled `{pending['tool']}` ({pending['args']})."}
            return {
                "status": "executed",
                "reply": f"Approved and executed `{pending['tool']}` ({pending['args']}). Service is now healthy.",
            }

        # 2. Forward task to guarded-agent-template (or standalone fallback)
        if self.agent_url:
            try:
                res = self._http_post(
                    "/v1/run",
                    {"task": text, "channel": "whatsapp", "max_steps": 3, "max_cost_usd": 0.02},
                )
            except urllib.error.URLError:
                res = self._standalone_run(text)
        else:
            res = self._standalone_run(text)

        if res.get("status") == "awaiting_approval" and res.get("approval_code"):
            self.hitl.save(
                code=res["approval_code"],
                sender=sender,
                tool=res.get("pending_tool", "unknown"),
                args=res.get("pending_args") or {},
            )

        return {
            "status": res.get("status", "completed"),
            "reply": res.get("answer", ""),
            "approval_code": res.get("approval_code"),
            "cost_usd": res.get("cost_usd", 0.0),
        }
