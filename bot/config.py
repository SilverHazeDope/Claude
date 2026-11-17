"""Настройки бота. Всё берётся из переменных окружения (файл .env)."""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from zoneinfo import ZoneInfo

from dotenv import load_dotenv

load_dotenv()


def _parse_ids(raw: str) -> frozenset[int]:
    return frozenset(int(x) for x in raw.replace(" ", "").split(",") if x)


@dataclass(frozen=True)
class Config:
    telegram_token: str
    anthropic_model: str = "claude-opus-5-5"
    # Пустой список = бот открыт для всех. Рекомендуется заполнить!
    allowed_user_ids: frozenset[int] = field(default_factory=frozenset)
    # Сколько фото в сутки может проанализировать один человек (защита от трат).
    daily_limit: int = 30
    timezone: ZoneInfo = ZoneInfo("Europe/Moscow")
    db_path: str = "data/bot.db"


def load_config() -> Config:
    token = os.environ.get("TELEGRAM_BOT_TOKEN", "").strip()
    if not token:
        raise SystemExit("Не задан TELEGRAM_BOT_TOKEN (см. README, шаг 1).")
    if not os.environ.get("ANTHROPIC_API_KEY", "").strip():
        raise SystemExit("Не задан ANTHROPIC_API_KEY (см. README, шаг 2).")
    return Config(
        telegram_token=token,
        anthropic_model=os.environ.get("CLAUDE_MODEL", "claude-opus-5-5").strip(),
        allowed_user_ids=_parse_ids(os.environ.get("ALLOWED_USER_IDS", "")),
        daily_limit=int(os.environ.get("DAILY_LIMIT", "30")),
        timezone=ZoneInfo(os.environ.get("TIMEZONE", "Europe/Moscow")),
        db_path=os.environ.get("DB_PATH", "data/bot.db"),
    )
