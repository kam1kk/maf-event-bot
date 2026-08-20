import os
from datetime import date, datetime, time, timezone

from sqlalchemy import BigInteger, Boolean, Date, DateTime, ForeignKey, Integer, String, Time
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

from bot.config import settings


class Base(DeclarativeBase):
    pass


class AppSetting(Base):
    __tablename__ = "app_settings"

    key: Mapped[str] = mapped_column(String(64), primary_key=True)
    value: Mapped[str] = mapped_column(String(128))


class Group(Base):
    """Группа Telegram, куда установлен бот. Настройки и типы — per-группа."""
    __tablename__ = "groups"

    chat_id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=False)
    title: Mapped[str | None] = mapped_column(String(128))
    timezone: Mapped[str | None] = mapped_column(String(64))  # None — фолбэк на TZ/системное
    # режим «создавать мероприятия могут только админы»; по умолчанию могут все
    only_admins_create: Mapped[bool] = mapped_column(Boolean, default=False)


class GroupAdmin(Base):
    """Участник, которому выдали права админа бота в конкретной группе.
    Telegram-админы группы считаются админами бота автоматически, без записи здесь."""
    __tablename__ = "group_admins"

    id: Mapped[int] = mapped_column(primary_key=True)
    chat_id: Mapped[int] = mapped_column(BigInteger)
    user_id: Mapped[int] = mapped_column(BigInteger)
    name: Mapped[str | None] = mapped_column(String(128))  # имя на момент выдачи, для списка
    granted_by: Mapped[int] = mapped_column(BigInteger)


class User(Base):
    __tablename__ = "users"

    tg_id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=False)
    nick: Mapped[str | None] = mapped_column(String(64))
    # задел на будущее: право создавать мероприятия только у админов бота
    is_admin: Mapped[bool] = mapped_column(Boolean, default=False)


class EventType(Base):
    __tablename__ = "event_types"

    id: Mapped[int] = mapped_column(primary_key=True)
    # группа-владелец типа; одноимённые типы в разных группах независимы
    group_chat_id: Mapped[int | None] = mapped_column(BigInteger)
    name: Mapped[str] = mapped_column(String(64))
    # тема, в которой публикуются мероприятия этого типа
    chat_id: Mapped[int | None] = mapped_column(BigInteger)
    topic_id: Mapped[int | None] = mapped_column(Integer)
    # тема для напоминаний (если не задана — напоминание в тему мероприятия)
    remind_chat_id: Mapped[int | None] = mapped_column(BigInteger)
    remind_topic_id: Mapped[int | None] = mapped_column(Integer)
    is_default: Mapped[bool] = mapped_column(Boolean, default=False)


class Event(Base):
    __tablename__ = "events"

    id: Mapped[int] = mapped_column(primary_key=True)
    type_id: Mapped[int] = mapped_column(ForeignKey("event_types.id"))
    type_name: Mapped[str] = mapped_column(String(64))
    date_: Mapped[date] = mapped_column("date", Date)
    time_: Mapped[time] = mapped_column("time", Time)
    place: Mapped[str] = mapped_column(String(128))
    host: Mapped[str] = mapped_column(String(64))
    creator_id: Mapped[int] = mapped_column(BigInteger)
    # снимок привязки на момент публикации — перепривязка типа не ломает старые события
    chat_id: Mapped[int | None] = mapped_column(BigInteger)
    topic_id: Mapped[int | None] = mapped_column(Integer)
    message_id: Mapped[int | None] = mapped_column(Integer)
    status: Mapped[str] = mapped_column(String(16), default="active")  # active | closed | cancelled
    remind_enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    # кто отменил стол; восстановление доступно, только если отменил сам создатель
    cancelled_by: Mapped[int | None] = mapped_column(BigInteger)


class Registration(Base):
    __tablename__ = "registrations"

    id: Mapped[int] = mapped_column(primary_key=True)
    event_id: Mapped[int] = mapped_column(ForeignKey("events.id"))
    user_id: Mapped[int | None] = mapped_column(BigInteger)  # None — гость (задел на будущее)
    added_by: Mapped[int] = mapped_column(BigInteger)
    nick: Mapped[str] = mapped_column(String(64))  # копия ника на момент записи
    username: Mapped[str | None] = mapped_column(String(64))  # @username на момент записи, для ссылки на профиль
    # id записи хозяина: гость «через /» — в одной строке с ним (kam1kk/mirai)
    attached_to: Mapped[int | None] = mapped_column(Integer)
    category: Mapped[str] = mapped_column(String(8), default="main")  # main | late
    arrive_time: Mapped[time | None] = mapped_column(Time)
    leave_time: Mapped[time | None] = mapped_column(Time)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, default=lambda: datetime.now(timezone.utc).replace(tzinfo=None)
    )


