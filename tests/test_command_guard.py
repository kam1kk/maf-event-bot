import asyncio
import os
from datetime import datetime, timezone


def _prepare(tmp_path, db_name: str):
    os.environ["DB_PATH"] = str(tmp_path / db_name)
    os.environ.setdefault("TZ", "Europe/Moscow")
    from bot.config import settings

    settings.db_path = os.environ["DB_PATH"]


def _make_session():
    """Сессия-заглушка: запоминает текст ответов, в сеть не ходит."""
    from aiogram.client.session.base import BaseSession
    from aiogram.methods import SendMessage
    from aiogram.types import Chat, Message

    class FakeSession(BaseSession):
        def __init__(self):
            super().__init__()
            self.sent: list[str] = []

        async def close(self):
            pass

        async def make_request(self, bot, method, timeout=None):
            if isinstance(method, SendMessage):
                self.sent.append(method.text)
                return Message(
                    message_id=len(self.sent),
                    date=datetime.now(timezone.utc),
                    chat=Chat(id=method.chat_id, type="private"),
                )
            return True

        async def stream_content(self, *args, **kwargs):  # pragma: no cover
            yield b""

    return FakeSession()


def _message(user_id: int, text: str):
    """Входящее сообщение в личке. Команду Telegram размечает сам —
    повторяем разметку, иначе тест проверял бы только запасной путь."""
    from aiogram.types import Chat, Message, MessageEntity, User

    entities = None
    if text.startswith("/"):
        entities = [
            MessageEntity(type="bot_command", offset=0, length=len(text.split()[0]))
        ]
    return Message(
        message_id=100,
        date=datetime.now(timezone.utc),
        chat=Chat(id=user_id, type="private"),
        from_user=User(id=user_id, is_bot=False, first_name="Тест"),
        text=text,
        entities=entities,
    )


def test_command_name():
    """Отличаем команду от значения: «19:00» и «Кама» — не команды,
    «/new@mafbot» — команда new."""
    from bot.handlers.guard import command_name, is_blocked_command

    assert command_name(_message(1, "/new")) == "new"
    assert command_name(_message(1, "/new@mafbot")) == "new"
    assert command_name(_message(1, "/start ev_12")) == "start"
    assert command_name(_message(1, "Кама")) is None
    assert command_name(_message(1, "19:00")) is None
    assert command_name(_message(1, "13.08")) is None

    assert is_blocked_command(_message(1, "/settings"))
    assert is_blocked_command(_message(1, "/NEW"))
    # /start — и выход из формы, и вход по ссылке из группы: не трогаем
    assert not is_blocked_command(_message(1, "/start"))
    assert not is_blocked_command(_message(1, "/start ev_12"))
    assert not is_blocked_command(_message(1, "Кама"))


# роутеры — модульные синглтоны: к диспетчеру их можно привязать один раз,
# поэтому на весь файл один диспетчер, а тесты разведены по user_id
_ENV = None


def _bot_and_dp():
    global _ENV
    if _ENV is None:
        from aiogram import Bot
        from aiogram.fsm.storage.memory import MemoryStorage

        from bot.main import build_dispatcher

        session = _make_session()
        bot = Bot("42:TESTTOKEN", session=session)
        storage = MemoryStorage()
        _ENV = (session, bot, storage, build_dispatcher(storage))
    _ENV[0].sent.clear()
    return _ENV


def _ctx(storage, bot, user_id: int):
    from aiogram.fsm.context import FSMContext
    from aiogram.fsm.storage.base import StorageKey

    return FSMContext(
        storage=storage, key=StorageKey(bot_id=bot.id, chat_id=user_id, user_id=user_id)
    )


