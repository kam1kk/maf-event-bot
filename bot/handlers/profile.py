from aiogram import Bot, F, Router
from aiogram.filters import Command, CommandObject, CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import CallbackQuery, Message

from html import escape

from bot import keyboards as kb
from bot.db import repo
from bot.services import roster
from bot.services.render import render_summary
from bot.utils import clean_nick, fmt_time, parse_time

router = Router()
router.message.filter(F.chat.type == "private")

WELCOME = (
    "Привет! Я бот для записи на игры.\n\n"
    "/new — создать мероприятие\n"
    "/my — мои записи (опоздаю / уйду раньше / выписаться)\n"
    "/nick — сменить игровой ник\n"
    "/settings — типы мероприятий и привязка тем"
)


class NickForm(StatesGroup):
    waiting = State()


class RegTimeForm(StatesGroup):
    arrive = State()
    leave = State()


class FriendForm(StatesGroup):
    nick = State()


def _owns_reg(reg, user_id: int) -> bool:
    """Своя запись или гость, которого этот пользователь добавил."""
    return reg.user_id == user_id or (reg.user_id is None and reg.added_by == user_id)


async def _ask_nick(
    message: Message, state: FSMContext, reg_event_id: int | None, time_flow: bool = False
) -> None:
    await state.set_state(NickForm.waiting)
    await state.update_data(reg_event_id=reg_event_id, time_flow=time_flow)
    await message.answer("Введите ваш игровой ник — я запомню его и буду подставлять при записи:")


async def _open_time_menu(
    bot: Bot, message: Message, event_id: int, user_id: int, nick: str, username: str | None = None
) -> None:
    """Кнопка «Со временем»: записывает (если ещё не записан) и открывает меню времени.
    Для уже записанного — изменение его текущей записи."""
    event = await repo.get_event(event_id)
    if not event or event.status != "active":
        await message.answer("Запись на это мероприятие закрыта.")
        return
    reg = await repo.get_reg(event_id, user_id)
    header = ""
    if not reg:
        ok, text = await roster.register(bot, event_id, user_id, nick, username)
        if not ok:
            await message.answer(text)
            return
        reg = await repo.get_reg(event_id, user_id)
        header = "Вы записаны ✅\n\n"
    await message.answer(
        f"{header}{render_summary(event)}\n\n"
        f"Запись: <b>{escape(reg.nick)}</b>. Укажите время:",
        reply_markup=kb.my_reg_menu_keyboard(reg),
    )


@router.message(CommandStart(deep_link=True))
async def cmd_start_deeplink(message: Message, command: CommandObject, state: FSMContext, bot: Bot) -> None:
    await state.clear()
    user = await repo.get_or_create_user(message.from_user.id)
    args = command.args or ""

    if args.startswith("reg_"):
        try:
            event_id = int(args[4:])
        except ValueError:
            await message.answer(WELCOME)
            return
        if user.nick:
            ok, text = await roster.register(
                bot, event_id, message.from_user.id, user.nick, message.from_user.username
            )
            await message.answer(text)
        else:
            await _ask_nick(message, state, event_id)
        return

    if args.startswith("time_"):
        try:
            event_id = int(args[5:])
        except ValueError:
            await message.answer(WELCOME)
            return
        if user.nick:
            await _open_time_menu(
                bot, message, event_id, message.from_user.id, user.nick,
                message.from_user.username,
            )
        else:
            await _ask_nick(message, state, event_id, time_flow=True)
        return

    if args.startswith("friend_"):
        try:
            event_id = int(args[7:])
        except ValueError:
            await message.answer(WELCOME)
            return
        event = await repo.get_event(event_id)
        if not event or event.status != "active":
            await message.answer("Запись на это мероприятие закрыта.")
            return
        await state.set_state(FriendForm.nick)
        await state.update_data(friend_event_id=event_id)
        await message.answer(
            "Введите ник друга, которого записываете:",
            reply_markup=kb.cancel_friend_keyboard(),
        )
        return

    if args.startswith("frsl_"):
        try:
            event_id = int(args[5:])
        except ValueError:
            await message.answer(WELCOME)
            return
        event = await repo.get_event(event_id)
        if not event or event.status != "active":
            await message.answer("Запись на это мероприятие закрыта.")
            return
        own = await repo.get_reg(event_id, message.from_user.id)
        if not own:
            await message.answer(
                "Сначала запишитесь сами — друг «через /» добавляется к вашей записи."
            )
            return
        await state.set_state(FriendForm.nick)
        await state.update_data(friend_event_id=event_id, slash=True)
        await message.answer(
            f"Введите ник друга — он попадёт в вашу строку: <b>{escape(own.nick)}/ник</b>:",
            reply_markup=kb.cancel_friend_keyboard(),
        )
        return

    if args.startswith("unfriend_"):
        try:
            event_id = int(args[9:])
        except ValueError:
            await message.answer(WELCOME)
            return
        guests = await repo.get_guest_regs(event_id, message.from_user.id)
        if not guests:
            await message.answer("Вы не записывали друзей на это мероприятие.")
            return
        await message.answer(
            "Кого из друзей выписать?",
            reply_markup=kb.unfriend_keyboard(event_id, guests),
        )
        return

    if args.startswith("new_"):
        # «Создать мероприятие» из темы группы
        from bot.handlers.create import start_from_deeplink
        await start_from_deeplink(message, state, bot, args)
        return

    if args.startswith("mng_"):
        # запасной вход в меню управления, если личка была закрыта
        from bot.handlers.edit import send_manage_menu
        try:
            event_id = int(args[4:])
        except ValueError:
            await message.answer(WELCOME)
            return
        await send_manage_menu(bot, message.from_user.id, event_id)
        return

    await message.answer(WELCOME)


