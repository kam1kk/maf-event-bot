import asyncio
import os


class FakeMessage:
    """Сообщение бота с шагом «ведущий»: помнит, во что его перерисовали."""

    def __init__(self):
        self.edits: list[str] = []

    async def edit_text(self, text, reply_markup=None):
        self.edits.append(text)
        return self


class FakeCallback:
    def __init__(self, user_id: int):
        self.from_user = type("U", (), {"id": user_id})()
        self.message = FakeMessage()
        self.alerts: list[str] = []

    async def answer(self, text=None, show_alert=False):
        if text:
            self.alerts.append(text)


class FakeState:
    def __init__(self, **data):
        self.data = dict(data)
        self.state = None

    async def get_data(self):
        return dict(self.data)

    async def update_data(self, **kwargs):
        self.data.update(kwargs)

    async def set_state(self, state):
        self.state = state


def _prepare(tmp_path, db_name: str):
    os.environ["DB_PATH"] = str(tmp_path / db_name)
    os.environ.setdefault("TZ", "Europe/Moscow")
    from bot.config import settings

    settings.db_path = os.environ["DB_PATH"]


def test_host_keyboard():
    """Кнопка со своим ником появляется, только если ник задан.
    Ручной ввод остаётся доступен всегда — кнопка ничего не заменяет."""
    from bot import keyboards as kb

    with_nick = kb.host_keyboard("Кама")
    assert [b.text for row in with_nick.inline_keyboard for b in row] == ["🎤 Кама", "✖ Отмена"]
    assert with_nick.inline_keyboard[0][0].callback_data == "host:self"

    without_nick = kb.host_keyboard(None)
    assert len(without_nick.inline_keyboard) == 1
    assert without_nick.inline_keyboard[0][0].callback_data == "cform:cancel"

    # в «⚙ Управление» та же кнопка, но выход — «« Назад» в меню стола
    from_manage = kb.host_keyboard("Кама", cancel_cb="mng:7:menu", cancel_text="« Назад")
    assert from_manage.inline_keyboard[1][0].callback_data == "mng:7:menu"


def test_host_from_nick_in_create(tmp_path):
    """Нажатие кнопки подставляет ник из профиля и ведёт на предпросмотр."""
    _prepare(tmp_path, "host_prefill.db")

    from bot.db import repo
    from bot.db.models import init_db
    from bot.handlers.create import CreateForm, cb_host_self

    async def run():
        await init_db()
        await repo.set_nick(77, "Кама")

        state = FakeState(type_name="Мафия", date_str="15.08.2030", time_str="19:00", place="Клуб")
        callback = FakeCallback(77)
        await cb_host_self(callback, state)

        assert state.data["host"] == "Кама"
        assert state.state == CreateForm.confirm
        assert "Ведущий: Кама" in callback.message.edits[0]

        # ник не задан — подставлять нечего, форма остаётся на шаге ввода
        state = FakeState(type_name="Мафия", date_str="15.08.2030", time_str="19:00", place="Клуб")
        callback = FakeCallback(99)
        await cb_host_self(callback, state)

        assert "host" not in state.data
        assert state.state is None
        assert callback.message.edits == []
        assert "/nick" in callback.alerts[0]

    asyncio.run(run())
