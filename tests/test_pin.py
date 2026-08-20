import asyncio
import os
from datetime import date, time


class FakeBot:
    """Мок Telegram: помнит, что закреплено, и умеет отказывать в правах."""

    def __init__(self, can_pin: bool = True):
        self.can_pin = can_pin
        self.pinned: int | None = None
        self.pin_calls: list[int] = []
        self.unpin_calls: list[int] = []

    async def pin_chat_message(self, chat_id, message_id, disable_notification=None):
        self.pin_calls.append(message_id)
        if not self.can_pin:
            raise RuntimeError("not enough rights to pin a message")
        self.pinned = message_id
        return True

    async def unpin_chat_message(self, chat_id, message_id=None):
        self.unpin_calls.append(message_id)
        if self.pinned != message_id:
            raise RuntimeError("message to unpin not found")
        self.pinned = None
        return True


def test_topic_pin(tmp_path):
    os.environ["DB_PATH"] = str(tmp_path / "pin.db")
    os.environ.setdefault("TZ", "Europe/Moscow")

    from bot.config import settings
    from bot.db import repo
    from bot.db.models import init_db
    from bot.services import pin

    settings.db_path = os.environ["DB_PATH"]

    GROUP = -1001234567890
    TOPIC = 42

    async def run():
        await init_db()
        await repo.ensure_group(GROUP, "Тестовая группа")
        await repo.ensure_default_type(GROUP)
        et = (await repo.list_types(GROUP))[0]
        await repo.bind_type_topic(et.id, GROUP, TOPIC)

        async def new_event(day: int, hour: int, message_id: int, topic_id: int = TOPIC):
            return await repo.create_event(
                type_id=et.id, type_name=et.name, date_=date(2030, 9, day), time_=time(hour, 0),
                place="Тут", host="Он", creator_id=1,
                chat_id=GROUP, topic_id=topic_id, message_id=message_id,
            )

        bot = FakeBot()
        # пустая тема — закреплять нечего, лишних вызовов нет
        await pin.refresh_topic_pin(bot, GROUP, TOPIC)
        assert bot.pin_calls == [] and bot.unpin_calls == []

        far = await new_event(20, 19, 1001)
        await pin.refresh_for_event(bot, far)
        assert bot.pinned == 1001
        assert (await repo.get_topic_pin(GROUP, TOPIC)).event_id == far.id

        # повторная пересборка ничего не трогает — пин уже верный
        await pin.refresh_topic_pin(bot, GROUP, TOPIC)
        assert bot.pin_calls == [1001] and bot.unpin_calls == []

        # новое мероприятие раньше прежнего — старый пин снимается, вешается новый
        near = await new_event(10, 19, 1002)
        await pin.refresh_for_event(bot, near)
        assert bot.pinned == 1002 and bot.unpin_calls == [1001]

        # позже прежнего — закреп остаётся на ближайшем
        await new_event(25, 12, 1003)
        await pin.refresh_topic_pin(bot, GROUP, TOPIC)
        assert bot.pinned == 1002 and bot.pin_calls == [1001, 1002]

        # соседняя тема закрепляет своё, не трогая эту
        other = await new_event(11, 19, 2001, topic_id=99)
        await pin.refresh_for_event(bot, other)
        assert bot.pinned == 2001  # мок помнит один пин на чат, но записи в БД раздельные
        assert (await repo.get_topic_pin(GROUP, TOPIC)).message_id == 1002
        assert (await repo.get_topic_pin(GROUP, 99)).message_id == 2001

        # отмена ближайшего — закреп переходит следующему по времени
        bot.pinned = 1002  # возвращаем мок к состоянию темы TOPIC
        await repo.update_event(near.id, status="cancelled")
        await pin.refresh_topic_pin(bot, GROUP, TOPIC)
        assert bot.pinned == 1001 and bot.unpin_calls[-1] == 1002

        # активных не осталось — закреп снимается, запись в БД чистится
        for event in await repo.list_active_events(GROUP):
            if event.topic_id == TOPIC:
                await repo.update_event(event.id, status="closed")
        await pin.refresh_topic_pin(bot, GROUP, TOPIC)
        assert bot.pinned is None
        assert await repo.get_topic_pin(GROUP, TOPIC) is None

        # нет прав на закреп: бот не падает и не запоминает несуществующий пин
        weak = FakeBot(can_pin=False)
        await repo.update_event(far.id, status="active")
        await pin.refresh_topic_pin(weak, GROUP, TOPIC)
        assert weak.pinned is None and await repo.get_topic_pin(GROUP, TOPIC) is None

        # пин руками сняли в Telegram — открепление падает, но новый всё равно вешается
        await pin.refresh_topic_pin(bot, GROUP, TOPIC)
        assert bot.pinned == 1001
        await repo.update_event(far.id, status="cancelled")
        bot.pinned = None  # как будто открепили вручную
        await new_event(5, 19, 1004)
        await pin.refresh_topic_pin(bot, GROUP, TOPIC)
        assert bot.pinned == 1004

    asyncio.run(run())
