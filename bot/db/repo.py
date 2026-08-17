from sqlalchemy import delete, select

from bot.db import models
from bot.db.models import Event, EventType, Registration, User


def S():
    assert models.Session is not None, "init_db() не вызван"
    return models.Session()


# ---------- users ----------

async def get_user(tg_id: int) -> User | None:
    async with S() as s:
        return await s.get(User, tg_id)


async def get_or_create_user(tg_id: int) -> User:
    async with S() as s:
        user = await s.get(User, tg_id)
        if not user:
            user = User(tg_id=tg_id)
            s.add(user)
            await s.commit()
        return user


async def set_nick(tg_id: int, nick: str) -> None:
    async with S() as s:
        user = await s.get(User, tg_id)
        if not user:
            user = User(tg_id=tg_id)
            s.add(user)
        user.nick = nick
        await s.commit()


# ---------- event types ----------

async def ensure_default_type(name: str) -> None:
    async with S() as s:
        result = await s.execute(select(EventType).where(EventType.is_default.is_(True)))
        if result.scalars().first():
            return
        result = await s.execute(select(EventType).where(EventType.name == name))
        et = result.scalars().first()
        if et:
            et.is_default = True
        else:
            s.add(EventType(name=name, is_default=True))
        await s.commit()


async def list_types() -> list[EventType]:
    async with S() as s:
        result = await s.execute(
            select(EventType).order_by(EventType.is_default.desc(), EventType.name)
        )
        return list(result.scalars().all())


async def get_type(type_id: int) -> EventType | None:
    async with S() as s:
        return await s.get(EventType, type_id)


async def get_type_by_name(name: str) -> EventType | None:
    # регистронезависимо для кириллицы сравниваем в питоне (lower() в SQLite — только ASCII)
    target = name.strip().lower()
    for et in await list_types():
        if et.name.lower() == target:
            return et
    return None


async def add_type(name: str) -> EventType | None:
    if await get_type_by_name(name):
        return None
    async with S() as s:
        et = EventType(name=name.strip())
        s.add(et)
        await s.commit()
        return et


async def bind_type_topic(type_id: int, chat_id: int, topic_id: int | None) -> None:
    async with S() as s:
        et = await s.get(EventType, type_id)
        et.chat_id = chat_id
        et.topic_id = topic_id
        await s.commit()


async def bind_type_remind(type_id: int, chat_id: int, topic_id: int | None) -> None:
    async with S() as s:
        et = await s.get(EventType, type_id)
        et.remind_chat_id = chat_id
        et.remind_topic_id = topic_id
        await s.commit()


# ---------- events ----------

async def create_event(**kwargs) -> Event:
    async with S() as s:
        event = Event(**kwargs)
        s.add(event)
        await s.commit()
        return event


async def get_event(event_id: int) -> Event | None:
    async with S() as s:
        return await s.get(Event, event_id)


async def update_event(event_id: int, **fields) -> Event | None:
    async with S() as s:
        event = await s.get(Event, event_id)
        if not event:
            return None
        for key, value in fields.items():
            setattr(event, key, value)
        await s.commit()
        return event


async def list_active_events() -> list[Event]:
    async with S() as s:
        result = await s.execute(
            select(Event).where(Event.status == "active").order_by(Event.date_, Event.time_)
        )
        return list(result.scalars().all())


# ---------- registrations ----------

async def get_regs(event_id: int) -> list[Registration]:
    async with S() as s:
        result = await s.execute(
            select(Registration).where(Registration.event_id == event_id).order_by(Registration.id)
        )
        return list(result.scalars().all())


async def get_reg(event_id: int, user_id: int) -> Registration | None:
    async with S() as s:
        result = await s.execute(
            select(Registration).where(
                Registration.event_id == event_id, Registration.user_id == user_id
            )
        )
        return result.scalars().first()


async def get_reg_by_id(reg_id: int) -> Registration | None:
    async with S() as s:
        return await s.get(Registration, reg_id)


async def add_reg(event_id: int, user_id: int, added_by: int, nick: str) -> Registration:
    async with S() as s:
        reg = Registration(event_id=event_id, user_id=user_id, added_by=added_by, nick=nick)
        s.add(reg)
        await s.commit()
        return reg


async def delete_reg(reg_id: int) -> None:
    async with S() as s:
        await s.execute(delete(Registration).where(Registration.id == reg_id))
        await s.commit()


async def update_reg(reg_id: int, **fields) -> Registration | None:
    async with S() as s:
        reg = await s.get(Registration, reg_id)
        if not reg:
            return None
        for key, value in fields.items():
            setattr(reg, key, value)
        await s.commit()
        return reg


async def list_user_regs_on_active(user_id: int) -> list[tuple[Registration, Event]]:
    async with S() as s:
        result = await s.execute(
            select(Registration, Event)
            .join(Event, Registration.event_id == Event.id)
            .where(Registration.user_id == user_id, Event.status == "active")
            .order_by(Event.date_, Event.time_)
        )
        return [(row[0], row[1]) for row in result.all()]
