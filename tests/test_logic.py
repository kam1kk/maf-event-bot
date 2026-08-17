import asyncio
import os
from datetime import date, time


def test_smoke(tmp_path):
    # env до импорта модулей бота: config читает DB_PATH при импорте
    os.environ["DB_PATH"] = str(tmp_path / "test.db")
    os.environ.setdefault("TZ", "Europe/Moscow")

    from bot.db import repo
    from bot.db.models import init_db
    from bot.services.render import render_event
    from bot.utils import parse_date, parse_time, today

    async def run():
        await init_db()
        await repo.ensure_default_type("Мафия")

        types = await repo.list_types()
        assert types[0].name == "Мафия" and types[0].is_default
        await repo.bind_type_topic(types[0].id, -1001234567890, 42)
        et = await repo.get_type_by_name("мафия")
        assert et and et.topic_id == 42

        event = await repo.create_event(
            type_id=et.id, type_name=et.name, date_=date(2030, 8, 15), time_=time(19, 0),
            place="Клуб «Тест»", host="Иван", creator_id=1,
            chat_id=et.chat_id, topic_id=et.topic_id,
        )

        # 11 основных + 1 опоздавший + пометка "до"
        for i in range(1, 12):
            await repo.add_reg(event.id, i, i, f"Nick{i}")
        late = await repo.add_reg(event.id, 100, 100, "LateGuy")
        await repo.update_reg(late.id, category="late", arrive_time=time(19, 30))
        await repo.update_reg((await repo.get_reg(event.id, 3)).id, leave_time=time(21, 0))

        text = render_event(event, await repo.get_regs(event.id))
        assert "11. Nick11" in text
        assert "3. Nick3 (до 21:00)" in text
        assert "1. LateGuy (придёт к 19:30)" in text

        # выписка из середины — сдвиг нумерации
        await repo.delete_reg((await repo.get_reg(event.id, 5)).id)
        text = render_event(event, await repo.get_regs(event.id))
        assert "5. Nick6" in text and "Nick5" not in text

        # пустое событие: слоты 1-10, опоздавших не видно
        empty = await repo.create_event(
            type_id=et.id, type_name=et.name, date_=date(2030, 8, 16), time_=time(19, 0),
            place="Тут", host="Он", creator_id=1, chat_id=et.chat_id, topic_id=et.topic_id,
        )
        text = render_event(empty, [])
        assert text.count("\n10.") == 1 and "Опоздавшие" not in text

        cancelled = await repo.update_event(empty.id, status="cancelled")
        assert "Стол отменен" in render_event(cancelled, [])

        items = await repo.list_user_regs_on_active(3)
        assert len(items) == 1 and items[0][1].id == event.id

    asyncio.run(run())


def test_parsers():
    from bot.utils import parse_date, parse_time, today

    assert parse_date("15.08.2030") == date(2030, 8, 15)
    assert parse_date("31.02") is None
    assert parse_date("ерунда") is None
    assert parse_time("19:00") == time(19, 0)
    assert parse_time("9.30") == time(9, 30)
    assert parse_time("25:00") is None

    d = parse_date("01.01")
    assert d is not None and d >= today()