@router.message(CommandStart())
async def cmd_start(message: Message, state: FSMContext) -> None:
    await state.clear()
    user = await repo.get_or_create_user(message.from_user.id)
    await message.answer(WELCOME)
    if not user.nick:
        await _ask_nick(message, state, None)


@router.message(Command("nick"))
async def cmd_nick(message: Message, state: FSMContext) -> None:
    await state.clear()
    await repo.get_or_create_user(message.from_user.id)
    await state.set_state(NickForm.waiting)
    await state.update_data(reg_event_id=None)
    await message.answer(
        "Введите новый ник. Он будет использоваться в <b>будущих</b> записях, "
        "уже существующие не изменятся:"
    )


@router.message(NickForm.waiting, F.text)
async def input_nick(message: Message, state: FSMContext, bot: Bot) -> None:
    nick = clean_nick(message.text)
    if not nick:
        await message.answer("Ник должен быть не длиннее 32 символов. Попробуйте ещё раз:")
        return
    await repo.set_nick(message.from_user.id, nick)
    data = await state.get_data()
    await state.clear()

    reg_event_id = data.get("reg_event_id")
    if reg_event_id and data.get("time_flow"):
        await message.answer(f"Ник сохранён: <b>{escape(nick)}</b> ✅")
        await _open_time_menu(
            bot, message, reg_event_id, message.from_user.id, nick,
            message.from_user.username,
        )
    elif reg_event_id:
        ok, text = await roster.register(
            bot, reg_event_id, message.from_user.id, nick, message.from_user.username
        )
        await message.answer(f"Ник сохранён: <b>{escape(nick)}</b>\n{text}")
    else:
        await message.answer(f"Ник сохранён: <b>{escape(nick)}</b> ✅")


@router.message(FriendForm.nick, F.text)
async def input_friend_nick(message: Message, state: FSMContext, bot: Bot) -> None:
    nick = clean_nick(message.text)
    if not nick:
        await message.answer(
            "Ник должен быть не длиннее 32 символов. Попробуйте ещё раз:",
            reply_markup=kb.cancel_friend_keyboard(),
        )
        return
    data = await state.get_data()
    await state.clear()
    event_id = data["friend_event_id"]
    event = await repo.get_event(event_id)
    if not event or event.status != "active":
        await message.answer("Запись на это мероприятие уже закрыта.")
        return
    if data.get("slash"):
        own = await repo.get_reg(event_id, message.from_user.id)
        if not own:
            # выписался, пока вводил ник
            await message.answer(
                "Вы не записаны на это мероприятие — запись «через /» невозможна."
            )
            return
        await repo.add_reg(event_id, None, message.from_user.id, nick, attached_to=own.id)
        await roster.refresh_event_message(bot, event_id)
        await message.answer(
            f"Записаны вместе: <b>{escape(own.nick)}/{escape(nick)}</b> ✅\n\n"
            f"{render_summary(event)}"
        )
        return
    reg = await repo.add_reg(event_id, None, message.from_user.id, nick)
    await roster.refresh_event_message(bot, event_id)
    await message.answer(
        f"Друг <b>{escape(nick)}</b> записан ✅\n\n{render_summary(event)}\n\n"
        f"Можно сразу указать время:",
        reply_markup=kb.my_reg_menu_keyboard(reg),
    )


