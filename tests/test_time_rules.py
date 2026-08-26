import asyncio
import os
from datetime import date, time


class FakeMessage:
    """Сообщение из лички: помнит, что бот ответил."""

    def __init__(self, text: str):
        self.text = text
        self.answers: list[str] = []

    async def answer(self, text, reply_markup=None):
        self.answers.append(text)
        return self


class FakeState:
    def __init__(self, **data):
        self.data = dict(data)
        self.cleared = False

    async def get_data(self):
        return dict(self.data)

    async def clear(self):
        self.cleared = True
        self.data = {}


def _prepare(tmp_path, db_name: str):
    os.environ["DB_PATH"] = str(tmp_path / db_name)
    os.environ.setdefault("TZ", "Europe/Moscow")
    from bot.config import settings

    settings.db_path = os.environ["DB_PATH"]


def test_promote_on_time_regs(tmp_path):
    """Стол перенесли на более позднее время — опоздавшие, которые теперь
    успевают, возвращаются в основной состав."""
    _prepare(tmp_path, "promote.db")

    from bot.db import repo
    from bot.db.models import init_db
    from bot.services.render import render_event

    GROUP = -1001234567890

    async def run():
        await init_db()
        await repo.ensure_group(GROUP, "Тестовая группа")
        await repo.ensure_default_type(GROUP)
        et = (await repo.list_types(GROUP))[0]
        await repo.bind_type_topic(et.id, GROUP, 42)

        event = await repo.create_event(
            type_id=et.id, type_name=et.name, date_=date(2030, 8, 15), time_=time(20, 0),
            place="Клуб", host="Иван", creator_id=1, chat_id=GROUP, topic_id=42,
        )

        on_time = await repo.add_reg(event.id, 1, 1, "Вовремя")
        at_start = await repo.add_reg(event.id, 2, 2, "Ровно21")
        after = await repo.add_reg(event.id, 3, 3, "Позже21")
        early = await repo.add_reg(event.id, 4, 4, "Ранний")
        await repo.update_reg(at_start.id, category="late", arrive_time=time(21, 0))
        await repo.update_reg(after.id, category="late", arrive_time=time(21, 30))
        # опоздавший, который заодно уйдёт раньше — пометка «до» должна уцелеть
        await repo.update_reg(early.id, category="late", arrive_time=time(20, 30),
                              leave_time=time(23, 0))

        text = render_event(event, await repo.get_regs(event.id))
        assert "Опоздавшие" in text and "Ровно21</a> (придёт к 21:00)" in text

        # начало сдвинули на 21:00 — успевают все, кто обещал прийти к 21:00 и раньше
        event = await repo.update_event(event.id, time_=time(21, 0))
        promoted = await repo.promote_on_time_regs(event.id, time(21, 0))
        assert [r.id for r in promoted] == [at_start.id, early.id]

        regs = {r.id: r for r in await repo.get_regs(event.id)}
        assert regs[at_start.id].category == "main" and regs[at_start.id].arrive_time is None
        assert regs[early.id].category == "main" and regs[early.id].arrive_time is None
        assert regs[early.id].leave_time == time(23, 0)  # «уйдёт раньше» не трогаем
        assert regs[after.id].category == "late" and regs[after.id].arrive_time == time(21, 30)
        assert regs[on_time.id].category == "main"

        text = render_event(event, await repo.get_regs(event.id))
        assert "придёт" not in next(l for l in text.splitlines() if "Ровно21" in l)
        assert "Ранний</a> (до 23:00)" in text
        assert "Позже21</a> (придёт к 21:30)" in text

        # повторный вызов ничего не меняет и никого не возвращает
        assert await repo.promote_on_time_regs(event.id, time(21, 0)) == []

        # стол сдвинули раньше — опоздавший остаётся опоздавшим
        await repo.update_event(event.id, time_=time(19, 0))
        assert await repo.promote_on_time_regs(event.id, time(19, 0)) == []
        assert (await repo.get_reg_by_id(after.id)).category == "late"

    asyncio.run(run())


