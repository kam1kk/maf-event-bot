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
    mode = "только админы" if group.only_admins_create else "все участники"
    lines = [
        f"<b>Настройки группы «{escape(group.title or str(group.chat_id))}»</b>",
        "",
        f"🌍 Часовой пояс: <b>{escape(str(tz_label))}</b> (сейчас {now})",
        f"🎛 Создавать мероприятия могут: <b>{mode}</b>",
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
    groups = await membership.admin_groups(bot, message.from_user.id)
    if not groups:
        await message.answer(
            "Настройки группы доступны только админам бота. "
            "Права выдаёт администратор группы командой /promote (ответом на ваше сообщение)."
        )
        return
    if len(groups) == 1:
        await message.answer(
            await _settings_text(groups[0]),
            reply_markup=kb.settings_keyboard(groups[0]),
        )
        return
    await message.answer(
        "Настройки какой группы открыть?",
        reply_markup=kb.group_picker_keyboard(groups, "sg"),
    )


async def _admin_group_or_alert(callback: CallbackQuery, bot: Bot, chat_id: int) -> Group | None:
    group = await repo.get_group(chat_id)
    if not group:
        await callback.answer("Группа не найдена", show_alert=True)
        return None
    if not await membership.is_bot_admin(bot, chat_id, callback.from_user.id):
        await callback.answer("Доступно только админам бота этой группы", show_alert=True)
        return None
    return group


@router.callback_query(F.data.startswith("sg:"))
async def cb_settings_group(callback: CallbackQuery, state: FSMContext, bot: Bot) -> None:
    await state.clear()
    group = await _admin_group_or_alert(callback, bot, int(callback.data.split(":")[1]))
    if not group:
        return
    await callback.message.edit_text(
        await _settings_text(group), reply_markup=kb.settings_keyboard(group)
    )
    await callback.answer()


@router.callback_query(F.data.startswith("st:mode:"))
async def cb_toggle_mode(callback: CallbackQuery, bot: Bot) -> None:
    group = await _admin_group_or_alert(callback, bot, int(callback.data.split(":")[2]))
    if not group:
        return
    await repo.set_group_creation_mode(group.chat_id, not group.only_admins_create)
    group = await repo.get_group(group.chat_id)
    await callback.message.edit_text(
        await _settings_text(group), reply_markup=kb.settings_keyboard(group)
    )
    await callback.answer()


@router.callback_query(F.data.startswith("st:adm:"))
async def cb_admins(callback: CallbackQuery, bot: Bot) -> None:
    group = await _admin_group_or_alert(callback, bot, int(callback.data.split(":")[2]))
    if not group:
        return
    admins = await repo.list_group_admins(group.chat_id)
    if admins:
        text = (
            "Админы бота, назначенные вручную (нажмите, чтобы снять права):\n\n"
            "Администраторы группы Telegram — админы бота автоматически."
        )
    else:
        text = (
            "Вручную назначенных админов бота нет.\n\n"
            "Выдать права: администратор группы отвечает командой /promote "
            "на сообщение участника в группе.\n"
            "Администраторы группы Telegram — админы бота автоматически."
        )
    await callback.message.edit_text(text, reply_markup=kb.admins_keyboard(group.chat_id, admins))
    await callback.answer()


@router.callback_query(F.data.startswith("unadm:"))
async def cb_remove_admin(callback: CallbackQuery, bot: Bot) -> None:
    _, chat_id_raw, user_id_raw = callback.data.split(":")
    chat_id, user_id = int(chat_id_raw), int(user_id_raw)
    # снимать права могут только Telegram-админы группы
    if not await membership.is_tg_admin(bot, chat_id, callback.from_user.id):
        await callback.answer("Снимать права могут только администраторы группы", show_alert=True)
        return
    await repo.remove_group_admin(chat_id, user_id)
    admins = await repo.list_group_admins(chat_id)
    await callback.message.edit_text(
        "Права сняты ✅" + ("\n\nОставшиеся админы бота:" if admins else "\n\nВручную назначенных админов больше нет."),
        reply_markup=kb.admins_keyboard(chat_id, admins),
    )
    await callback.answer()


# ---------- часовой пояс ----------

@router.callback_query(F.data.startswith("st:tz:"))
async def cb_tz_menu(callback: CallbackQuery, bot: Bot) -> None:
    group = await _admin_group_or_alert(callback, bot, int(callback.data.split(":")[2]))
    if not group:
        return
    await callback.message.edit_text(
        "Выберите часовой пояс группы (по нему закрывается запись и приходят напоминания):",
        reply_markup=kb.tz_keyboard(group.chat_id),
    )
    await callback.answer()


@router.callback_query(F.data.startswith("tzset:"))
async def cb_tz_set(callback: CallbackQuery, bot: Bot) -> None:
    _, group_chat_id_raw, name = callback.data.split(":", 2)
    group = await _admin_group_or_alert(callback, bot, int(group_chat_id_raw))
    if not group:
        return
    note = await _apply_tz(group.chat_id, name)
    if not note:
        await callback.answer("Неизвестный часовой пояс", show_alert=True)
        return
    await callback.message.edit_text(note)
    await callback.answer()


@router.callback_query(F.data.startswith("st:tzm:"))
async def cb_tz_manual(callback: CallbackQuery, state: FSMContext, bot: Bot) -> None:
    group = await _admin_group_or_alert(callback, bot, int(callback.data.split(":")[2]))
    if not group:
        return
    group_chat_id = group.chat_id
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
async def cb_add_type(callback: CallbackQuery, state: FSMContext, bot: Bot) -> None:
    group = await _admin_group_or_alert(callback, bot, int(callback.data.split(":")[2]))
    if not group:
        return
    await state.set_state(TypeForm.name)
    await state.update_data(group_chat_id=group.chat_id)
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
