"""Telegram-бот: присылаешь фото еды — получаешь КБЖУ."""
from __future__ import annotations

import asyncio
import logging

from aiogram import Bot, Dispatcher, F, Router
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.filters import Command, CommandStart
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message

from .analyzer import AnalysisError, FoodAnalyzer
from .config import Config, load_config
from .db import Database
from .formatting import format_analysis, format_day

log = logging.getLogger("foodbot")

WELCOME = (
    "👋 Привет! Я считаю КБЖУ по фото еды.\n\n"
    "📸 Просто пришли фото блюда — я покажу состав, вес порции, калории, белки, жиры и углеводы.\n"
    "✍️ Можно добавить подпись к фото, чтобы уточнить: «200 г, без масла» или «это творог 5%».\n\n"
    "Команды:\n"
    "/today — что я съел сегодня\n"
    "/undo — убрать последнюю запись из дневника\n"
    "/help — подсказка"
)


def build_router(cfg: Config, analyzer: FoodAnalyzer, db: Database) -> Router:
    router = Router()

    def allowed(user_id: int) -> bool:
        return not cfg.allowed_user_ids or user_id in cfg.allowed_user_ids

    @router.message(CommandStart())
    @router.message(Command("help"))
    async def start(message: Message) -> None:
        if not allowed(message.from_user.id):
            await message.answer(f"Этот бот закрытый. Твой Telegram ID: {message.from_user.id}")
            return
        await message.answer(WELCOME)

    @router.message(Command("today"))
    async def today(message: Message) -> None:
        if not allowed(message.from_user.id):
            return
        uid = message.from_user.id
        await message.answer(format_day(await db.today_entries(uid), await db.today_totals(uid)))

    @router.message(Command("undo"))
    async def undo(message: Message) -> None:
        if not allowed(message.from_user.id):
            return
        dish = await db.undo_last_saved(message.from_user.id)
        await message.answer(f"↩️ Убрал из дневника: {dish}" if dish else "Сегодня в дневнике нечего убирать.")

    @router.message(F.photo)
    async def on_photo(message: Message, bot: Bot) -> None:
        uid = message.from_user.id
        if not allowed(uid):
            await message.answer(f"Этот бот закрытый. Твой Telegram ID: {uid}")
            return
        if await db.analyses_today(uid) >= cfg.daily_limit:
            await message.answer(f"Дневной лимит ({cfg.daily_limit} фото) исчерпан. Продолжим завтра!")
            return

        wait = await message.answer("🔍 Анализирую…")
        try:
            buf = await bot.download(message.photo[-1])  # самое большое разрешение
            result = await analyzer.analyze(buf.read(), hint=message.caption)
        except AnalysisError as exc:
            await wait.edit_text(f"⚠️ {exc}")
            return
        except Exception:
            log.exception("Необработанная ошибка при анализе фото")
            await wait.edit_text("⚠️ Что-то пошло не так. Попробуй ещё раз.")
            return

        text = format_analysis(result)
        if not result.is_food or not result.items:
            await wait.edit_text(text)
            return

        analysis_id = await db.add_analysis(
            uid, result.dish_name, result.kcal, result.protein_g, result.fat_g, result.carbs_g
        )
        keyboard = InlineKeyboardMarkup(
            inline_keyboard=[[InlineKeyboardButton(text="➕ Сохранить в дневник", callback_data=f"save:{analysis_id}")]]
        )
        await wait.edit_text(text, reply_markup=keyboard)

    @router.callback_query(F.data.startswith("save:"))
    async def on_save(call: CallbackQuery) -> None:
        if not allowed(call.from_user.id):
            await call.answer()
            return
        ok = await db.mark_saved(call.from_user.id, int(call.data.split(":", 1)[1]))
        if not ok:
            await call.answer("Запись не найдена", show_alert=True)
            return
        totals = await db.today_totals(call.from_user.id)
        await call.answer(f"Сохранено ✅ Сегодня уже {round(totals.kcal)} ккал", show_alert=False)
        if call.message:
            await call.message.edit_reply_markup(reply_markup=None)

    @router.message()
    async def fallback(message: Message) -> None:
        if allowed(message.from_user.id):
            await message.answer("Пришли мне фото еды 📸 (текст я не анализирую). /help — подсказка.")

    return router


async def run() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    cfg = load_config()
    db = Database(cfg.db_path, cfg.timezone)
    analyzer = FoodAnalyzer(cfg.anthropic_model)
    bot = Bot(cfg.telegram_token, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
    dp = Dispatcher()
    dp.include_router(build_router(cfg, analyzer, db))
    log.info("Бот запущен, модель: %s", cfg.anthropic_model)
    await dp.start_polling(bot)


def main() -> None:
    asyncio.run(run())


if __name__ == "__main__":
    main()