def test_arrive_time_must_be_after_start(tmp_path):
    """«Приду позже» раньше или ровно в начало — не опоздание, ввод отклоняется.
    «Уйду раньше» такой проверки не имеет."""
    _prepare(tmp_path, "arrive.db")

    from bot.db import repo
    from bot.db.models import init_db
    from bot.handlers.profile import input_arrive, input_leave

    GROUP = -1001234567890

    async def run():
        await init_db()
        await repo.ensure_group(GROUP, "Тестовая группа")
        await repo.ensure_default_type(GROUP)
        et = (await repo.list_types(GROUP))[0]

        event = await repo.create_event(
            type_id=et.id, type_name=et.name, date_=date(2030, 8, 15), time_=time(20, 0),
            place="Клуб", host="Иван", creator_id=1, chat_id=GROUP, topic_id=42,
        )
        reg = await repo.add_reg(event.id, 1, 1, "Nick1")

        async def arrive(text: str):
            message, state = FakeMessage(text), FakeState(reg_id=reg.id)
            await input_arrive(message, state, bot=None)
            return message, state

        # раньше начала — отказ, состояние ввода сохраняется для новой попытки
        message, state = await arrive("19:30")
        assert "20:00" in message.answers[0] and not state.cleared
        assert (await repo.get_reg_by_id(reg.id)).category == "main"

        # ровно в начало — тоже отказ: это не опоздание
        message, state = await arrive("20:00")
        assert "20:00" in message.answers[0] and not state.cleared
        assert (await repo.get_reg_by_id(reg.id)).arrive_time is None

        # нераспознанное время — прежняя ошибка формата
        message, state = await arrive("вечером")
        assert "Не понял время" in message.answers[0] and not state.cleared

        # позже начала — записываем в опоздавшие
        message, state = await arrive("21:00")
        assert state.cleared and "Опоздавшие" in message.answers[0]
        fresh = await repo.get_reg_by_id(reg.id)
        assert fresh.category == "late" and fresh.arrive_time == time(21, 0)

        # «уйду раньше» до начала стола проверкой не ограничено
        message = FakeMessage("19:00")
        await input_leave(message, FakeState(reg_id=reg.id), bot=None)
        assert (await repo.get_reg_by_id(reg.id)).leave_time == time(19, 0)

    asyncio.run(run())


class FakeBot:
    """Ловит последнюю перерисовку сообщения события; в группе никто не Telegram-админ."""

    def __init__(self):
        self.markup = "не вызывался"

    async def edit_message_text(self, text, chat_id=None, message_id=None,
                                reply_markup=None, **kwargs):
        self.markup = reply_markup

    async def get_chat_member(self, chat_id, user_id):
        raise RuntimeError("чат недоступен")

    async def pin_chat_message(self, chat_id, message_id, disable_notification=None):
        return True

    async def unpin_chat_message(self, chat_id, message_id=None):
        return True


class FakeCallback:
    """Нажатие на инлайн-кнопку: помнит ответ бота."""

    def __init__(self, data: str, user_id: int):
        self.data = data
        self.from_user = type("U", (), {"id": user_id})()
        self.replies: list[str] = []

    async def answer(self, text=None, show_alert=False, url=None):
        self.replies.append(text)


