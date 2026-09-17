import asyncio
import os
from datetime import date, datetime, time, timedelta
from types import SimpleNamespace


def _prepare(tmp_path, db_name: str):
    os.environ["DB_PATH"] = str(tmp_path / db_name)
    os.environ.setdefault("TZ", "Europe/Moscow")
    from bot.config import settings

    settings.db_path = os.environ["DB_PATH"]


class FakeMessage:
    """Сообщение в личке: помнит ответы бота и то, во что его перерисовали."""

    def __init__(self, text: str = "", user_id: int = 0):
        self.text = text
        self.from_user = SimpleNamespace(id=user_id)
        self.answers: list[str] = []
        self.edits: list[str] = []
        self.markups: list = []

    async def answer(self, text, reply_markup=None, **kwargs):
        self.answers.append(text)
        self.markups.append(reply_markup)
        return self

    async def edit_text(self, text, reply_markup=None, **kwargs):
        self.edits.append(text)
        self.markups.append(reply_markup)
        return self


class FakeCallback:
    def __init__(self, user_id: int, data: str):
        self.from_user = SimpleNamespace(id=user_id)
        self.data = data
        self.message = FakeMessage(user_id=user_id)
        self.alerts: list[str] = []

    async def answer(self, text=None, show_alert=False, **kwargs):
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

    async def clear(self):
        self.data = {}
        self.state = None


class FakeBot:
    """Мок Telegram для публикации и правки стола: не падает, помнит отправленное."""

    def __init__(self):
        self.sent: list[str] = []

    async def send_message(self, chat_id, text, **kwargs):
        self.sent.append(text)
        return SimpleNamespace(message_id=len(self.sent))

    async def edit_message_text(self, text, **kwargs):
        return True

    async def pin_chat_message(self, chat_id, message_id, **kwargs):
        return True

    async def unpin_chat_message(self, chat_id, message_id=None):
        return True


def _buttons(markup):
    return [b for row in markup.inline_keyboard for b in row]


def test_place_key():
    """Регистр, раскладка, пробелы и знаки не различают площадку;
    разные названия остаются разными."""
    from bot.utils import place_key

    same = [
        ("Лофт", "Loft"), ("Лофт", "LOFT"), ("loft", "Loft"),
        ("Клуб", "Club"), ("Цирк", "Cirk"), ("Цирк", "Tsirk"), ("Хаус", "Khaus"),
        ("Щука", "Shchuka"), ("Юла", "Yula"), ("Юла", "Jula"), ("Мафия", "Mafia"),
        ("Сергей", "Sergej"), ("Сергей", "Sergey"), ("Кофе", "Coffee"), ("Рок", "Rock"),
        ("Кафе «Лофт»", "Cafe Loft"), ("Лофт-бар", "Loft bar"), ("Лофт  бар", "Loftbar"),
        ("Лофт 2", "Loft 2"), ("Ёлки", "Elki"),
    ]
    for a, b in same:
        assert place_key(a) == place_key(b), (a, b, place_key(a), place_key(b))

    different = [
        ("Лофт", "Бар"), ("Лофт 1", "Лофт 2"), ("Loft", "Left"), ("Клуб", "Куб"),
        # удвоенные буквы схлопываются, цифры — нет: номер дома значим
        ("Лофт 11", "Лофт 1"), ("Ленина 55", "Ленина 5"),
    ]
    for a, b in different:
        assert place_key(a) != place_key(b), (a, b)

    # одни знаки — сравниваем буквально, «???» и «!!!» не склеиваются
    assert place_key("???") != place_key("!!!")


