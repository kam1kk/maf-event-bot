import os
from datetime import date, datetime, time, timezone

from sqlalchemy import BigInteger, Boolean, Date, DateTime, ForeignKey, Integer, String, Time
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

from bot.config import settings


class Base(DeclarativeBase):
    pass


class User(Base):
    __tablename__ = "users"

    tg_id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=False)
    nick: Mapped[str | None] = mapped_column(String(64))
    # задел на будущее: право создавать мероприятия только у админов бота
    is_admin: Mapped[bool] = mapped_column(Boolean, default=False)


class EventType(Base):
    __tablename__ = "event_types"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(64), unique=True)
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


class Registration(Base):
    __tablename__ = "registrations"

    id: Mapped[int] = mapped_column(primary_key=True)
    event_id: Mapped[int] = mapped_column(ForeignKey("events.id"))
    user_id: Mapped[int | None] = mapped_column(BigInteger)  # None — гость (задел на будущее)
    added_by: Mapped[int] = mapped_column(BigInteger)
    nick: Mapped[str] = mapped_column(String(64))  # копия ника на момент записи
    username: Mapped[str | None] = mapped_column(String(64))  # @username на момент записи, для ссылки на профиль
    category: Mapped[str] = mapped_column(String(8), default="main")  # main | late
    arrive_time: Mapped[time | None] = mapped_column(Time)
    leave_time: Mapped[time | None] = mapped_column(Time)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, default=lambda: datetime.now(timezone.utc).replace(tzinfo=None)
    )


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
        await conn.run_sync(Base.metadata.create_all)
        # create_all не добавляет колонки в существующие таблицы — доливаем вручную
        result = await conn.exec_driver_sql("PRAGMA table_info(registrations)")
        columns = [row[1] for row in result.fetchall()]
        if "username" not in columns:
            await conn.exec_driver_sql("ALTER TABLE registrations ADD COLUMN username VARCHAR(64)")