class TopicPin(Base):
    """Что бот закрепил в теме — чтобы снять свой прежний пин при пересборке.
    Одна строка на тему (chat_id + topic_id); topic_id None — общий чат группы."""
    __tablename__ = "topic_pins"

    id: Mapped[int] = mapped_column(primary_key=True)
    chat_id: Mapped[int] = mapped_column(BigInteger)
    topic_id: Mapped[int | None] = mapped_column(Integer)
    event_id: Mapped[int] = mapped_column(Integer)
    message_id: Mapped[int] = mapped_column(Integer)


engine = None
Session: async_sessionmaker[AsyncSession] | None = None


async def init_db() -> None:
    global engine, Session
    db_dir = os.path.dirname(settings.db_path)
    if db_dir:
        os.makedirs(db_dir, exist_ok=True)
    engine = create_async_engine(f"sqlite+aiosqlite:///{settings.db_path}")
    Session = async_sessionmaker(engine, expire_on_commit=False)
    async with engine.begin() as conn:
        # миграция на мультитенантность: старая event_types (без group_chat_id,
        # с UNIQUE на name) пересоздаётся — ALTER в SQLite ограничения не меняет
        result = await conn.exec_driver_sql(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='event_types'"
        )
        legacy_types = False
        if result.fetchone():
            columns = [row[1] for row in (
                await conn.exec_driver_sql("PRAGMA table_info(event_types)")
            ).fetchall()]
            if "group_chat_id" not in columns:
                legacy_types = True
                await conn.exec_driver_sql("ALTER TABLE event_types RENAME TO event_types_old")

        await conn.run_sync(Base.metadata.create_all)

        # create_all не добавляет колонки в существующие таблицы — доливаем вручную
        result = await conn.exec_driver_sql("PRAGMA table_info(registrations)")
        columns = [row[1] for row in result.fetchall()]
        if "username" not in columns:
            await conn.exec_driver_sql("ALTER TABLE registrations ADD COLUMN username VARCHAR(64)")
        if "attached_to" not in columns:
            await conn.exec_driver_sql("ALTER TABLE registrations ADD COLUMN attached_to INTEGER")
        result = await conn.exec_driver_sql("PRAGMA table_info(events)")
        columns = [row[1] for row in result.fetchall()]
        if columns and "cancelled_by" not in columns:
            await conn.exec_driver_sql("ALTER TABLE events ADD COLUMN cancelled_by BIGINT")
        result = await conn.exec_driver_sql("PRAGMA table_info(groups)")
        columns = [row[1] for row in result.fetchall()]
        if columns and "only_admins_create" not in columns:
            await conn.exec_driver_sql(
                "ALTER TABLE groups ADD COLUMN only_admins_create BOOLEAN DEFAULT 0"
            )

        if legacy_types:
            # группы — из привязок старых типов; типы получают группу-владельца
            await conn.exec_driver_sql(
                "INSERT OR IGNORE INTO groups (chat_id, title, timezone) "
                "SELECT DISTINCT chat_id, NULL, NULL FROM event_types_old WHERE chat_id IS NOT NULL"
            )
            await conn.exec_driver_sql(
                "INSERT INTO event_types "
                "(id, name, chat_id, topic_id, remind_chat_id, remind_topic_id, is_default, group_chat_id) "
                "SELECT id, name, chat_id, topic_id, remind_chat_id, remind_topic_id, is_default, chat_id "
                "FROM event_types_old"
            )
            # непривязанные типы: если группа одна — отдаём ей
            await conn.exec_driver_sql(
                "UPDATE event_types SET group_chat_id = (SELECT chat_id FROM groups LIMIT 1) "
                "WHERE group_chat_id IS NULL AND (SELECT COUNT(*) FROM groups) = 1"
            )
            await conn.exec_driver_sql("DROP TABLE event_types_old")
