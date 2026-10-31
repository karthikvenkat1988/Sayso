"""Local dictation history in SQLite. Text only; audio is never stored. Off switch and retention in settings."""

from __future__ import annotations

import sqlite3
import threading
import time
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class HistoryItem:
    id: int
    created: float
    app: str
    mode: str
    transcript: str
    text: str
    stt_engine: str
    llm_provider: str
    latency_ms: int
    confidence: float | None


class History:
    def __init__(self, path: Path | str, enabled: bool = True, retention_days: int = 30):
        self.enabled = enabled
        self.retention_days = retention_days
        self._lock = threading.Lock()
        self._db = sqlite3.connect(str(path), check_same_thread=False)
        self._db.execute(
            """CREATE TABLE IF NOT EXISTS history (
                id INTEGER PRIMARY KEY AUTOINCREMENT, created REAL NOT NULL, app TEXT, mode TEXT,
                transcript TEXT, text TEXT, stt_engine TEXT, llm_provider TEXT, latency_ms INTEGER, confidence REAL)"""
        )
        self._db.commit()
        self.prune()

    def add(self, *, app: str, mode: str, transcript: str, text: str, stt_engine: str, llm_provider: str,
            latency_ms: int, confidence: float | None) -> int | None:
        if not self.enabled:
            return None
        with self._lock:
            cur = self._db.execute(
                "INSERT INTO history (created, app, mode, transcript, text, stt_engine, llm_provider, latency_ms, confidence)"
                " VALUES (?,?,?,?,?,?,?,?,?)",
                (time.time(), app, mode, transcript, text, stt_engine, llm_provider, latency_ms, confidence),
            )
            self._db.commit()
            return cur.lastrowid

    def recent(self, limit: int = 200, query: str = "") -> list[HistoryItem]:
        sql = "SELECT * FROM history"
        args: tuple = ()
        if query:
            sql += " WHERE text LIKE ? OR transcript LIKE ? OR app LIKE ?"
            like = f"%{query}%"
            args = (like, like, like)
        sql += " ORDER BY created DESC LIMIT ?"
        with self._lock:
            rows = self._db.execute(sql, (*args, limit)).fetchall()
        return [HistoryItem(*r) for r in rows]

    def delete(self, item_id: int) -> None:
        with self._lock:
            self._db.execute("DELETE FROM history WHERE id=?", (item_id,))
            self._db.commit()

    def clear(self) -> None:
        with self._lock:
            self._db.execute("DELETE FROM history")
            self._db.commit()
            self._db.execute("VACUUM")

    def prune(self) -> None:
        if self.retention_days <= 0:
            return
        cutoff = time.time() - self.retention_days * 86400
        with self._lock:
            self._db.execute("DELETE FROM history WHERE created < ?", (cutoff,))
            self._db.commit()

    def close(self) -> None:
        self._db.close()
