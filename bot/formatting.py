"""Оформление сообщений для Telegram (HTML-разметка)."""
from __future__ import annotations

from html import escape

from .analyzer import Analysis
from .db import DayTotals

_CONFIDENCE = {
    "high": "🟢 высокая",
    "medium": "🟡 средняя",
    "low": "🔴 низкая",
}


def _n(value: float) -> str:
    return f"{round(value):d}"


def _g(value: float) -> str:
    return f"{value:.0f}"


def format_analysis(a: Analysis) -> str:
    if not a.is_food or not a.items:
        return "🤔 Не вижу на фото еды. Пришли фото блюда — попробуем ещё раз."

    lines = [f"🍽 <b>{escape(a.dish_name)}</b>", ""]
    for i in a.items:
        lines.append(
            f"• {escape(i.name)} — {_g(i.grams)} г\n"
            f"   {_n(i.kcal)} ккал · Б {_g(i.protein_g)} · Ж {_g(i.fat_g)} · У {_g(i.carbs_g)}"
        )
    lines += [
        "",
        f"<b>Итого (~{_g(a.grams)} г)</b>",
        f"🔥 Калории: <b>{_n(a.kcal)} ккал</b>",
        f"🥩 Белки: <b>{_g(a.protein_g)} г</b>",
        f"🧈 Жиры: <b>{_g(a.fat_g)} г</b>",
        f"🍞 Углеводы: <b>{_g(a.carbs_g)} г</b>",
        "",
        f"Уверенность оценки: {_CONFIDENCE[a.confidence]}",
    ]
    if a.comment:
        lines.append(f"💬 {escape(a.comment)}")
    lines += ["", "<i>Оценка приблизительная — по фото точный вес не определить.</i>"]
    return "\n".join(lines)


def format_day(entries: list[tuple[str, float]], totals: DayTotals) -> str:
    if not entries:
        return "📒 Сегодня в дневнике пока пусто. Пришли фото еды и нажми «Сохранить в дневник»."
    lines = ["📒 <b>Дневник за сегодня</b>", ""]
    for n, (dish, kcal) in enumerate(entries, 1):
        lines.append(f"{n}. {escape(dish)} — {_n(kcal)} ккал")
    lines += [
        "",
        f"🔥 Всего: <b>{_n(totals.kcal)} ккал</b>",
        f"🥩 Белки: {_g(totals.protein)} г · 🧈 Жиры: {_g(totals.fat)} г · 🍞 Углеводы: {_g(totals.carbs)} г",
    ]
    return "\n".join(lines)
