from datetime import timedelta
from html import escape

from aiogram import Bot, F, Router
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import CallbackQuery, Message

from bot import keyboards as kb
from bot.db import repo
from bot.services import scheduler
from bot.services.render import render_event
from bot.utils import fmt_date, fmt_time, parse_date, parse_time, today

router = Router()
router.message.filter(F.chat.type == "private")


class CreateForm(StatesGroup):
    type_ = State()
    date_ = State()
    date_manual = State()
    time_ = State()
    place = State()
    host = State()
    confirm = State()


def _preview_text(data: dict) -> str:
    return (
        "Проверьте мероприятие:\n\n"
        f"🎭 <b>{escape(data['type_name'])}</b>\n"
        f"📅 {data['date_str']}, {data['time_str']}\n"
        f"📍 {escape(data['place'])}\n"
        f"🎤 Ведущий: {escape(data['host'])}"
    )


@router.message(Command("new"))
async def cmd_new(message: Message, state: FSMContext) -> None:
    await state.clear()
    await repo.get_or_create_user(message.from_user.id)
    types = await repo.list_types()
    await state.set_state(CreateForm.type_)
    await message.answer("Выберите тип мероприятия:", reply_markup=kb.types_keyboard(types))


@router.callback_query(CreateForm.type_, F.data.startswith("ct:"))
async def cb_type(callback: CallbackQuery, state: FSMContext) -> None:
    type_id = int(callback.data.split(":")[1])
    event_type = await repo.get_type(type_id)
    if not event_type:
        await callback.answer("Тип не найден", show_alert=True)
        return
    if not event_type.chat_id:
        await callback.answer(
            f"Тема для «{event_type.name}» не привязана.\n"
            f"Отправьте /bind {event_type.name} в нужной теме группы.",
            show_alert=True,
        )
        return
    await state.update_data(type_id=event_type.id, type_name=event_type.name)
    await state.set_state(CreateForm.date_)
    await callback.message.edit_text(
        f"Тип: <b>{escape(event_type.name)}</b>\nВыберите дату:",
        reply_markup=kb.date_keyboard("cd"),
    )
    await callback.answer()


@router.callback_query(CreateForm.date_, F.data.startswith("cd:"))
async def cb_date(callback: CallbackQuery, state: FSMContext) -> None:
    choice = callback.data.split(":")[1]
    if choice == "manual":
        await state.set_state(CreateForm.date_manual)
        await callback.message.edit_text("Введите дату в формате <b>ДД.ММ</b> или <b>ДД.ММ.ГГГГ</b>:")
        await callback.answer()
        return
    event_date = today() if choice == "today" else today() + timedelta(days=1)
    await state.update_data(date=event_date.isoformat(), date_str=fmt_date(event_date))
    await state.set_state(CreateForm.time_)
    await callback.message.edit_text(f"Дата: <b>{fmt_date(event_date)}</b>\nВведите время начала (например, 19:00):")
    await callback.answer()


@router.message(CreateForm.date_manual, F.text)
async def input_date(message: Message, state: FSMContext) -> None:
    event_date = parse_date(message.text)
    if not event_date:
        await message.answer("Не понял дату. Формат: <b>ДД.ММ</b> или <b>ДД.ММ.ГГГГ</b>, например 15.08")
        return
    if event_date < today():
        await message.answer("Эта дата уже прошла. Введите будущую дату:")
        return
    await state.update_data(date=event_date.isoformat(), date_str=fmt_date(event_date))
    await state.set_state(CreateForm.time_)
    await message.answer(f"Дата: <b>{fmt_date(event_date)}</b>\nВведите время начала (например, 19:00):")


@router.message(CreateForm.time_, F.text)
async def input_time(message: Message, state: FSMContext) -> None:
    event_time = parse_time(message.text)
    if not event_time:
        await message.answer("Не понял время. Формат: <b>ЧЧ:ММ</b>, например 19:00")
        return
    await state.update_data(time=event_time.isoformat(), time_str=fmt_time(event_time))
    await state.set_state(CreateForm.place)
    await message.answer("Введите место проведения:")


@router.message(CreateForm.place, F.text)
async def input_place(message: Message, state: FSMContext) -> None:
    place = message.text.strip()
    if not place or len(place) > 128:
        await message.answer("Слишком длинно (максимум 128 символов). Введите место проведения:")
        return
    await state.update_data(place=place)
    await state.set_state(CreateForm.host)
    await message.answer("Введите имя ведущего игр:")


@router.message(CreateForm.host, F.text)
async def input_host(message: Message, state: FSMContext) -> None:
    host = message.text.strip()
    if not host or len(host) > 64:
        await message.answer("Слишком длинно (максимум 64 символа). Введите имя ведущего:")
        return
    await state.update_data(host=host)
    await state.set_state(CreateForm.confirm)
    data = await state.get_data()
    await message.answer(_preview_text(data), reply_markup=kb.confirm_keyboard())


@router.callback_query(CreateForm.confirm, F.data == "cform:publish")
async def cb_publish(callback: CallbackQuery, state: FSMContext, bot: Bot) -> None:
    from datetime import date as date_cls, time as time_cls

    data = await state.get_data()
    event_type = await repo.get_type(data["type_id"])
    if not event_type or not event_type.chat_id:
        await state.clear()
        await callback.message.edit_text(
            "Тема для этого типа больше не привязана. Отправьте /bind в нужной теме группы и создайте заново."
        )
        await callback.answer()
        return

    event = await repo.create_event(
        type_id=event_type.id,
        type_name=event_type.name,
        date_=date_cls.fromisoformat(data["date"]),
        time_=time_cls.fromisoformat(data["time"]),
        place=data["place"],
        host=data["host"],
        creator_id=callback.from_user.id,
        chat_id=event_type.chat_id,
        topic_id=event_type.topic_id,
    )
    text = render_event(event, [])
    try:
        posted = await bot.send_message(
            event_type.chat_id,
            text,
            message_thread_id=event_type.topic_id,
            reply_markup=kb.event_keyboard(event.id),
        )
    except Exception:
        await repo.update_event(event.id, status="cancelled")
        await state.clear()
        await callback.message.edit_text(
            "Не удалось опубликовать сообщение в тему. Проверьте, что бот добавлен в группу "
            "и является администратором, затем создайте мероприятие заново."
        )
        await callback.answer()
        return

    event = await repo.update_event(event.id, message_id=posted.message_id)
    scheduler.schedule_event_jobs(event)
    await state.clear()
    await callback.message.edit_text("Мероприятие опубликовано ✅\nУправление — кнопка «⚙ Управление» под списком.")
    await callback.answer()


@router.callback_query(F.data == "cform:cancel")
async def cb_cancel(callback: CallbackQuery, state: FSMContext) -> None:
    await state.clear()
    await callback.message.edit_text("Создание отменено.")
    await callback.answer()
