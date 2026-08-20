from datetime import datetime, timedelta
from html import escape

from aiogram import Bot, F, Router
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import CallbackQuery, Message

from bot import keyboards as kb
from bot.db import repo
from bot.services import membership, pin, roster, scheduler
from bot.services.render import render_guests, render_summary
from bot.utils import fmt_date, fmt_time, parse_date, parse_time

router = Router()


class EditForm(StatesGroup):
    date_manual = State()
    time_ = State()
    place = State()
    host = State()


async def _can_manage(bot: Bot, event, user_id: int) -> bool:
    """Создатель мероприятия или админ бота его группы."""
    if user_id == event.creator_id:
        return True
    return await membership.is_bot_admin(bot, event.chat_id, user_id)


async def send_manage_menu(bot: Bot, user_id: int, event_id: int) -> bool:
    event = await repo.get_event(event_id)
    if not event:
        return False
    if not await _can_manage(bot, event, user_id):
        return False
    try:
        await bot.send_message(
            user_id,
            f"Управление мероприятием:\n\n{render_summary(event)}",
            reply_markup=kb.manage_keyboard(event),
        )
        return True
    except Exception:
        return False


@router.callback_query(F.data.startswith("manage:"))
async def cb_manage(callback: CallbackQuery, bot: Bot) -> None:
    event_id = int(callback.data.split(":")[1])
    event = await repo.get_event(event_id)
    if not event:
        await callback.answer("Мероприятие не найдено", show_alert=True)
        return
    if not await _can_manage(bot, event, callback.from_user.id):
        await callback.answer(
            "Управлять мероприятием может его создатель или админ бота", show_alert=True
        )
        return
    if event.status != "active":
        await callback.answer("Мероприятие уже завершено", show_alert=True)
        return
    if await send_manage_menu(bot, callback.from_user.id, event_id):
        await callback.answer("Меню управления отправлено вам в личку")
    else:
        # личка с ботом закрыта — даём deep-link
        me = await bot.get_me()
        await callback.answer(url=f"https://t.me/{me.username}?start=mng_{event_id}")


async def _after_edit(bot: Bot, message: Message, event_id: int, note: str) -> None:
    event = await repo.get_event(event_id)
    await roster.refresh_event_message(bot, event_id)
    await scheduler.reschedule(event)
    # дата или время могли сменить ближайшее мероприятие темы
    await pin.refresh_for_event(bot, event)
    await message.answer(
        f"{note}\n\n{render_summary(event)}",
        reply_markup=kb.manage_keyboard(event),
    )


@router.callback_query(F.data.startswith("mng:"))
async def cb_manage_action(callback: CallbackQuery, state: FSMContext, bot: Bot) -> None:
    _, event_id_raw, action = callback.data.split(":")
    event_id = int(event_id_raw)
    event = await repo.get_event(event_id)
    if not event:
        await callback.answer("Мероприятие не найдено", show_alert=True)
        return
    if not await _can_manage(bot, event, callback.from_user.id):
        await callback.answer("Только создатель или админ бота", show_alert=True)
        return
    if event.status != "active" and action != "close":
        await callback.answer("Мероприятие уже завершено", show_alert=True)
        return

    if action == "date":
        await state.clear()
        await state.update_data(event_id=event_id)
        await callback.message.edit_text(
            "Новая дата:",
            reply_markup=kb.date_keyboard(f"ed:{event_id}", cancel_cb=f"mng:{event_id}:menu", cancel_text="« Назад"),
        )
    elif action == "time":
        await state.set_state(EditForm.time_)
        await state.update_data(event_id=event_id)
        await callback.message.edit_text(
            "Введите новое время начала (например, 19:00):",
            reply_markup=kb.back_to_manage_keyboard(event_id),
        )
    elif action == "place":
        await state.set_state(EditForm.place)
        await state.update_data(event_id=event_id)
        await callback.message.edit_text(
            "Введите новое место проведения:",
            reply_markup=kb.back_to_manage_keyboard(event_id),
        )
    elif action == "host":
        await state.set_state(EditForm.host)
        await state.update_data(event_id=event_id)
        await callback.message.edit_text(
            "Введите нового ведущего:",
            reply_markup=kb.back_to_manage_keyboard(event_id),
        )
    elif action == "remind":
        event = await repo.update_event(event_id, remind_enabled=not event.remind_enabled)
        await scheduler.reschedule(event)
        await callback.message.edit_reply_markup(reply_markup=kb.manage_keyboard(event))
    elif action == "kick":
        regs = await repo.get_regs(event_id)
        if not regs:
            await callback.answer("Пока никто не записан", show_alert=True)
            return
        await callback.message.edit_text(
            "Кого выписать? Нажмите на участника:",
            reply_markup=kb.kick_keyboard(event_id, regs),
        )
    elif action == "guests":
        # кто записал каждого друга — видно только создателю и админам бота
        regs = await repo.get_regs(event_id)
        await callback.message.edit_text(
            f"{render_summary(event)}\n\n{render_guests(regs, await roster.guest_author_names(regs))}",
            reply_markup=kb.back_to_manage_keyboard(event_id),
        )
    elif action == "menu":
        # «Назад» из любого шага ввода: сбрасываем ожидание текста
        await state.clear()
        await callback.message.edit_text(
            f"Управление мероприятием:\n\n{render_summary(event)}",
            reply_markup=kb.manage_keyboard(event),
        )
    elif action == "cancel":
        await callback.message.edit_text(
            "Точно отменить стол? Запись закроется, в сообщении появится «Стол отменен».",
            reply_markup=kb.cancel_confirm_keyboard(event_id),
        )
    elif action == "close":
        await callback.message.edit_text("Готово ✔")
    await callback.answer()


