import asyncio
import logging
from collections import defaultdict
from datetime import datetime

from aiogram import Bot
from aiogram.exceptions import TelegramBadRequest
from aiogram.types import LinkPreviewOptions

from bot.db import repo
from bot.keyboards import event_keyboard, restore_keyboard
from bot.services.render import render_event
from bot.utils import day_end

logger = logging.getLogger(__name__)

# сериализуем правки одного сообщения: два одновременных нажатия не потеряют записи
_locks: dict[int, asyncio.Lock] = defaultdict(asyncio.Lock)


async def restore_allowed(event) -> bool:
    """Отменённый стол можно вернуть, пока идёт день игры: после полуночи
    восстанавливать уже нечего. Кто именно отменил — неважно."""
    if event.status != "cancelled":
        return False
    tz = await repo.group_tz(event.chat_id)
    return datetime.now(tz) < day_end(event.date_, tz)


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
        elif await restore_allowed(event):
            keyboard = restore_keyboard(event.id)
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


async def guest_author_names(regs: list) -> dict[int, str]:
    """Имена тех, кто записывал друзей на мероприятие: ник из их собственной
    записи здесь же, иначе сохранённый игровой ник (записавший мог выписаться)."""
    adders = {r.added_by for r in regs if r.user_id is None}
    names = {r.user_id: r.nick for r in regs if r.user_id in adders}
    missing = adders - set(names)
    if missing:
        names.update(await repo.get_nicks(missing))
    return names


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