@router.callback_query(F.data == "frx")
async def cb_friend_cancel(callback: CallbackQuery, state: FSMContext) -> None:
    await state.clear()
    await callback.message.edit_text("Запись друга отменена.")
    await callback.answer()


@router.callback_query(F.data.startswith("unfr:"))
async def cb_unfriend_pick(callback: CallbackQuery, bot: Bot) -> None:
    _, event_id_raw, reg_id_raw = callback.data.split(":")
    event_id, reg_id = int(event_id_raw), int(reg_id_raw)
    reg = await repo.get_reg_by_id(reg_id)
    if not reg or reg.user_id is not None or reg.added_by != callback.from_user.id:
        await callback.answer("Запись не найдена", show_alert=True)
        return
    await repo.delete_reg(reg_id)
    await roster.refresh_event_message(bot, event_id)
    guests = await repo.get_guest_regs(event_id, callback.from_user.id)
    if guests:
        await callback.message.edit_text(
            f"Выписан: <b>{escape(reg.nick)}</b> ✅\n\nКого из друзей выписать?",
            reply_markup=kb.unfriend_keyboard(event_id, guests),
        )
    else:
        await callback.message.edit_text(f"Выписан: <b>{escape(reg.nick)}</b> ✅")
    await callback.answer()


# ---------- мои записи ----------

@router.message(Command("my"))
async def cmd_my(message: Message, state: FSMContext) -> None:
    await state.clear()
    items = await repo.list_user_regs_on_active(message.from_user.id)
    if not items:
        await message.answer("У вас нет активных записей.")
        return
    await message.answer("Ваши записи — выберите мероприятие:", reply_markup=kb.my_regs_keyboard(items))


@router.callback_query(F.data.startswith("my:"))
async def cb_my_reg(callback: CallbackQuery, state: FSMContext) -> None:
    # сюда же ведёт «Назад» из ввода времени — сбрасываем ожидание текста
    await state.clear()
    reg_id = int(callback.data.split(":")[1])
    reg = await repo.get_reg_by_id(reg_id)
    if not reg or not _owns_reg(reg, callback.from_user.id):
        await callback.answer("Запись не найдена", show_alert=True)
        return
    event = await repo.get_event(reg.event_id)
    if not event or event.status != "active":
        await callback.answer("Запись на это мероприятие уже закрыта", show_alert=True)
        return
    if reg.user_id is None and reg.attached_to is not None:
        who = f"Ваш друг: <b>{escape(reg.nick)}</b> (записан к вам через /)"
    elif reg.user_id is None:
        who = f"Ваш друг: <b>{escape(reg.nick)}</b>"
    else:
        who = f"Вы записаны как <b>{escape(reg.nick)}</b>"
    await callback.message.edit_text(
        f"{render_summary(event)}\n\n{who}. Что сделать?",
        reply_markup=kb.my_reg_menu_keyboard(reg),
    )
    await callback.answer()


@router.callback_query(F.data == "myr:back")
async def cb_my_back(callback: CallbackQuery) -> None:
    items = await repo.list_user_regs_on_active(callback.from_user.id)
    if not items:
        await callback.message.edit_text("У вас нет активных записей.")
    else:
        await callback.message.edit_text(
            "Ваши записи — выберите мероприятие:", reply_markup=kb.my_regs_keyboard(items)
        )
    await callback.answer()


