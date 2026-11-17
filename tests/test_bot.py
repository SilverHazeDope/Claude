import json
from types import SimpleNamespace
from zoneinfo import ZoneInfo

import pytest

from bot.analyzer import AnalysisError, FoodAnalyzer, parse_result
from bot.db import Database
from bot.formatting import format_analysis, format_day

GOOD = {
    "is_food": True,
    "dish_name": "Гречка с курицей",
    "items": [
        {"name": "Гречка", "grams": 150, "kcal": 190, "protein_g": 7, "fat_g": 2, "carbs_g": 37},
        {"name": "Куриная грудка", "grams": 100, "kcal": 165, "protein_g": 31, "fat_g": 4, "carbs_g": 0},
    ],
    "confidence": "medium",
    "comment": "Масло не видно <b>",
}


def test_totals_are_sums_of_items():
    a = parse_result(json.dumps(GOOD))
    assert a.kcal == 355
    assert a.protein_g == 38
    assert a.grams == 250


def test_parse_garbage_raises_user_friendly_error():
    with pytest.raises(AnalysisError):
        parse_result("not json")
    with pytest.raises(AnalysisError):
        parse_result(json.dumps({"is_food": True}))


def test_formatting_escapes_html_and_not_food():
    text = format_analysis(parse_result(json.dumps(GOOD)))
    assert "355 ккал" in text and "&lt;b&gt;" in text
    not_food = {**GOOD, "is_food": False, "items": []}
    assert "Не вижу" in format_analysis(parse_result(json.dumps(not_food)))


class FakeMessages:
    def __init__(self, response):
        self.response, self.kwargs = response, None

    async def create(self, **kwargs):
        self.kwargs = kwargs
        return self.response


def fake_client(response):
    msgs = FakeMessages(response)
    return SimpleNamespace(messages=msgs, beta=SimpleNamespace(messages=msgs)), msgs


def resp(text, stop="end_turn"):
    return SimpleNamespace(stop_reason=stop, content=[SimpleNamespace(type="text", text=text)])


async def test_analyze_sends_image_and_hint():
    client, msgs = fake_client(resp(json.dumps(GOOD)))
    result = await FoodAnalyzer("claude-opus-5-5", client).analyze(b"\xff\xd8jpeg", hint="200 г")
    assert result.dish_name == "Гречка с курицей"
    content = msgs.kwargs["messages"][0]["content"]
    assert content[0]["type"] == "image" and content[0]["source"]["media_type"] == "image/jpeg"
    assert "200 г" in content[1]["text"]
    assert msgs.kwargs["fallbacks"] == "default"


async def test_analyze_other_model_has_no_fallbacks():
    client, msgs = fake_client(resp(json.dumps(GOOD)))
    await FoodAnalyzer("claude-haiku-5-5", client).analyze(b"x")
    assert "fallbacks" not in msgs.kwargs


async def test_refusal_and_truncation():
    for stop in ("refusal", "max_tokens"):
        client, _ = fake_client(resp("{}", stop))
        with pytest.raises(AnalysisError):
            await FoodAnalyzer("claude-opus-5-5", client).analyze(b"x")


async def test_db_limit_save_undo_and_totals():
    db = Database(":memory:", ZoneInfo("Europe/Moscow"))
    a = await db.add_analysis(1, "Суп", 200, 10, 5, 20)
    b = await db.add_analysis(1, "Хлеб", 100, 3, 1, 20)
    await db.add_analysis(2, "Чужое", 999, 0, 0, 0)
    assert await db.analyses_today(1) == 2
    assert (await db.today_totals(1)).count == 0  # ничего ещё не сохранено
    assert await db.mark_saved(1, a) and await db.mark_saved(1, b)
    assert not await db.mark_saved(1, 3)  # чужая запись
    totals = await db.today_totals(1)
    assert totals.count == 2 and totals.kcal == 300
    assert await db.undo_last_saved(1) == "Хлеб"
    entries = await db.today_entries(1)
    assert entries == [("Суп", 200)]
    assert "Суп" in format_day(entries, await db.today_totals(1))
