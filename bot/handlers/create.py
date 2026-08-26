from datetime import datetime, timedelta
from html import escape

from aiogram import Bot, F, Router
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.storage.base import StorageKey
from aiogram.types import CallbackQuery, LinkPreviewOptions, Message

from bot import keyboards as kb
from bot.db import repo
from bot.services import membership, pin, scheduler
from bot.services.render import render_event
from bot.utils import fmt_date, fmt_time, parse_date, parse_time

router = Router()
router.message.filter(F.chat.type == "private")


class CreateForm(StatesGroup):
    group_ = State()
    type_ = State()
    date_ = State()
    date_manual = State()
    time_ = State()
    place = State()
    host = State()
    confirm = State()


async def _group_today(state: FSMContext):
    data = await state.get_data()
    tz = await repo.group_tz(data.get("group_chat_id"))
    return datetime.now(tz).date()


async def _show_types(target: Message, state: FSMContext, group_chat_id: int, edit: bool) -> None:
    types = await repo.list_types(group_chat_id)
    if not types:
        await repo.ensure_default_type(group_chat_id)
        types = await repo.list_types(group_chat_id)
    await state.update_data(group_chat_id=group_chat_id)
    await state.set_state(CreateForm.type_)
    text = "Выберите тип мероприятия:"
    markup = kb.types_keyboard(types)
    if edit:
        await target.edit_text(text, reply_markup=markup)
    else:
        await target.answer(text, reply_markup=markup)


async def _start_with_type(message: Message, state: FSMContext, event_type) -> None:
    """Вход в форму с уже известным типом (deep-link из привязанной темы)."""
    await state.update_data(
        group_chat_id=event_type.group_chat_id,
        type_id=event_type.id,
        type_name=event_type.name,
    )
    await state.set_state(CreateForm.date_)
    await message.answer(
        f"Тип: <b>{escape(event_type.name)}</b>\nВыберите дату:",
        reply_markup=kb.date_keyboard("cd"),
    )


async def start_in_dm(bot: Bot, storage, user_id: int, group_chat_id: int, event_type=None) -> bool:
    """Запуск формы прямо в личке — для /new из темы группы, без сообщений в теме.
    False — личка с ботом закрыта (человек не нажимал Start)."""
    if event_type and event_type.chat_id:
        text = f"Тип: <b>{escape(event_type.name)}</b>\nВыберите дату:"
        markup = kb.date_keyboard("cd")
    else:
        event_type = None
        types = await repo.list_types(group_chat_id)
        if not types:
            await repo.ensure_default_type(group_chat_id)
            types = await repo.list_types(group_chat_id)
        text = "Выберите тип мероприятия:"
        markup = kb.types_keyboard(types)

    try:
        await bot.send_message(user_id, text, reply_markup=markup)
    except Exception:
        return False

    # FSM-контекст лички собираем вручную: хендлер-инициатор живёт в контексте группы
    state = FSMContext(
        storage=storage, key=StorageKey(bot_id=bot.id, chat_id=user_id, user_id=user_id)
    )
    await state.clear()
    if event_type:
        await state.update_data(
            group_chat_id=event_type.group_chat_id,
            type_id=event_type.id,
            type_name=event_type.name,
        )
        await state.set_state(CreateForm.date_)
    else:
        await state.update_data(group_chat_id=group_chat_id)
        await state.set_state(CreateForm.type_)
    return True


async def start_from_deeplink(message: Message, state: FSMContext, bot: Bot, args: str) -> None:
    """Переход «Создать мероприятие» из темы группы (payload new_t_/new_g_)."""
    await state.clear()
    await repo.get_or_create_user(message.from_user.id)

    event_type = None
    group_chat_id = None
    try:
        if args.startswith("new_t_"):
            event_type = await repo.get_type(int(args[6:]))
            group_chat_id = event_type.group_chat_id if event_type else None
        elif args.startswith("new_g_"):
            group_chat_id = int(args[6:])
    except ValueError:
        pass
    if not group_chat_id:
        await message.answer("Не понял ссылку — попробуйте /new.")
        return

    group = await repo.get_group(group_chat_id)
    if not group or not await membership.is_member(bot, group_chat_id, message.from_user.id):
        await message.answer("Вы не состоите в этой группе.")
        return
    if group.only_admins_create and not await membership.is_bot_admin(
        bot, group_chat_id, message.from_user.id
    ):
        await message.answer("В этой группе создавать мероприятия могут только админы бота.")
        return

    if event_type and event_type.chat_id:
        await _start_with_type(message, state, event_type)
    else:
        await _show_types(message, state, group_chat_id, edit=False)


async def _own_nick(tg_id: int) -> str | None:
    user = await repo.get_user(tg_id)
    return user.nick if user else None


async def _set_host(state: FSMContext, host: str) -> None:
    await state.update_data(host=host)
    await state.set_state(CreateForm.confirm)


def _preview_text(data: dict) -> str:
    return (
        "Проверьте мероприятие:\n\n"
        f"🎭 <b>{escape(data['type_name'])}</b>\n"
        f"📅 {data['date_str']}, {data['time_str']}\n"
        f"📍 {escape(data['place'])}\n"
        f"🎤 Ведущий: {escape(data['host'])}"
    )