@router.callback_query(F.data.startswith("ed:"))
async def cb_edit_date(callback: CallbackQuery, state: FSMContext, bot: Bot) -> None:
    _, event_id_raw, choice = callback.data.split(":")
    event_id = int(event_id_raw)
    event = await repo.get_event(event_id)
    if not event or not await _can_manage(bot, event, callback.from_user.id):
        await callback.answer("Недоступно", show_alert=True)
        return

    if choice == "manual":
        await state.set_state(EditForm.date_manual)
        await state.update_data(event_id=event_id)
        await callback.message.edit_text(
            "Введите дату в формате <b>ДД.ММ</b> или <b>ДД.ММ.ГГГГ</b>:",
            reply_markup=kb.back_to_manage_keyboard(event_id),
        )
        await callback.answer()
        return

    tz = await repo.group_tz(event.chat_id)
    base = datetime.now(tz).date()
    new_date = base if choice == "today" else base + timedelta(days=1)
    await repo.update_event(event_id, date_=new_date)
    await state.clear()
    await _after_edit(bot, callback.message, event_id, f"Дата изменена: <b>{fmt_date(new_date)}</b> ✅")
    await callback.answer()


@router.message(EditForm.date_manual, F.text, F.chat.type == "private")
async def input_edit_date(message: Message, state: FSMContext, bot: Bot) -> None:
    data = await state.get_data()
    event = await repo.get_event(data["event_id"])
    tz = await repo.group_tz(event.chat_id if event else None)
    base = datetime.now(tz).date()
    new_date = parse_date(message.text, base)
    if not new_date:
        await message.answer("Не понял дату. Формат: <b>ДД.ММ</b> или <b>ДД.ММ.ГГГГ</b>")
        return
    if new_date < base:
        await message.answer("Эта дата уже прошла. Введите будущую дату:")
        return
    await state.clear()
    await repo.update_event(data["event_id"], date_=new_date)
    await _after_edit(bot, message, data["event_id"], f"Дата изменена: <b>{fmt_date(new_date)}</b> ✅")


@router.message(EditForm.time_, F.text, F.chat.type == "private")
async def input_edit_time(message: Message, state: FSMContext, bot: Bot) -> None:
    new_time = parse_time(message.text)
    if not new_time:
        await message.answer("Не понял время. Формат: <b>ЧЧ:ММ</b>, например 19:00")
        return
    data = await state.get_data()
    await state.clear()
    await repo.update_event(data["event_id"], time_=new_time)
    await _after_edit(bot, message, data["event_id"], f"Время изменено: <b>{fmt_time(new_time)}</b> ✅")


@router.message(EditForm.place, F.text, F.chat.type == "private")
async def input_edit_place(message: Message, state: FSMContext, bot: Bot) -> None:
    place = message.text.strip()
    if not place or len(place) > 128:
        await message.answer("Слишком длинно (максимум 128 символов). Введите место:")
        return
    data = await state.get_data()
    await state.clear()
    await repo.update_event(data["event_id"], place=place)
    await _after_edit(bot, message, data["event_id"], f"Место изменено: <b>{escape(place)}</b> ✅")