def test_restore_button_expires_with_the_day(tmp_path):
    """Кнопку «Восстановить стол» видно только пока идёт день игры: время позже
    начала — ещё можно, наступил следующий день — уже нет. Кто отменил, роли не играет."""
    _prepare(tmp_path, "restore.db")

    from datetime import datetime, timedelta

    from bot.db import repo
    from bot.db.models import init_db
    from bot.services import roster

    GROUP = -1001234567890
    CREATOR, ADMIN = 1, 777

    async def run():
        await init_db()
        await repo.ensure_group(GROUP, "Тестовая группа")
        await repo.set_group_timezone(GROUP, "Europe/Moscow")
        await repo.ensure_default_type(GROUP)
        et = (await repo.list_types(GROUP))[0]
        tz = await repo.group_tz(GROUP)
        today = datetime.now(tz).date()

        async def make(day, cancelled_by=CREATOR, status="cancelled"):
            event = await repo.create_event(
                type_id=et.id, type_name=et.name, date_=day, time_=time(9, 0),
                place="Клуб", host="Иван", creator_id=CREATOR,
                chat_id=GROUP, topic_id=42, message_id=100,
            )
            return await repo.update_event(event.id, status=status, cancelled_by=cancelled_by)

        # стол сегодня: начало уже прошло (9:00), но день ещё идёт — восстановить можно
        todays = await make(today)
        assert await roster.restore_allowed(todays)

        # наступил следующий день — восстановление закрыто
        yesterdays = await make(today - timedelta(days=1))
        assert not await roster.restore_allowed(yesterdays)

        # кто отменил — неважно: стол админа тоже возвращается в день игры
        by_admin = await make(today, cancelled_by=ADMIN)
        assert await roster.restore_allowed(by_admin)
        assert not await roster.restore_allowed(await make(today - timedelta(days=1),
                                                           cancelled_by=ADMIN))

        # активный стол кнопки восстановления не получает
        active = await make(today, cancelled_by=None, status="active")
        assert not await roster.restore_allowed(active)

        # в самом сообщении: сегодня — кнопка есть, вчера — клавиатуры нет
        bot = FakeBot()
        await roster.refresh_event_message(bot, todays.id)
        assert bot.markup is not None and "rst:" in bot.markup.inline_keyboard[0][0].callback_data
        await roster.refresh_event_message(bot, yesterdays.id)
        assert bot.markup is None

    asyncio.run(run())


def test_admin_can_restore_cancelled_table(tmp_path):
    """Восстановить стол может и создатель, и админ бота — независимо от того,
    кто его отменил. Посторонний участник — нет."""
    _prepare(tmp_path, "restore_rights.db")

    from datetime import datetime, timedelta

    from bot.db import repo
    from bot.db.models import init_db
    from bot.handlers.edit import cb_restore

    GROUP = -1001234567890
    CREATOR, ADMIN, STRANGER = 1, 777, 500

    async def run():
        await init_db()
        await repo.ensure_group(GROUP, "Тестовая группа")
        await repo.set_group_timezone(GROUP, "Europe/Moscow")
        await repo.ensure_default_type(GROUP)
        await repo.add_group_admin(GROUP, ADMIN, "Админ", CREATOR)
        et = (await repo.list_types(GROUP))[0]
        tz = await repo.group_tz(GROUP)
        today = datetime.now(tz).date()
        bot = FakeBot()

        async def cancelled(day, by):
            event = await repo.create_event(
                type_id=et.id, type_name=et.name, date_=day, time_=time(9, 0),
                place="Клуб", host="Иван", creator_id=CREATOR,
                chat_id=GROUP, topic_id=42, message_id=100,
            )
            return await repo.update_event(event.id, status="cancelled", cancelled_by=by)

        async def press(event, user_id):
            callback = FakeCallback(f"rst:{event.id}", user_id)
            await cb_restore(callback, bot)
            return callback.replies[-1]

        # отменил админ — создатель откатывает
        event = await cancelled(today, ADMIN)
        assert "восстановлен" in await press(event, CREATOR)
        assert (await repo.get_event(event.id)).status == "active"

        # отменил создатель — админ откатывает
        event = await cancelled(today, CREATOR)
        assert "восстановлен" in await press(event, ADMIN)
        assert (await repo.get_event(event.id)).status == "active"

        # посторонний участник кнопкой не пользуется
        event = await cancelled(today, CREATOR)
        assert "создатель или админ бота" in await press(event, STRANGER)
        assert (await repo.get_event(event.id)).status == "cancelled"

        # день прошёл — отказ даже админу, кнопка из сообщения убирается
        event = await cancelled(today - timedelta(days=1), CREATOR)
        assert "уже прошёл" in await press(event, ADMIN)
        assert (await repo.get_event(event.id)).status == "cancelled"
        assert bot.markup is None

    asyncio.run(run())
