"""SQLite-backed Human-in-the-Loop (HITL) approval store with expiry TTL."""
from __future__ import annotations

import json
import re
import sqlite3
import time
from pathlib import Path
from typing import Any

APPROVAL_RE = re.compile(r"^\s*(yes|no|approve|reject|ja|nein|نعم|لا)\s+([A-Za-z0-9]{4,12})\s*$", re.I)


def parse_approval_reply(text: str) -> tuple[bool, str] | None:
    m = APPROVAL_RE.match(text or "")
    if not m:
        return None
    verb = m.group(1).lower()
    code = m.group(2).upper()
    approved = verb in ("yes", "approve", "ja", "نعم")
    return approved, code


class HitlStore:
    def __init__(self, db_path: str | Path, ttl_seconds: int = 300):
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self.ttl_seconds = ttl_seconds
        self._init_db()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path, timeout=10.0)
        conn.row_factory = sqlite3.Row
        return conn

    def _init_db(self) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS pending_approvals (
                    code TEXT PRIMARY KEY,
                    sender TEXT NOT NULL,
                    tool TEXT NOT NULL,
                    args_json TEXT NOT NULL,
                    expires_at REAL NOT NULL
                )
                """
            )

    def save(self, code: str, sender: str, tool: str, args: dict[str, Any]) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                INSERT OR REPLACE INTO pending_approvals (code, sender, tool, args_json, expires_at)
                VALUES (?, ?, ?, ?, ?)
                """,
                (code.upper(), sender, tool, json.dumps(args), time.time() + self.ttl_seconds),
            )

    def pop_for_sender(self, code: str, sender: str) -> dict[str, Any] | None:
        now = time.time()
        with self._connect() as conn:
            conn.execute("DELETE FROM pending_approvals WHERE expires_at < ?", (now,))
            row = conn.execute(
                "SELECT * FROM pending_approvals WHERE code = ? AND sender = ?",
                (code.upper(), sender),
            ).fetchone()
            if not row:
                return None
            conn.execute("DELETE FROM pending_approvals WHERE code = ?", (code.upper(),))
            return {
                "code": row["code"],
                "sender": row["sender"],
                "tool": row["tool"],
                "args": json.loads(row["args_json"]),
            }
