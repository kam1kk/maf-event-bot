import asyncio
import os
from datetime import date, time


class FakeBot:
    """Мок Telegram: помнит отправленные сообщения и умеет падать при отправке."""

    def __init__(self, fail_send: bool = False):
        self.fail_send = fail_send
        self.sent: list[dict] = []
        self.edits = 0

    async def edit_message_text(self, text, chat_id=None, message_id=None, **kwargs):
        self.edits += 1
        return True

    async def send_message(self, chat_id, text, message_thread_id=None, **kwargs):
        if self.fail_send:
            raise RuntimeError("chat not found")
        self.sent.append({"chat_id": chat_id, "topic": message_thread_id, "text": text})
        return True


def test_full_roster_alert(tmp_path):
    os.environ["DB_PATH"] = str(tmp_path / "full.db")
    os.environ.setdefault("TZ", "Europe/Moscow")

    from bot.config import settings
    from bot.db import repo
    from bot.db.models import init_db
    from bot.services import roster

    settings.db_path = os.environ["DB_PATH"]

    GROUP = -1001234567890
    TOPIC, REMIND_TOPIC = 42, 77

    async def run():
        await init_db()
        await repo.ensure_group(GROUP, "Тестовая группа")
        await repo.ensure_default_type(GROUP)
        et = (await repo.list_types(GROUP))[0]
        await repo.bind_type_topic(et.id, GROUP, TOPIC)
        await repo.bind_type_remind(et.id, GROUP, REMIND_TOPIC)

        async def new_event(day: int, message_id: int, status: str = "active"):
            return await repo.create_event(
                type_id=et.id, type_name=et.name, date_=date(2030, 9, day), time_=time(19, 0),
                place="Клуб «Тест»", host="Иван", creator_id=1,
                chat_id=GROUP, topic_id=TOPIC, message_id=message_id, status=status,
            )

        async def fill(event_id: int, count: int, first: int = 1):
            for i in range(first, first + count):
                await repo.add_reg(event_id, i, i, f"Nick{i}")

        bot = FakeBot()
        event = await new_event(10, 555)

        # девять человек — стол ещё не собран, в чат ничего не уходит
        for i in range(1, 10):
            await repo.add_reg(event.id, i, i, f"Nick{i}")
            await roster.refresh_event_message(bot, event.id)
        assert bot.sent == []

        # друг «через /» сидит в строке хозяина и места не занимает — не в счёт
        slash = await repo.add_reg(
            event.id, None, 1, "SlashBro", attached_to=(await repo.get_reg(event.id, 1)).id
        )
        await roster.refresh_event_message(bot, event.id)
        assert bot.sent == []
        await repo.delete_reg(slash.id)

        # десятый — опоздавший: он тоже в счёт
        late = await repo.add_reg(event.id, 10, 10, "LateGuy")
        await repo.update_reg(late.id, category="late", arrive_time=time(19, 30))
        await roster.refresh_event_message(bot, event.id)
        assert len(bot.sent) == 1
        msg = bot.sent[0]
        # уведомление уходит туда же, куда напоминание за час
        assert msg["chat_id"] == GROUP and msg["topic"] == REMIND_TOPIC
        assert "Состав собран: <b>10</b>" in msg["text"]
        assert "https://t.me/c/1234567890/555" in msg["text"]
        assert (await repo.get_event(event.id)).full_notified

        # состав меняется дальше — повторных уведомлений нет
        await repo.add_reg(event.id, 11, 11, "Nick11")
        await roster.refresh_event_message(bot, event.id)
        await repo.delete_reg((await repo.get_reg(event.id, 3)).id)
        await roster.refresh_event_message(bot, event.id)
        await repo.add_reg(event.id, 12, 12, "Nick12")
        await roster.refresh_event_message(bot, event.id)
        assert len(bot.sent) == 1

        # без отдельной темы напоминаний — уведомление в тему мероприятия
        await repo.unbind_type_remind(et.id)
        event2 = await new_event(11, 556)
        await fill(event2.id, 10)
        await roster.refresh_event_message(bot, event2.id)
        assert len(bot.sent) == 2 and bot.sent[-1]["topic"] == TOPIC

        # отменённый и закрытый столы не зовут никого, даже если состав полный
        for day, message_id, status in ((12, 557, "cancelled"), (13, 558, "closed")):
            dead = await new_event(day, message_id, status)
            await fill(dead.id, 10)
            await roster.refresh_event_message(bot, dead.id)
            assert not (await repo.get_event(dead.id)).full_notified
        assert len(bot.sent) == 2

        # отправка не прошла — отметка снимается, следующая правка пробует снова
        event3 = await new_event(14, 559)
        await fill(event3.id, 10)
        await roster.refresh_event_message(FakeBot(fail_send=True), event3.id)
        assert not (await repo.get_event(event3.id)).full_notified
        await repo.add_reg(event3.id, 99, 99, "Nick99")
        await roster.refresh_event_message(bot, event3.id)
        assert len(bot.sent) == 3 and "Состав собран: <b>11</b>" in bot.sent[-1]["text"]

    asyncio.run(run())
