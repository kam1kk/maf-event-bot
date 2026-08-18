from zoneinfo import ZoneInfo

from sqlalchemy import and_, delete, or_, select, update

from bot.config import get_tz
from bot.db import models
from bot.db.models import AppSetting, Event, EventType, Group, GroupAdmin, Registration, User


def S():
    assert models.Session is not None, "init_db() не вызван"
    return models.Session()


# ---------- app settings ----------

async def get_setting(key: str) -> str | None:
    async with S() as s:
        setting = await s.get(AppSetting, key)
        return setting.value if setting else None


async def set_setting(key: str, value: str) -> None:
    async with S() as s:
        setting = await s.get(AppSetting, key)
        if setting:
            setting.value = value
        else:
            s.add(AppSetting(key=key, value=value))
        await s.commit()


async def delete_setting(key: str) -> None:
    async with S() as s:
        await s.execute(delete(AppSetting).where(AppSetting.key == key))
        await s.commit()


# ---------- groups ----------

async def ensure_group(chat_id: int, title: str | None = None) -> Group:
    async with S() as s:
        group = await s.get(Group, chat_id)
        if not group:
            group = Group(chat_id=chat_id, title=title)
            s.add(group)
            await s.commit()
        elif title and group.title != title:
            group.title = title
            await s.commit()
        return group


async def get_group(chat_id: int) -> Group | None:
    async with S() as s:
        return await s.get(Group, chat_id)


async def list_groups() -> list[Group]:
    async with S() as s:
        result = await s.execute(select(Group).order_by(Group.title, Group.chat_id))
        return list(result.scalars().all())


async def set_group_timezone(chat_id: int, tz_name: str) -> None:
    async with S() as s:
        group = await s.get(Group, chat_id)
        if group:
            group.timezone = tz_name
            await s.commit()


async def set_group_creation_mode(chat_id: int, only_admins: bool) -> None:
    async with S() as s:
        group = await s.get(Group, chat_id)
        if group:
            group.only_admins_create = only_admins
            await s.commit()


# ---------- group admins (выданные права бота) ----------

async def is_group_admin(chat_id: int, user_id: int) -> bool:
    async with S() as s:
        result = await s.execute(
            select(GroupAdmin.id).where(
                GroupAdmin.chat_id == chat_id, GroupAdmin.user_id == user_id
            ).limit(1)
        )
        return result.first() is not None


async def add_group_admin(chat_id: int, user_id: int, name: str | None, granted_by: int) -> bool:
    if await is_group_admin(chat_id, user_id):
        return False
    async with S() as s:
        s.add(GroupAdmin(chat_id=chat_id, user_id=user_id, name=name, granted_by=granted_by))
        await s.commit()
        return True


async def remove_group_admin(chat_id: int, user_id: int) -> bool:
    if not await is_group_admin(chat_id, user_id):
        return False
    async with S() as s:
        await s.execute(
            delete(GroupAdmin).where(
                GroupAdmin.chat_id == chat_id, GroupAdmin.user_id == user_id
            )
        )
        await s.commit()
        return True


async def list_group_admins(chat_id: int) -> list[GroupAdmin]:
    async with S() as s:
        result = await s.execute(
            select(GroupAdmin).where(GroupAdmin.chat_id == chat_id).order_by(GroupAdmin.id)
        )
        return list(result.scalars().all())


async def group_tz(chat_id: int | None):
    """Часовой пояс группы; фолбэк — TZ из .env или системное время."""
    if chat_id:
        group = await get_group(chat_id)
        if group and group.timezone:
            try:
                return ZoneInfo(group.timezone)
            except Exception:
                pass
    return get_tz()


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


# ---------- event types (в разрезе группы) ----------

async def ensure_default_type(group_chat_id: int, name: str = "Мафия") -> None:
    async with S() as s:
        result = await s.execute(
            select(EventType).where(
                EventType.group_chat_id == group_chat_id, EventType.is_default.is_(True)
            )
        )
        if result.scalars().first():
            return
        result = await s.execute(
            select(EventType).where(
                EventType.group_chat_id == group_chat_id, EventType.name == name
            )
        )
        et = result.scalars().first()
        if et:
            et.is_default = True
        else:
            s.add(EventType(group_chat_id=group_chat_id, name=name, is_default=True))
        await s.commit()


async def list_types(group_chat_id: int) -> list[EventType]:
    async with S() as s:
        result = await s.execute(
            select(EventType)
            .where(EventType.group_chat_id == group_chat_id)
            .order_by(EventType.is_default.desc(), EventType.name)
        )
        return list(result.scalars().all())


async def get_type(type_id: int) -> EventType | None:
    async with S() as s:
        return await s.get(EventType, type_id)


async def get_type_by_name(group_chat_id: int, name: str) -> EventType | None:
    # регистронезависимо для кириллицы сравниваем в питоне (lower() в SQLite — только ASCII)
    target = name.strip().lower()
    for et in await list_types(group_chat_id):
        if et.name.lower() == target:
            return et
    return None


async def add_type(group_chat_id: int, name: str) -> EventType | None:
    if await get_type_by_name(group_chat_id, name):
        return None
    async with S() as s:
        et = EventType(group_chat_id=group_chat_id, name=name.strip())
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


async def unbind_type_topic(type_id: int) -> None:
    async with S() as s:
        et = await s.get(EventType, type_id)
        et.chat_id = None
        et.topic_id = None
        await s.commit()


async def unbind_type_remind(type_id: int) -> None:
    async with S() as s:
        et = await s.get(EventType, type_id)
        et.remind_chat_id = None
        et.remind_topic_id = None
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


async def list_active_events(chat_id: int | None = None) -> list[Event]:
    async with S() as s:
        query = select(Event).where(Event.status == "active")
        if chat_id is not None:
            query = query.where(Event.chat_id == chat_id)
        result = await s.execute(query.order_by(Event.date_, Event.time_))
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


async def get_guest_regs(event_id: int, added_by: int) -> list[Registration]:
    """Друзья (гости), записанные данным пользователем на мероприятие."""
    async with S() as s:
        result = await s.execute(
            select(Registration)
            .where(
                Registration.event_id == event_id,
                Registration.user_id.is_(None),
                Registration.added_by == added_by,
            )
            .order_by(Registration.id)
        )
        return list(result.scalars().all())


async def event_has_guests(event_id: int) -> bool:
    async with S() as s:
        result = await s.execute(
            select(Registration.id).where(
                Registration.event_id == event_id, Registration.user_id.is_(None)
            ).limit(1)
        )
        return result.first() is not None


async def add_reg(
    event_id: int, user_id: int | None, added_by: int, nick: str,
    username: str | None = None, attached_to: int | None = None,
) -> Registration:
    async with S() as s:
        reg = Registration(
            event_id=event_id, user_id=user_id, added_by=added_by, nick=nick,
            username=username, attached_to=attached_to,
        )
        s.add(reg)
        await s.commit()
        return reg


async def delete_reg(reg_id: int) -> None:
    async with S() as s:
        # друзья «через /» не исчезают вместе с хозяином, а становятся отдельными строками
        await s.execute(
            update(Registration).where(Registration.attached_to == reg_id).values(attached_to=None)
        )
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
            .where(
                Event.status == "active",
                or_(
                    Registration.user_id == user_id,
                    and_(Registration.user_id.is_(None), Registration.added_by == user_id),
                ),
            )
            .order_by(Event.date_, Event.time_)
        )
        return [(row[0], row[1]) for row in result.all()]
