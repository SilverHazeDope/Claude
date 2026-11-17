"""Простое хранилище на SQLite: журнал анализов и дневник питания."""
from __future__ import annotations

import asyncio
import os
import sqlite3
from dataclasses import dataclass
from datetime import datetime
from zoneinfo import ZoneInfo

_SCHEMA = """
CREATE TABLE IF NOT EXISTS analyses (
    id        INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id   INTEGER NOT NULL,
    day       TEXT NOT NULL,          -- YYYY-MM-DD в часовом поясе бота
    created   TEXT NOT NULL,
    dish      TEXT NOT NULL,
    kcal      REAL NOT NULL,
    protein   REAL NOT NULL,
    fat       REAL NOT NULL,
    carbs     REAL NOT NULL,
    saved     INTEGER NOT NULL DEFAULT 0
);
CREATE INDEX IF NOT EXISTS idx_analyses_user_day ON analyses (user_id, day);
"""


@dataclass(frozen=True)
class DayTotals:
    count: int
    kcal: float
    protein: float
    fat: float
    carbs: float


class Database:
    def __init__(self, path: str, tz: ZoneInfo) -> None:
        self.tz = tz
        if path != ":memory:":
            os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
        self._conn = sqlite3.connect(path, check_same_thread=False)
        self._conn.executescript(_SCHEMA)
        self._lock = asyncio.Lock()

    def _now(self) -> datetime:
        return datetime.now(self.tz)

    def _today(self) -> str:
        return self._now().strftime("%Y-%m-%d")

    async def _run(self, fn):
        async with self._lock:
            return await asyncio.to_thread(fn)

    async def analyses_today(self, user_id: int) -> int:
        """Сколько анализов пользователь сделал сегодня (для лимита)."""
        def q() -> int:
            row = self._conn.execute(
                "SELECT COUNT(*) FROM analyses WHERE user_id=? AND day=?", (user_id, self._today())
            ).fetchone()
            return row[0]
        return await self._run(q)

    async def add_analysis(self, user_id: int, dish: str, kcal: float, protein: float, fat: float, carbs: float) -> int:
        def q() -> int:
            cur = self._conn.execute(
                "INSERT INTO analyses (user_id, day, created, dish, kcal, protein, fat, carbs) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (user_id, self._today(), self._now().isoformat(), dish, kcal, protein, fat, carbs),
            )
            self._conn.commit()
            return int(cur.lastrowid)
        return await self._run(q)

    async def mark_saved(self, user_id: int, analysis_id: int) -> bool:
        """Сохранить анализ в дневник. False — если записи нет (или она чужая)."""
        def q() -> bool:
            cur = self._conn.execute(
                "UPDATE analyses SET saved=1 WHERE id=? AND user_id=?", (analysis_id, user_id)
            )
            self._conn.commit()
            return cur.rowcount > 0
        return await self._run(q)

    async def undo_last_saved(self, user_id: int) -> str | None:
        """Убрать из дневника последнюю сохранённую запись за сегодня. Возвращает её название."""
        def q() -> str | None:
            row = self._conn.execute(
                "SELECT id, dish FROM analyses WHERE user_id=? AND day=? AND saved=1 ORDER BY id DESC LIMIT 1",
                (user_id, self._today()),
            ).fetchone()
            if row is None:
                return None
            self._conn.execute("UPDATE analyses SET saved=0 WHERE id=?", (row[0],))
            self._conn.commit()
            return row[1]
        return await self._run(q)

    async def today_entries(self, user_id: int) -> list[tuple[str, float]]:
        def q() -> list[tuple[str, float]]:
            rows = self._conn.execute(
                "SELECT dish, kcal FROM analyses WHERE user_id=? AND day=? AND saved=1 ORDER BY id",
                (user_id, self._today()),
            ).fetchall()
            return [(r[0], r[1]) for r in rows]
        return await self._run(q)

    async def today_totals(self, user_id: int) -> DayTotals:
        def q() -> DayTotals:
            row = self._conn.execute(
                "SELECT COUNT(*), COALESCE(SUM(kcal),0), COALESCE(SUM(protein),0), "
                "COALESCE(SUM(fat),0), COALESCE(SUM(carbs),0) "
                "FROM analyses WHERE user_id=? AND day=? AND saved=1",
                (user_id, self._today()),
            ).fetchone()
            return DayTotals(*row)
        return await self._run(q)