def test_resolve_place():
    from bot.utils import resolve_place

    # различие только в регистре — побеждает новый ввод
    assert resolve_place("LOFT", ["Loft"]) == "LOFT"
    assert resolve_place("loft", ["LOFT", "Bar"]) == "loft"
    # другой алфавит или знаки — берётся известное написание
    assert resolve_place("Лофт", ["Loft"]) == "Loft"
    assert resolve_place("лофт", ["Loft"]) == "Loft"
    assert resolve_place("Loft", ["Лофт"]) == "Лофт"
    assert resolve_place("Кафе Лофт", ["Кафе «Лофт»"]) == "Кафе «Лофт»"
    # незнакомое место — как ввели
    assert resolve_place("Лофт", ["Bar"]) == "Лофт"
    assert resolve_place("Лофт", []) == "Лофт"
    # из нескольких подходящих — первое: список идёт от недавних к старым
    assert resolve_place("Лофт", ["LOFT", "Loft"]) == "LOFT"


def test_place_keyboard():
    from bot import keyboards as kb

    places = [SimpleNamespace(id=5, place="Loft"), SimpleNamespace(id=3, place="Бар «Крыша»")]
    markup = kb.place_keyboard(places)
    assert [b.text for b in _buttons(markup)] == ["📍 Loft", "📍 Бар «Крыша»", "✖ Отмена"]
    assert markup.inline_keyboard[0][0].callback_data == "place:5"
    assert markup.inline_keyboard[-1][0].callback_data == "cform:cancel"

    # истории нет — только выход, как раньше
    assert len(kb.place_keyboard([]).inline_keyboard) == 1

    from_manage = kb.place_keyboard(places, cancel_cb="mng:7:menu", cancel_text="« Назад")
    assert from_manage.inline_keyboard[-1][0].callback_data == "mng:7:menu"
    assert from_manage.inline_keyboard[-1][0].text == "« Назад"


def test_place_history_repo(tmp_path, monkeypatch):
    """Одна строка на площадку: регистр перекрывается последним вводом, другой
    алфавит подстраивается под известное написание, порядок — по свежести."""
    _prepare(tmp_path, "places.db")

    from bot.db import repo
    from bot.db.models import init_db

    # часы с гарантированным шагом: порядок «по свежести» не должен зависеть
    # от разрешения системного времени
    ticks = iter(range(1, 10_000))
    monkeypatch.setattr(
        repo, "utcnow", lambda: datetime(2026, 9, 17) + timedelta(seconds=next(ticks))
    )

    async def names(user_id: int):
        return [p.place for p in await repo.list_places(user_id)]

    async def run():
        await init_db()
        assert await repo.list_places(1) == []
        assert await repo.resolve_place(1, "Лофт") == "Лофт"

        await repo.remember_place(1, "Loft")
        assert await names(1) == ["Loft"]

        # LOFT и Loft — одно место, остаётся последнее написание
        assert await repo.resolve_place(1, "LOFT") == "LOFT"
        await repo.remember_place(1, "LOFT")
        assert await names(1) == ["LOFT"]

        # «Лофт» при известной «LOFT» — берём «LOFT»; строка не плодится
        assert await repo.resolve_place(1, "Лофт") == "LOFT"
        await repo.remember_place(1, "Лофт")
        assert await names(1) == ["LOFT"]

        # новые площадки встают первыми, повторное использование поднимает наверх
        await repo.remember_place(1, "Бар «Крыша»")
        await repo.remember_place(1, "Клуб")
        assert await names(1) == ["Клуб", "Бар «Крыша»", "LOFT"]
        await repo.remember_place(1, "loft")
        assert await names(1) == ["loft", "Клуб", "Бар «Крыша»"]
        assert await repo.resolve_place(1, "Бар Крыша") == "Бар «Крыша»"

        # у каждого пользователя свой список
        assert await repo.list_places(2) == []
        await repo.remember_place(2, "Лофт")
        assert await names(2) == ["Лофт"]
        assert await repo.resolve_place(2, "Loft") == "Лофт"
        assert await repo.resolve_place(1, "Loft") == "Loft"

        # кнопками — три последних заведения, а не вся история
        assert repo.PLACE_SUGGESTIONS == 3
        for i in range(1, 6):
            await repo.remember_place(3, f"Место {i}")
        assert await names(3) == ["Место 5", "Место 4", "Место 3"]
        # старые площадки из кнопок ушли, но написание по ним всё ещё подстраивается
        assert await repo.resolve_place(3, "Mesto 1") == "Место 1"

    asyncio.run(run())


