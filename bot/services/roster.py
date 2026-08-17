import asyncio
import logging
from collections import defaultdict

from aiogram import Bot
from aiogram.exceptions import TelegramBadRequest
from aiogram.types import LinkPreviewOptions

from bot.db import repo
from bot.keyboards import event_keyboard
from bot.services.render import render_event

logger = logging.getLogger(__name__)

# сериализуем правки одного сообщения: два одновременных нажатия не потеряют записи
_locks: dict[int, asyncio.Lock] = defaultdict(asyncio.Lock)


async def refresh_event_message(bot: Bot, event_id: int) -> None:
    async with _locks[event_id]:
        event = await repo.get_event(event_id)
        if not event or not event.message_id:
            return
        regs = await repo.get_regs(event_id)
        text = render_event(event, regs)
        keyboard = None
        if event.status == "active":
            has_guests = any(r.user_id is None for r in regs)
            keyboard = event_keyboard(event.id, has_guests)
        try:
            await bot.edit_message_text(
                text,
                chat_id=event.chat_id,
                message_id=event.message_id,
                reply_markup=keyboard,
                link_preview_options=LinkPreviewOptions(is_disabled=True),
            )
        except TelegramBadRequest as e:
            if "message is not modified" not in str(e):
                logger.warning("Не удалось обновить сообщение события %s: %s", event_id, e)


async def register(
    bot: Bot, event_id: int, user_id: int, nick: str, username: str | None = None
) -> tuple[bool, str]:
    event = await repo.get_event(event_id)
    if not event or event.status != "active":
        return False, "Запись на это мероприятие закрыта."
    if await repo.get_reg(event_id, user_id):
        return False, "Вы уже записаны на это мероприятие."
    await repo.add_reg(event_id, user_id, user_id, nick, username=username)
    await refresh_event_message(bot, event_id)
    return True, f"Вы записаны: {nick} ✅"


async def unregister(bot: Bot, event_id: int, user_id: int) -> tuple[bool, str]:
    event = await repo.get_event(event_id)
    if not event or event.status != "active":
        return False, "Запись на это мероприятие закрыта."
    reg = await repo.get_reg(event_id, user_id)
    if not reg:
        return False, "Вы не записаны на это мероприятие."
    await repo.delete_reg(reg.id)
    await refresh_event_message(bot, event_id)
    return True, "Вы выписаны 🚪"
