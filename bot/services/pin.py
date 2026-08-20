import asyncio
import logging
from collections import defaultdict

from aiogram import Bot

from bot.db import repo
from bot.db.models import Event

logger = logging.getLogger(__name__)

# пересборка пина темы — по одной за раз: два события, созданные одновременно,
# не должны закрепиться оба
_locks: dict[tuple[int, int | None], asyncio.Lock] = defaultdict(asyncio.Lock)


async def refresh_topic_pin(bot: Bot, chat_id: int | None, topic_id: int | None) -> None:
    """Держит закреплённым сообщение ближайшего активного мероприятия темы.
    Прежний пин бота снимается; если активных мероприятий не осталось — просто снимается."""
    if not bot or not chat_id:
        return
    async with _locks[(chat_id, topic_id)]:
        nearest = await repo.nearest_active_event(chat_id, topic_id)
        pin = await repo.get_topic_pin(chat_id, topic_id)
        if pin and nearest and pin.message_id == nearest.message_id:
            return  # закреплено то, что нужно

        if pin:
            await _unpin(bot, chat_id, pin.message_id)
            await repo.clear_topic_pin(chat_id, topic_id)
        if not nearest:
            return
        if await _pin(bot, chat_id, nearest.message_id):
            await repo.set_topic_pin(chat_id, topic_id, nearest.id, nearest.message_id)


async def refresh_for_event(bot: Bot, event: Event | None) -> None:
    """Пересборка пина темы, где опубликовано это мероприятие."""
    if event:
        await refresh_topic_pin(bot, event.chat_id, event.topic_id)


async def _pin(bot: Bot, chat_id: int, message_id: int) -> bool:
    try:
        await bot.pin_chat_message(chat_id, message_id, disable_notification=True)
        return True
    except Exception as e:
        # чаще всего — у бота нет права «закреплять сообщения»
        logger.warning("Не удалось закрепить сообщение %s в чате %s: %s", message_id, chat_id, e)
        return False


async def _unpin(bot: Bot, chat_id: int, message_id: int) -> None:
    try:
        await bot.unpin_chat_message(chat_id, message_id=message_id)
    except Exception as e:
        # сообщение могли открепить руками или удалить — не мешает закрепить новое
        logger.info("Не удалось открепить сообщение %s в чате %s: %s", message_id, chat_id, e)