@router.message(EditForm.host, F.text, F.chat.type == "private")
async def input_edit_host(message: Message, state: FSMContext, bot: Bot) -> None:
    host = message.text.strip()
    if not host or len(host) > 64:
        await message.answer("Слишком длинно (максимум 64 символа). Введите ведущего:")
        return
    data = await state.get_data()
    await state.clear()
    await repo.update_event(data["event_id"], host=host)
    await _after_edit(bot, message, data["event_id"], f"Ведущий изменён: <b>{escape(host)}</b> ✅")


@router.callback_query(F.data.startswith("kick:"))
async def cb_kick(callback: CallbackQuery, bot: Bot) -> None:
    _, event_id_raw, reg_id_raw = callback.data.split(":")
    event_id, reg_id = int(event_id_raw), int(reg_id_raw)
    event = await repo.get_event(event_id)
    if not event or not await _can_manage(bot, event, callback.from_user.id):
        await callback.answer("Недоступно", show_alert=True)
        return
    if event.status != "active":
        await callback.answer("Мероприятие уже завершено", show_alert=True)
        return
    reg = await repo.get_reg_by_id(reg_id)
    if not reg or reg.event_id != event_id:
        await callback.answer("Запись уже удалена", show_alert=True)
        return

    await repo.delete_reg(reg_id)
    await roster.refresh_event_message(bot, event_id)
    regs = await repo.get_regs(event_id)
    if regs:
        await callback.message.edit_text(
            f"Выписан: <b>{escape(reg.nick)}</b> ✅\n\nКого выписать? Нажмите на участника:",
            reply_markup=kb.kick_keyboard(event_id, regs),
        )
    else:
        await callback.message.edit_text(
            f"Выписан: <b>{escape(reg.nick)}</b> ✅\n\nСписок пуст.\n\n"
            f"Управление мероприятием:\n\n{render_summary(event)}",
            reply_markup=kb.manage_keyboard(event),
        )
    await callback.answer()


@router.callback_query(F.data.startswith("mngc:"))
async def cb_cancel_confirm(callback: CallbackQuery, bot: Bot) -> None:
    _, event_id_raw, choice = callback.data.split(":")
    event_id = int(event_id_raw)
    event = await repo.get_event(event_id)
    if not event or not await _can_manage(bot, event, callback.from_user.id):
        await callback.answer("Недоступно", show_alert=True)
        return

    if choice == "no":
        await callback.message.edit_text(
            f"Управление мероприятием:\n\n{render_summary(event)}",
            reply_markup=kb.manage_keyboard(event),
        )
        await callback.answer()
        return

    event = await repo.update_event(
        event_id, status="cancelled", cancelled_by=callback.from_user.id
    )
    scheduler.cancel_event_jobs(event_id)
    await roster.refresh_event_message(bot, event_id)
    await pin.refresh_for_event(bot, event)
    note = "Стол отменен ❌"
    if callback.from_user.id == event.creator_id:
        note += "\nПередумаете — под сообщением в теме есть кнопка «♻ Восстановить стол»."
    await callback.message.edit_text(note)
    await callback.answer()


@router.callback_query(F.data.startswith("rst:"))
async def cb_restore(callback: CallbackQuery, bot: Bot) -> None:
    event_id = int(callback.data.split(":")[1])
    event = await repo.get_event(event_id)
    if not event or event.status != "cancelled":
        await callback.answer("Мероприятие не найдено или не отменено", show_alert=True)
        return
    if callback.from_user.id != event.creator_id:
        await callback.answer("Восстановить стол может только его создатель", show_alert=True)
        return
    if event.cancelled_by is not None and event.cancelled_by != event.creator_id:
        await callback.answer(
            "Стол отменён админом — восстановление недоступно", show_alert=True
        )
        return
    # день игры уже закончился — восстанавливать нечего
    tz = await repo.group_tz(event.chat_id)
    if datetime.combine(event.date_ + timedelta(days=1), datetime.min.time(), tzinfo=tz) <= datetime.now(tz):
        await callback.answer("День этого мероприятия уже прошёл", show_alert=True)
        return

    event = await repo.update_event(event_id, status="active", cancelled_by=None)
    await roster.refresh_event_message(bot, event_id)
    await scheduler.schedule_event_jobs(event)
    await pin.refresh_for_event(bot, event)
    await callback.answer("Стол восстановлен ✅ Запись снова открыта")