def test_place_step_in_create(tmp_path):
    """Шаг «место» в форме: кнопки с прежними площадками, ввод «Лофт» при
    известной «Loft» превращается в «Loft», публикация запоминает площадку."""
    _prepare(tmp_path, "places_create.db")

    from bot.db import repo
    from bot.db.models import init_db
    from bot.handlers.create import CreateForm, cb_place, cb_publish, input_place, input_time

    GROUP = -1001234567890
    USER = 77

    async def run():
        await init_db()
        await repo.ensure_group(GROUP, "Тестовая группа")
        await repo.ensure_default_type(GROUP)
        et = (await repo.list_types(GROUP))[0]
        await repo.bind_type_topic(et.id, GROUP, 42)

        # истории нет — шаг выглядит как раньше: только ввод и «Отмена»
        state = FakeState(group_chat_id=GROUP)
        message = FakeMessage("19:00", USER)
        await input_time(message, state)
        assert state.state == CreateForm.place
        assert message.answers[-1] == "Введите место проведения:"
        assert [b.text for b in _buttons(message.markups[-1])] == ["✖ Отмена"]

        # первое место вводится руками и сохраняется как есть, без лишних слов
        message = FakeMessage("Loft", USER)
        await input_place(message, state)
        assert state.data["place"] == "Loft" and state.state == CreateForm.host
        assert message.answers[-1] == "Введите имя ведущего игр:"

        # публикация запоминает площадку
        state.data.update(
            type_id=et.id, type_name=et.name, date="2030-08-15", date_str="15.08.2030",
            time="19:00:00", time_str="19:00", host="Кама",
        )
        callback = FakeCallback(USER, "cform:publish")
        await cb_publish(callback, state, FakeBot())
        assert "опубликовано" in callback.message.edits[-1]
        assert [p.place for p in await repo.list_places(USER)] == ["Loft"]
        assert (await repo.list_active_events(GROUP))[0].place == "Loft"

        # теперь на шаге места есть кнопка «📍 Loft»
        state = FakeState(group_chat_id=GROUP)
        message = FakeMessage("19:00", USER)
        await input_time(message, state)
        assert message.answers[-1] == "Выберите место проведения или введите новое:"
        buttons = _buttons(message.markups[-1])
        assert [b.text for b in buttons] == ["📍 Loft", "✖ Отмена"]
        place_id = int(buttons[0].callback_data.split(":")[1])

        # «Лофт» кириллицей — подставляется «Loft», бот говорит об этом
        message = FakeMessage("Лофт", USER)
        await input_place(message, state)
        assert state.data["place"] == "Loft" and state.state == CreateForm.host
        assert message.answers[-1] == (
            "Место: <b>Loft</b> (так вы писали его раньше)\nВведите имя ведущего игр:"
        )

        # кнопка подставляет площадку и ведёт к ведущему
        state = FakeState(group_chat_id=GROUP)
        callback = FakeCallback(USER, f"place:{place_id}")
        await cb_place(callback, state)
        assert state.data["place"] == "Loft" and state.state == CreateForm.host
        assert callback.message.edits[-1] == "Место: <b>Loft</b>\nВведите имя ведущего игр:"

        # чужая кнопка не срабатывает — площадки у каждого свои
        state = FakeState(group_chat_id=GROUP)
        callback = FakeCallback(99, f"place:{place_id}")
        await cb_place(callback, state)
        assert "place" not in state.data and state.state is None
        assert callback.message.edits == [] and callback.alerts

        # LOFT — то же место, но написание меняется на последнее
        state = FakeState(group_chat_id=GROUP)
        message = FakeMessage("LOFT", USER)
        await input_place(message, state)
        assert state.data["place"] == "LOFT"
        assert message.answers[-1] == "Введите имя ведущего игр:"

    asyncio.run(run())


