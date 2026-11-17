"""Анализ фото еды через Claude: фото -> блюда, граммовки и КБЖУ."""
from __future__ import annotations

import base64
import json
from dataclasses import dataclass

import anthropic

SYSTEM_PROMPT = """\
Ты — нутрициолог-аналитик. По фотографии еды ты оцениваешь состав блюда и КБЖУ \
(калории, белки, жиры, углеводы).

Правила:
- Раздели блюдо на отдельные компоненты (например: рис, куриная грудка, соус, салат) \
и оцени вес КАЖДОГО в граммах в приготовленном виде, как он лежит на тарелке.
- Для оценки порции используй ориентиры на фото: размер тарелки (обычная ~24–26 см), \
столовые приборы, руки, упаковки, стаканы.
- Не забывай скрытые калории: масло для жарки, соусы, заправки, сахар в напитках.
- Если пользователь написал подпись к фото (вес, состав, «без масла» и т.п.) — \
она важнее твоих догадок, опирайся на неё.
- На фото несколько блюд — перечисли всё как отдельные компоненты.
- Если на фото нет еды или напитка — поставь is_food=false, остальное заполни нулями/пустыми.
- Калории компонента должны примерно сходиться с 4*белки + 9*жиры + 4*углеводы.
- confidence: "high" — блюдо простое и порция хорошо видна; "medium" — типичный случай; \
"low" — плохое фото, сложный состав или непонятный размер порции.
- В comment (1–2 коротких предложения по-русски) скажи, что повлияло на оценку \
или о чём стоит уточнить (например, «не видно, жарили ли на масле»).
- Названия блюд и компонентов пиши по-русски.
"""

USER_PROMPT = "Оцени КБЖУ блюда на фото."

RESULT_SCHEMA = {
    "type": "object",
    "properties": {
        "is_food": {"type": "boolean"},
        "dish_name": {"type": "string"},
        "items": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "name": {"type": "string"},
                    "grams": {"type": "number"},
                    "kcal": {"type": "number"},
                    "protein_g": {"type": "number"},
                    "fat_g": {"type": "number"},
                    "carbs_g": {"type": "number"},
                },
                "required": ["name", "grams", "kcal", "protein_g", "fat_g", "carbs_g"],
                "additionalProperties": False,
            },
        },
        "confidence": {"type": "string", "enum": ["low", "medium", "high"]},
        "comment": {"type": "string"},
    },
    "required": ["is_food", "dish_name", "items", "confidence", "comment"],
    "additionalProperties": False,
}

# Модели, для которых включаем серверный fallback при отказе по политике безопасности.
_FALLBACK_MODELS = {"claude-opus-5-5", "claude-sonnet-5-5", "claude-fable-5-2"}


class AnalysisError(Exception):
    """Ошибка анализа с текстом, который можно показать пользователю."""


@dataclass(frozen=True)
class Item:
    name: str
    grams: float
    kcal: float
    protein_g: float
    fat_g: float
    carbs_g: float


@dataclass(frozen=True)
class Analysis:
    is_food: bool
    dish_name: str
    items: tuple[Item, ...]
    confidence: str
    comment: str

    # Итоги считаем сами из компонентов — так сумма всегда сходится со списком.
    @property
    def kcal(self) -> float:
        return sum(i.kcal for i in self.items)

    @property
    def protein_g(self) -> float:
        return sum(i.protein_g for i in self.items)

    @property
    def fat_g(self) -> float:
        return sum(i.fat_g for i in self.items)

    @property
    def carbs_g(self) -> float:
        return sum(i.carbs_g for i in self.items)

    @property
    def grams(self) -> float:
        return sum(i.grams for i in self.items)


def parse_result(raw: str) -> Analysis:
    try:
        data = json.loads(raw)
        items = tuple(
            Item(
                name=str(i["name"]),
                grams=max(0.0, float(i["grams"])),
                kcal=max(0.0, float(i["kcal"])),
                protein_g=max(0.0, float(i["protein_g"])),
                fat_g=max(0.0, float(i["fat_g"])),
                carbs_g=max(0.0, float(i["carbs_g"])),
            )
            for i in data["items"]
        )
        confidence = data["confidence"] if data["confidence"] in ("low", "medium", "high") else "medium"
        return Analysis(
            is_food=bool(data["is_food"]),
            dish_name=str(data["dish_name"]),
            items=items,
            confidence=confidence,
            comment=str(data.get("comment", "")),
        )
    except (ValueError, KeyError, TypeError) as exc:
        raise AnalysisError("Не получилось разобрать ответ модели. Попробуй отправить фото ещё раз.") from exc


class FoodAnalyzer:
    def __init__(self, model: str, client: anthropic.AsyncAnthropic | None = None) -> None:
        self.model = model
        self.client = client or anthropic.AsyncAnthropic()

    async def analyze(self, image_bytes: bytes, hint: str | None = None, media_type: str = "image/jpeg") -> Analysis:
        content: list[dict] = [
            {
                "type": "image",
                "source": {
                    "type": "base64",
                    "media_type": media_type,
                    "data": base64.standard_b64encode(image_bytes).decode("ascii"),
                },
            },
            {
                "type": "text",
                "text": USER_PROMPT + (f"\nПодпись пользователя к фото: {hint}" if hint else ""),
            },
        ]
        params: dict = dict(
            model=self.model,
            max_tokens=8000,
            system=SYSTEM_PROMPT,
            messages=[{"role": "user", "content": content}],
            output_config={"effort": "medium", "format": {"type": "json_schema", "schema": RESULT_SCHEMA}},
        )
        try:
            if self.model in _FALLBACK_MODELS:
                response = await self.client.beta.messages.create(
                    betas=["server-side-fallback-2026-07-01"], fallbacks="default", **params
                )
            else:
                response = await self.client.messages.create(**params)
        except anthropic.RateLimitError as exc:
            raise AnalysisError("Сервис анализа сейчас перегружен. Попробуй через минуту.") from exc
        except anthropic.AuthenticationError as exc:
            raise AnalysisError("Проблема с ключом Anthropic API — сообщи владельцу бота.") from exc
        except anthropic.APIStatusError as exc:
            raise AnalysisError(f"Ошибка сервиса анализа ({exc.status_code}). Попробуй ещё раз позже.") from exc
        except anthropic.APIConnectionError as exc:
            raise AnalysisError("Не удалось связаться с сервисом анализа. Попробуй ещё раз.") from exc

        if response.stop_reason == "refusal":
            raise AnalysisError("Модель не смогла обработать это фото. Попробуй другое.")
        if response.stop_reason == "max_tokens":
            raise AnalysisError("Ответ получился слишком длинным. Попробуй фото попроще.")
        text = next((b.text for b in response.content if b.type == "text"), None)
        if text is None:
            raise AnalysisError("Пустой ответ от модели. Попробуй ещё раз.")
        return parse_result(text)
