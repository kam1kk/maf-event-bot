import logging
from datetime import datetime, time, timedelta
from html import escape

from aiogram import Bot
from apscheduler.schedulers.asyncio import AsyncIOScheduler

from bot.config import get_tz
from bot.db import repo
from bot.db.models import Event
from bot.services import roster
from bot.utils import fmt_time, message_link

logger = logging.getLogger(__name__)

scheduler = AsyncIOScheduler(timezone=get_tz())

_bot: Bot | None = None


def setup(bot: Bot) -> None:
    global _bot
    _bot = bot


def _close_at(event: Event) -> datetime:
    # конец дня проведения: полночь следующего дня
    return datetime.combine(event.date_ + timedelta(days=1), time(0, 0), tzinfo=get_tz())


def _remind_at(event: Event) -> datetime:
    return datetime.combine(event.date_, event.time_, tzinfo=get_tz()) - timedelta(hours=1)


def schedule_event_jobs(event: Event) -> None:
    now = datetime.now(get_tz())
    close_at = _close_at(event)
    if close_at > now:
        scheduler.add_job(
            close_event, "date", run_date=close_at,
            id=f"close:{event.id}", args=[event.id], replace_existing=True,
        )
    remind_at = _remind_at(event)
    if event.remind_enabled and remind_at > now:
        scheduler.add_job(
            send_reminder, "date", run_date=remind_at,
            id=f"remind:{event.id}", args=[event.id], replace_existing=True,
        )


def cancel_event_jobs(event_id: int) -> None:
    for prefix in ("close", "remind"):
        job = scheduler.get_job(f"{prefix}:{event_id}")
        if job:
            job.remove()


def reschedule(event: Event) -> None:
    cancel_event_jobs(event.id)
    if event.status == "active":
        schedule_event_jobs(event)


async def close_event(event_id: int) -> None:
    event = await repo.get_event(event_id)
    if not event or event.status != "active":
        return
    await repo.update_event(event_id, status="closed")
    await roster.refresh_event_message(_bot, event_id)
    logger.info("Запись на событие %s закрыта (конец дня проведения)", event_id)


async def send_reminder(event_id: int) -> None:
    event = await repo.get_event(event_id)
    if not event or event.status != "active" or not event.remind_enabled:
        return
    event_type = await repo.get_type(event.type_id)
    if event_type and event_type.remind_chat_id:
        chat_id, topic_id = event_type.remind_chat_id, event_type.remind_topic_id
    else:
        chat_id, topic_id = event.chat_id, event.topic_id
    if not chat_id:
        return

    regs = await repo.get_regs(event_id)
    text = (
        f"⏰ Через час — <b>{escape(event.type_name)}</b> в {fmt_time(event.time_)}\n"
        f"📍 {escape(event.place)}  |  Ведущий: {escape(event.host)}\n"
        f"Записано: {len(regs)}"
    )
    if event.message_id:
        link = message_link(event.chat_id, event.message_id)
        if link:
            text += f"\n<a href=\"{link}\">Список участников</a>"
    try:
        await _bot.send_message(chat_id, text, message_thread_id=topic_id)
    except Exception as e:
        logger.warning("Не удалось отправить напоминание о событии %s: %s", event_id, e)


async def restore_jobs() -> None:
    """При старте бота восстанавливаем задачи по активным событиям.
    Если время закрытия прошло, пока бот лежал, — закрываем сразу."""
    now = datetime.now(get_tz())
    for event in await repo.list_active_events():
        if _close_at(event) <= now:
            await close_event(event.id)
        else:
            schedule_event_jobs(event)