@router.callback_query(F.data.startswith("myr:"))
async def cb_my_action(callback: CallbackQuery, state: FSMContext, bot: Bot) -> None:
    _, reg_id_raw, action = callback.data.split(":")
    reg_id = int(reg_id_raw)
    reg = await repo.get_reg_by_id(reg_id)
    if not reg or not _owns_reg(reg, callback.from_user.id):
        await callback.answer("Запись не найдена", show_alert=True)
        return
    event = await repo.get_event(reg.event_id)
    if not event or event.status != "active":
        await callback.answer("Запись на это мероприятие уже закрыта", show_alert=True)
        return

    # у друга «через /» своей строки нет — время задаётся только у хозяина
    if reg.attached_to is not None and action in ("arrive", "leave", "reset"):
        await callback.answer(
            "У записи «через /» время общее с вашей. Чтобы задать своё — "
            "выпишите друга и запишите отдельной строкой.",
            show_alert=True,
        )
        return

    if action == "arrive":
        await state.set_state(RegTimeForm.arrive)
        await state.update_data(reg_id=reg_id)
        await callback.message.edit_text(
            "К какому времени придёте? Введите время (например, 19:30):",
            reply_markup=kb.back_to_reg_keyboard(reg_id),
        )
    elif action == "leave":
        await state.set_state(RegTimeForm.leave)
        await state.update_data(reg_id=reg_id)
        await callback.message.edit_text(
            "До какого времени будете? Введите время (например, 21:00):",
            reply_markup=kb.back_to_reg_keyboard(reg_id),
        )
    elif action == "reset":
        await repo.update_reg(reg_id, category="main", arrive_time=None, leave_time=None)
        await roster.refresh_event_message(bot, event.id)
        note = "Время сброшено — запись в основном составе ✅" if reg.user_id is None \
            else "Время сброшено — вы в основном составе ✅"
        await callback.message.edit_text(note)
    elif action == "unreg":
        await repo.delete_reg(reg_id)
        await roster.refresh_event_message(bot, event.id)
        note = f"Друг <b>{escape(reg.nick)}</b> выписан 🚪" if reg.user_id is None else "Вы выписаны 🚪"
        await callback.message.edit_text(note)
    await callback.answer()


@router.message(RegTimeForm.arrive, F.text)
async def input_arrive(message: Message, state: FSMContext, bot: Bot) -> None:
    data = await state.get_data()
    reg_id = data["reg_id"]
    t = parse_time(message.text)
    if not t:
        await message.answer(
            "Не понял время. Формат: <b>ЧЧ:ММ</b>, например 19:30",
            reply_markup=kb.back_to_reg_keyboard(reg_id),
        )
        return
    reg = await repo.get_reg_by_id(reg_id)
    event = await repo.get_event(reg.event_id) if reg else None
    if event and t <= event.time_:
        # «приду позже» раньше начала — не опоздание; состав определяется временем стола
        await message.answer(
            f"Мероприятие начинается в <b>{fmt_time(event.time_)}</b> — "
            f"время опоздания должно быть позже начала.\n"
            f"Введите время после {fmt_time(event.time_)}, "
            f"а если успеваете вовремя — вернитесь назад.",
            reply_markup=kb.back_to_reg_keyboard(reg_id),
        )
        return
    await state.clear()
    reg = await repo.update_reg(reg_id, category="late", arrive_time=t)
    if reg:
        await roster.refresh_event_message(bot, reg.event_id)
        note = (
            f"Отметил: <b>{escape(reg.nick)}</b> придёт к {message.text.strip()} — запись в списке «Опоздавшие» ✅"
            if reg.user_id is None
            else f"Отметил: придёте к {message.text.strip()} — вы в списке «Опоздавшие» ✅"
        )
        await message.answer(note, reply_markup=kb.my_reg_menu_keyboard(reg))


@router.message(RegTimeForm.leave, F.text)
async def input_leave(message: Message, state: FSMContext, bot: Bot) -> None:
    t = parse_time(message.text)
    if not t:
        await message.answer("Не понял время. Формат: <b>ЧЧ:ММ</b>, например 21:00")
        return
    data = await state.get_data()
    await state.clear()
    reg = await repo.update_reg(data["reg_id"], leave_time=t)
    if reg:
        await roster.refresh_event_message(bot, reg.event_id)
        note = (
            f"Отметил: <b>{escape(reg.nick)}</b> будет до {message.text.strip()} ✅"
            if reg.user_id is None
            else f"Отметил: будете до {message.text.strip()} ✅"
        )
        await message.answer(note, reply_markup=kb.my_reg_menu_keyboard(reg))
