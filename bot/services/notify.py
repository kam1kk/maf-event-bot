import logging
from html import escape

from aiogram import Bot

from bot.db import repo
from bot.db.models import Event, Registration
from bot.services.render import MIN_SLOTS, split_roster
from bot.utils import fmt_date, fmt_time, message_link

logger = logging.getLogger(__name__)

# состав считается собранным, когда заняты все места основного списка;
# опоздавшие идут в зачёт наравне со всеми — за стол они всё равно сядут
FULL_COUNT = MIN_SLOTS


async def remind_target(event: Event) -> tuple[int | None, int | None]:
    """Куда бот пишет о столе: тема напоминаний типа, а если она не привязана —
    тема самого мероприятия."""
    event_type = await repo.get_type(event.type_id)
    if event_type and event_type.remind_chat_id:
        return event_type.remind_chat_id, event_type.remind_topic_id
    return event.chat_id, event.topic_id


def seat_count(regs: list[Registration]) -> int:
    """Сколько мест за столом занято: основной состав плюс опоздавшие. Друг
    «через /» сидит в строке хозяина, отдельного места не занимает и в счёт
    не идёт — ровно как в списке под сообщением стола."""
    hosts, _ = split_roster(regs)
    return len(hosts)


def full_text(event: Event, count: int) -> str:
    text = (
        f"🔥 Состав собран: <b>{count}</b> человек\n"
        f"🎭 <b>{escape(event.type_name)}</b> — {fmt_date(event.date_)}, {fmt_time(event.time_)}\n"
        f"📍 {escape(event.place)}  |  Ведущий: {escape(event.host)}"
    )
    link = message_link(event.chat_id, event.message_id) if event.message_id else None
    if link:
        text += f"\n<a href=\"{link}\">Список участников</a>"
    return text


async def roster_filled(bot: Bot, event: Event, regs: list[Registration]) -> None:
    """Набралось FULL_COUNT человек (с учётом опоздавших) — сообщаем об этом в тот
    же чат, куда приходит напоминание за час до стола. На стол — одно уведомление:
    отметка ставится атомарно, поэтому два одновременных «Записаться» не дадут
    двух сообщений, а выписка и новая запись не позовут людей повторно."""
    if not bot or event.status != "active" or event.full_notified:
        return
    count = seat_count(regs)
    if count < FULL_COUNT:
        return
    if not await repo.mark_full_notified(event.id):
        return  # уведомление уже отправляет другой обработчик
    chat_id, topic_id = await remind_target(event)
    if not chat_id:
        return
    try:
        await bot.send_message(chat_id, full_text(event, count), message_thread_id=topic_id)
    except Exception as e:
        # не дошло — снимаем отметку, следующая запись попробует ещё раз
        await repo.update_event(event.id, full_notified=False)
        logger.warning("Не удалось сообщить о полном составе события %s: %s", event.id, e)