@router.message(Command("new"))
async def cmd_new(message: Message, state: FSMContext, bot: Bot) -> None:
    await state.clear()
    await repo.get_or_create_user(message.from_user.id)
    all_groups = await membership.user_groups(bot, message.from_user.id)
    if not all_groups:
        await message.answer(
            "Я не вижу вас ни в одной группе, где я работаю. "
            "Убедитесь, что вы состоите в группе и бот туда добавлен."
        )
        return
    # режим «только админы»: такие группы доступны лишь админам бота
    groups = []
    for g in all_groups:
        if not g.only_admins_create or await membership.is_bot_admin(bot, g.chat_id, message.from_user.id):
            groups.append(g)
    if not groups:
        await message.answer("В ваших группах создавать мероприятия могут только админы бота.")
        return
    if len(groups) == 1:
        await _show_types(message, state, groups[0].chat_id, edit=False)
        return
    await state.set_state(CreateForm.group_)
    await message.answer(
        "Для какой группы создаём мероприятие?",
        reply_markup=kb.group_picker_keyboard(groups, "cg"),
    )


@router.callback_query(CreateForm.group_, F.data.startswith("cg:"))
async def cb_group(callback: CallbackQuery, state: FSMContext) -> None:
    group_chat_id = int(callback.data.split(":")[1])
    await _show_types(callback.message, state, group_chat_id, edit=True)
    await callback.answer()


@router.callback_query(CreateForm.type_, F.data.startswith("ct:"))
async def cb_type(callback: CallbackQuery, state: FSMContext) -> None:
    type_id = int(callback.data.split(":")[1])
    event_type = await repo.get_type(type_id)
    data = await state.get_data()
    if not event_type or event_type.group_chat_id != data.get("group_chat_id"):
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
        await callback.message.edit_text(
            "Введите дату в формате <b>ДД.ММ</b> или <b>ДД.ММ.ГГГГ</b>:",
            reply_markup=kb.cancel_create_keyboard(),
        )
        await callback.answer()
        return
    base = await _group_today(state)
    event_date = base if choice == "today" else base + timedelta(days=1)
    await state.update_data(date=event_date.isoformat(), date_str=fmt_date(event_date))
    await state.set_state(CreateForm.time_)
    await callback.message.edit_text(
        f"Дата: <b>{fmt_date(event_date)}</b>\nВведите время начала (например, 19:00):",
        reply_markup=kb.cancel_create_keyboard(),
    )
    await callback.answer()


@router.message(CreateForm.date_manual, F.text)
async def input_date(message: Message, state: FSMContext) -> None:
    base = await _group_today(state)
    event_date = parse_date(message.text, base)
    if not event_date:
        await message.answer("Не понял дату. Формат: <b>ДД.ММ</b> или <b>ДД.ММ.ГГГГ</b>, например 15.08")
        return
    if event_date < base:
        await message.answer("Эта дата уже прошла. Введите будущую дату:")
        return
    await state.update_data(date=event_date.isoformat(), date_str=fmt_date(event_date))
    await state.set_state(CreateForm.time_)
    await message.answer(
        f"Дата: <b>{fmt_date(event_date)}</b>\nВведите время начала (например, 19:00):",
        reply_markup=kb.cancel_create_keyboard(),
    )


@router.message(CreateForm.time_, F.text)
async def input_time(message: Message, state: FSMContext) -> None:
    event_time = parse_time(message.text)
    if not event_time:
        await message.answer("Не понял время. Формат: <b>ЧЧ:ММ</b>, например 19:00")
        return
    await state.update_data(time=event_time.isoformat(), time_str=fmt_time(event_time))
    await state.set_state(CreateForm.place)
    await message.answer("Введите место проведения:", reply_markup=kb.cancel_create_keyboard())


@router.message(CreateForm.place, F.text)
async def input_place(message: Message, state: FSMContext) -> None:
    place = message.text.strip()
    if not place or len(place) > 128:
        await message.answer("Слишком длинно (максимум 128 символов). Введите место проведения:")
        return
    await state.update_data(place=place)
    await state.set_state(CreateForm.host)
    await message.answer(
        "Введите имя ведущего игр:",
        reply_markup=kb.host_keyboard(await _own_nick(message.from_user.id)),
    )


@router.message(CreateForm.host, F.text)
async def input_host(message: Message, state: FSMContext) -> None:
    host = message.text.strip()
    if not host or len(host) > 64:
        await message.answer("Слишком длинно (максимум 64 символа). Введите имя ведущего:")
        return
    await _set_host(state, host)
    data = await state.get_data()
    await message.answer(_preview_text(data), reply_markup=kb.confirm_keyboard())


@router.callback_query(CreateForm.host, F.data == "host:self")
async def cb_host_self(callback: CallbackQuery, state: FSMContext) -> None:
    """«Веду сам» — подставляем игровой ник из профиля."""
    nick = await _own_nick(callback.from_user.id)
    if not nick:
        await callback.answer("Игровой ник не задан — отправьте /nick или введите имя вручную", show_alert=True)
        return
    await _set_host(state, nick)
    data = await state.get_data()
    await callback.message.edit_text(_preview_text(data), reply_markup=kb.confirm_keyboard())
    await callback.answer()


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
            link_preview_options=LinkPreviewOptions(is_disabled=True),
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
    await scheduler.schedule_event_jobs(event)
    # новый стол мог оказаться ближайшим — пересобираем закреп темы
    await pin.refresh_for_event(bot, event)
    await state.clear()
    await callback.message.edit_text("Мероприятие опубликовано ✅\nУправление — кнопка «⚙ Управление» под списком.")
    await callback.answer()


@router.callback_query(F.data == "cform:cancel")
async def cb_cancel(callback: CallbackQuery, state: FSMContext) -> None:
    await state.clear()
    await callback.message.edit_text("Создание отменено.")
    await callback.answer()