def test_place_step_in_edit(tmp_path):
    """«⚙ Управление» → «📍 Место»: те же кнопки и тот же парсер, что в форме,
    и площадка тоже запоминается."""
    _prepare(tmp_path, "places_edit.db")

    from bot.db import repo
    from bot.db.models import init_db
    from bot.handlers.edit import EditForm, cb_edit_place, input_edit_place

    GROUP = -1001234567890
    USER = 77

    async def run():
        await init_db()
        await repo.ensure_group(GROUP, "Тестовая группа")
        await repo.ensure_default_type(GROUP)
        et = (await repo.list_types(GROUP))[0]
        await repo.bind_type_topic(et.id, GROUP, 42)
        event = await repo.create_event(
            type_id=et.id, type_name=et.name, date_=date(2030, 8, 15), time_=time(19, 0),
            place="Клуб", host="Кама", creator_id=USER, chat_id=GROUP, topic_id=42, message_id=5,
        )
        await repo.remember_place(USER, "Loft")

        # ввод кириллицей — в стол уходит известное «Loft»
        state = FakeState(event_id=event.id)
        state.state = EditForm.place
        message = FakeMessage("лофт", USER)
        await input_edit_place(message, state, FakeBot())
        assert (await repo.get_event(event.id)).place == "Loft"
        assert message.answers[-1].startswith(
            "Место изменено: <b>Loft</b> (так вы писали его раньше) ✅"
        )
        assert state.state is None

        # новое место — как ввели, и оно попадает в подсказки
        state = FakeState(event_id=event.id)
        message = FakeMessage("Бар", USER)
        await input_edit_place(message, state, FakeBot())
        assert message.answers[-1].startswith("Место изменено: <b>Бар</b> ✅")
        assert {p.place for p in await repo.list_places(USER)} == {"Loft", "Бар"}

        # кнопка с прежней площадкой
        loft = next(p for p in await repo.list_places(USER) if p.place == "Loft")
        state = FakeState(event_id=event.id)
        callback = FakeCallback(USER, f"place:{loft.id}")
        await cb_edit_place(callback, state, FakeBot())
        assert (await repo.get_event(event.id)).place == "Loft"
        assert callback.message.answers[-1].startswith("Место изменено: <b>Loft</b> ✅")

        # чужая кнопка — отказ, стол не тронут
        state = FakeState(event_id=event.id)
        callback = FakeCallback(99, f"place:{loft.id}")
        await cb_edit_place(callback, state, FakeBot())
        assert callback.alerts and callback.message.answers == []
        assert (await repo.get_event(event.id)).place == "Loft"

    asyncio.run(run())


def test_backfill_from_events(tmp_path):
    """Первый запуск версии: подсказки наполняются из уже созданных столов —
    по одной строке на площадку, последнее написание, недавние первыми."""
    _prepare(tmp_path, "places_backfill.db")

    from bot.db import models, repo
    from bot.db.models import init_db

    async def run():
        await init_db()
        history = [
            (1, "Loft"), (2, "Лофт"), (1, "Бар"), (1, "Лофт"), (1, "LOFT"), (2, "Клуб"),
        ]
        for creator, place in history:
            await repo.create_event(
                type_id=1, type_name="Мафия", date_=date(2030, 8, 15), time_=time(19, 0),
                place=place, host="Кама", creator_id=creator, chat_id=-100, topic_id=None,
            )
        # таблицы подсказок ещё не было — как у базы, созданной прошлой версией
        async with models.engine.begin() as conn:
            await conn.exec_driver_sql("DROP TABLE user_places")
        await models.engine.dispose()

        await init_db()
        # 1: Loft → Бар → Лофт (= Loft) → LOFT: две площадки, LOFT использована позже
        assert [p.place for p in await repo.list_places(1)] == ["LOFT", "Бар"]
        assert [p.place for p in await repo.list_places(2)] == ["Клуб", "Лофт"]

        # повторный запуск ничего не дублирует
        await models.engine.dispose()
        await init_db()
        assert len(await repo.list_places(1)) == 2

    asyncio.run(run())
