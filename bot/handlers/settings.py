from datetime import datetime
from html import escape
from zoneinfo import ZoneInfo

from aiogram import Bot, F, Router
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import CallbackQuery, Message

from bot import config
from bot import keyboards as kb
from bot.db import repo
from bot.db.models import Group
from bot.services import membership
from bot.services import scheduler as sched

router = Router()
router.message.filter(F.chat.type == "private")


class TypeForm(StatesGroup):
    name = State()


class TzForm(StatesGroup):
    name = State()


def _bind_status(chat_id: int | None) -> str:
    return "привязана ✅" if chat_id else "не привязана ⚠"


async def _settings_text(group: Group) -> str:
    tz = await repo.group_tz(group.chat_id)
    now = datetime.now(tz).strftime("%H:%M")
    tz_label = group.timezone or f"{tz} (по умолчанию)"
    lines = [
        f"<b>Настройки группы «{escape(group.title or str(group.chat_id))}»</b>",
        "",
        f"🌍 Часовой пояс: <b>{escape(str(tz_label))}</b> (сейчас {now})",
        "",
        "<b>Типы мероприятий:</b>",
        "",
    ]
    for et in await repo.list_types(group.chat_id):
        star = "⭐ " if et.is_default else ""
        lines.append(f"{star}<b>{escape(et.name)}</b>")
        lines.append(f"    тема публикации: {_bind_status(et.chat_id)}")
        lines.append(f"    тема напоминаний: {_bind_status(et.remind_chat_id)}")
    lines.append("")
    lines.append("Привязка тем — командами в нужной теме группы:")
    lines.append("<code>/bind &lt;тип&gt;</code> — где публикуются мероприятия")
    lines.append("<code>/bind_remind &lt;тип&gt;</code> — куда приходят напоминания")
    return "\n".join(lines)


async def _apply_tz(group_chat_id: int, name: str) -> str | None:
    """Сохраняет пояс группы, перепланирует задачи её активных мероприятий.
    Возвращает текст подтверждения или None, если имя пояса некорректно."""
    try:
        tz = ZoneInfo(name)
    except Exception:
        return None
    await repo.set_group_timezone(group_chat_id, name)
    for event in await repo.list_active_events(group_chat_id):
        await sched.reschedule(event)
    now = datetime.now(tz).strftime("%H:%M")
    return f"Часовой пояс группы установлен: <b>{escape(name)}</b>, сейчас {now} ✅"


@router.message(Command("settings"))
async def cmd_settings(message: Message, state: FSMContext, bot: Bot) -> None:
    await state.clear()
    groups = await membership.user_groups(bot, message.from_user.id)
    if not groups:
        await message.answer(
            "Я не вижу вас ни в одной группе, где я работаю. "
            "Убедитесь, что вы состоите в группе и бот туда добавлен."
        )
        return
    if len(groups) == 1:
        await message.answer(
            await _settings_text(groups[0]),
            reply_markup=kb.settings_keyboard(groups[0].chat_id),
        )
        return
    await message.answer(
        "Настройки какой группы открыть?",
        reply_markup=kb.group_picker_keyboard(groups, "sg"),
    )


@router.callback_query(F.data.startswith("sg:"))
async def cb_settings_group(callback: CallbackQuery, state: FSMContext) -> None:
    await state.clear()
    group = await repo.get_group(int(callback.data.split(":")[1]))
    if not group:
        await callback.answer("Группа не найдена", show_alert=True)
        return
    await callback.message.edit_text(
        await _settings_text(group), reply_markup=kb.settings_keyboard(group.chat_id)
    )
    await callback.answer()


# ---------- часовой пояс ----------

@router.callback_query(F.data.startswith("st:tz:"))
async def cb_tz_menu(callback: CallbackQuery) -> None:
    group_chat_id = int(callback.data.split(":")[2])
    await callback.message.edit_text(
        "Выберите часовой пояс группы (по нему закрывается запись и приходят напоминания):",
        reply_markup=kb.tz_keyboard(group_chat_id),
    )
    await callback.answer()


@router.callback_query(F.data.startswith("tzset:"))
async def cb_tz_set(callback: CallbackQuery) -> None:
    _, group_chat_id_raw, name = callback.data.split(":", 2)
    note = await _apply_tz(int(group_chat_id_raw), name)
    if not note:
        await callback.answer("Неизвестный часовой пояс", show_alert=True)
        return
    await callback.message.edit_text(note)
    await callback.answer()


@router.callback_query(F.data.startswith("st:tzm:"))
async def cb_tz_manual(callback: CallbackQuery, state: FSMContext) -> None:
    group_chat_id = int(callback.data.split(":")[2])
    await state.set_state(TzForm.name)
    await state.update_data(group_chat_id=group_chat_id)
    await callback.message.edit_text(
        "Введите название часового пояса в формате IANA, например "
        "<code>Asia/Yekaterinburg</code> или <code>Europe/Moscow</code>:"
    )
    await callback.answer()


@router.message(TzForm.name, F.text)
async def input_tz_name(message: Message, state: FSMContext) -> None:
    data = await state.get_data()
    note = await _apply_tz(data["group_chat_id"], message.text.strip())
    if not note:
        await message.answer(
            "Не знаю такой пояс. Формат IANA, например <code>Asia/Novosibirsk</code>. Попробуйте ещё раз:"
        )
        return
    await state.clear()
    await message.answer(note)


# ---------- типы мероприятий ----------

@router.callback_query(F.data.startswith("st:add:"))
async def cb_add_type(callback: CallbackQuery, state: FSMContext) -> None:
    group_chat_id = int(callback.data.split(":")[2])
    await state.set_state(TypeForm.name)
    await state.update_data(group_chat_id=group_chat_id)
    await callback.message.answer("Введите название нового типа мероприятия:")
    await callback.answer()


@router.message(TypeForm.name, F.text)
async def input_type_name(message: Message, state: FSMContext) -> None:
    name = " ".join(message.text.split())
    if not name or len(name) > 64:
        await message.answer("Название должно быть не длиннее 64 символов. Попробуйте ещё раз:")
        return
    data = await state.get_data()
    event_type = await repo.add_type(data["group_chat_id"], name)
    await state.clear()
    if not event_type:
        await message.answer(f"Тип «{escape(name)}» уже существует в этой группе.")
        return
    await message.answer(
        f"Тип «{escape(name)}» создан ✅\n\n"
        f"Теперь отправьте <code>/bind {escape(name)}</code> в той теме группы, "
        f"где должны публиковаться эти мероприятия."
    )
