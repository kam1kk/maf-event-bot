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
from bot.utils import clean_nick, parse_time

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


async def _ask_nick(
    message: Message, state: FSMContext, reg_event_id: int | None, time_flow: bool = False
) -> None:
    await state.set_state(NickForm.waiting)
    await state.update_data(reg_event_id=reg_event_id, time_flow=time_flow)
    await message.answer("Введите ваш игровой ник — я запомню его и буду подставлять при записи:")


async def _open_time_menu(bot: Bot, message: Message, event_id: int, user_id: int, nick: str) -> None:
    """Кнопка «Со временем»: записывает (если ещё не записан) и открывает меню времени.
    Для уже записанного — изменение его текущей записи."""
    event = await repo.get_event(event_id)
    if not event or event.status != "active":
        await message.answer("Запись на это мероприятие закрыта.")
        return
    reg = await repo.get_reg(event_id, user_id)
    header = ""
    if not reg:
        ok, text = await roster.register(bot, event_id, user_id, nick)
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
            ok, text = await roster.register(bot, event_id, message.from_user.id, user.nick)
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
            await _open_time_menu(bot, message, event_id, message.from_user.id, user.nick)
        else:
            await _ask_nick(message, state, event_id, time_flow=True)
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
        await _open_time_menu(bot, message, reg_event_id, message.from_user.id, nick)
    elif reg_event_id:
        ok, text = await roster.register(bot, reg_event_id, message.from_user.id, nick)
        await message.answer(f"Ник сохранён: <b>{escape(nick)}</b>\n{text}")
    else:
        await message.answer(f"Ник сохранён: <b>{escape(nick)}</b> ✅")


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
async def cb_my_reg(callback: CallbackQuery) -> None:
    reg_id = int(callback.data.split(":")[1])
    reg = await repo.get_reg_by_id(reg_id)
    if not reg or reg.user_id != callback.from_user.id:
        await callback.answer("Запись не найдена", show_alert=True)
        return
    event = await repo.get_event(reg.event_id)
    if not event or event.status != "active":
        await callback.answer("Запись на это мероприятие уже закрыта", show_alert=True)
        return
    await callback.message.edit_text(
        f"{render_summary(event)}\n\nВы записаны как <b>{escape(reg.nick)}</b>. Что сделать?",
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
    if not reg or reg.user_id != callback.from_user.id:
        await callback.answer("Запись не найдена", show_alert=True)
        return
    event = await repo.get_event(reg.event_id)
    if not event or event.status != "active":
        await callback.answer("Запись на это мероприятие уже закрыта", show_alert=True)
        return

    if action == "arrive":
        await state.set_state(RegTimeForm.arrive)
        await state.update_data(reg_id=reg_id)
        await callback.message.edit_text(
            "К какому времени придёте? Введите время (например, 19:30):"
        )
    elif action == "leave":
        await state.set_state(RegTimeForm.leave)
        await state.update_data(reg_id=reg_id)
        await callback.message.edit_text(
            "До какого времени будете? Введите время (например, 21:00):"
        )
    elif action == "reset":
        await repo.update_reg(reg_id, category="main", arrive_time=None, leave_time=None)
        await roster.refresh_event_message(bot, event.id)
        await callback.message.edit_text("Время сброшено — вы в основном составе ✅")
    elif action == "unreg":
        await repo.delete_reg(reg_id)
        await roster.refresh_event_message(bot, event.id)
        await callback.message.edit_text("Вы выписаны 🚪")
    await callback.answer()


@router.message(RegTimeForm.arrive, F.text)
async def input_arrive(message: Message, state: FSMContext, bot: Bot) -> None:
    t = parse_time(message.text)
    if not t:
        await message.answer("Не понял время. Формат: <b>ЧЧ:ММ</b>, например 19:30")
        return
    data = await state.get_data()
    await state.clear()
    reg = await repo.update_reg(data["reg_id"], category="late", arrive_time=t)
    if reg:
        await roster.refresh_event_message(bot, reg.event_id)
        await message.answer(
            f"Отметил: придёте к {message.text.strip()} — вы в списке «Опоздавшие» ✅",
            reply_markup=kb.my_reg_menu_keyboard(reg),
        )


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
        await message.answer(
            f"Отметил: будете до {message.text.strip()} ✅",
            reply_markup=kb.my_reg_menu_keyboard(reg),
        )