def test_command_does_not_become_nick(tmp_path):
    """Главный случай: /new на шаге ника не сохраняется как ник.
    Бот объясняет, что это команда, и остаётся ждать ввод."""
    _prepare(tmp_path, "guard_nick.db")

    from aiogram.types import Update

    from bot.db import repo
    from bot.db.models import init_db
    from bot.handlers.profile import NickForm

    USER = 555

    async def run():
        await init_db()
        session, bot, storage, dp = _bot_and_dp()
        ctx = _ctx(storage, bot, USER)

        await repo.get_or_create_user(USER)
        await ctx.set_state(NickForm.waiting)
        await ctx.update_data(reg_event_id=None)

        await dp.feed_update(bot, Update(update_id=1, message=_message(USER, "/new")))

        assert "Похоже, вы отправили команду" in session.sent[-1]
        assert "/new" in session.sent[-1] and "ник" in session.sent[-1]
        user = await repo.get_or_create_user(USER)
        assert user.nick is None, "команда не должна становиться ником"
        assert await ctx.get_state() == NickForm.waiting.state, "шаг ввода сохраняется"

        # обычный ник после отказа проходит как раньше
        await dp.feed_update(bot, Update(update_id=2, message=_message(USER, "Кама")))
        user = await repo.get_or_create_user(USER)
        assert user.nick == "Кама"
        assert await ctx.get_state() is None

    asyncio.run(run())


def test_command_does_not_become_place(tmp_path):
    """/settings на шаге «место» раньше сохранялся как название площадки:
    его хендлер живёт в роутере ниже create."""
    _prepare(tmp_path, "guard_place.db")

    from aiogram.types import Update

    from bot.db.models import init_db
    from bot.handlers.create import CreateForm

    USER = 777

    async def run():
        await init_db()
        session, bot, storage, dp = _bot_and_dp()
        ctx = _ctx(storage, bot, USER)
        await ctx.set_state(CreateForm.place)

        await dp.feed_update(
            bot, Update(update_id=1, message=_message(USER, "/settings"))
        )

        assert "/settings" in session.sent[-1] and "место" in session.sent[-1]
        assert await ctx.get_state() == CreateForm.place.state
        assert (await ctx.get_data()).get("place") is None

        # настоящее место сохраняется и форма едет дальше
        await dp.feed_update(
            bot, Update(update_id=2, message=_message(USER, "Клуб на Ленина"))
        )
        assert (await ctx.get_data())["place"] == "Клуб на Ленина"
        assert await ctx.get_state() == CreateForm.host.state

    asyncio.run(run())


def test_command_does_not_kill_form(tmp_path):
    """/nick на шаге «место» раньше молча очищал состояние — стол пропадал
    вместе с уже введёнными датой и временем."""
    _prepare(tmp_path, "guard_kill.db")

    from aiogram.types import Update

    from bot.db.models import init_db
    from bot.handlers.create import CreateForm

    USER = 999

    async def run():
        await init_db()
        session, bot, storage, dp = _bot_and_dp()
        ctx = _ctx(storage, bot, USER)
        await ctx.set_state(CreateForm.place)
        await ctx.update_data(date_str="13.08.2026", time_str="19:00")

        await dp.feed_update(bot, Update(update_id=1, message=_message(USER, "/nick")))

        assert await ctx.get_state() == CreateForm.place.state
        assert (await ctx.get_data())["date_str"] == "13.08.2026"

    asyncio.run(run())


def test_every_text_step_is_covered():
    """Каждый шаг с ручным вводом должен быть в EXPECTED — иначе на нём
    команда снова уедет в базу как значение."""
    from aiogram.fsm.state import State

    from bot.handlers import create, edit, profile
    from bot.handlers import settings as settings_handlers
    from bot.handlers.guard import EXPECTED

    # состояние, переданное в @router.message(...) первым аргументом,
    # само работает фильтром — искать надо State, а не StateFilter
    text_states: set[str] = set()
    for module in (profile, create, edit, settings_handlers):
        for handler in module.router.observers["message"].handlers:
            for f in handler.filters or []:
                if isinstance(f.callback, State):
                    text_states.add(f.callback.state)

    assert text_states, "не нашли ни одного шага ввода — сломался тест, а не код"
    assert text_states <= set(EXPECTED), f"без защиты остались: {text_states - set(EXPECTED)}"
