from datetime import datetime
from html import escape
from zoneinfo import ZoneInfo

from aiogram import F, Router
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import CallbackQuery, Message

from bot import config
from bot import keyboards as kb
from bot.db import repo
from bot.services import scheduler as sched

router = Router()
router.message.filter(F.chat.type == "private")


class TypeForm(StatesGroup):
    name = State()


class TzForm(StatesGroup):
    name = State()


async def _apply_tz(name: str) -> str | None:
    """Сохраняет пояс, применяет его и перепланирует задачи активных мероприятий.
    Возвращает текст подтверждения или None, если имя пояса некорректно."""
    try:
        tz = ZoneInfo(name)
    except Exception:
        return None
    await repo.set_setting("timezone", name)
    config.set_tz(tz)
    for event in await repo.list_active_events():
        sched.reschedule(event)
    now = datetime.now(tz).strftime("%H:%M")
    return f"Часовой пояс установлен: <b>{escape(name)}</b>, сейчас {now} ✅"


def _bind_status(chat_id: int | None) -> str:
    return "привязана ✅" if chat_id else "не привязана ⚠"


async def _settings_text() -> str:
    tz = config.get_tz()
    now = datetime.now(tz).strftime("%H:%M")
    lines = [
        f"🌍 Часовой пояс: <b>{escape(str(tz))}</b> (сейчас {now})",
        "",
        "<b>Типы мероприятий:</b>",
        "",
    ]
    for et in await repo.list_types():
        star = "⭐ " if et.is_default else ""
        lines.append(f"{star}<b>{escape(et.name)}</b>")
        lines.append(f"    тема публикации: {_bind_status(et.chat_id)}")
        lines.append(f"    тема напоминаний: {_bind_status(et.remind_chat_id)}")
    lines.append("")
    lines.append("Привязка тем — командами в нужной теме группы:")
    lines.append("<code>/bind &lt;тип&gt;</code> — где публикуются мероприятия")
    lines.append("<code>/bind_remind &lt;тип&gt;</code> — куда приходят напоминания")
    return "\n".join(lines)


@router.message(Command("settings"))
async def cmd_settings(message: Message, state: FSMContext) -> None:
    await state.clear()
    await message.answer(await _settings_text(), reply_markup=kb.settings_keyboard())


@router.callback_query(F.data == "st:tz")
async def cb_tz_menu(callback: CallbackQuery) -> None:
    await callback.message.edit_text(
        "Выберите часовой пояс клуба (по нему закрывается запись и приходят напоминания):",
        reply_markup=kb.tz_keyboard(),
    )
    await callback.answer()


@router.callback_query(F.data.startswith("tzset:"))
async def cb_tz_set(callback: CallbackQuery) -> None:
    name = callback.data.split(":", 1)[1]
    note = await _apply_tz(name)
    if not note:
        await callback.answer("Неизвестный часовой пояс", show_alert=True)
        return
    await callback.message.edit_text(note)
    await callback.answer()


@router.callback_query(F.data == "st:tzmanual")
async def cb_tz_manual(callback: CallbackQuery, state: FSMContext) -> None:
    await state.set_state(TzForm.name)
    await callback.message.edit_text(
        "Введите название часового пояса в формате IANA, например "
        "<code>Asia/Yekaterinburg</code> или <code>Europe/Moscow</code>:"
    )
    await callback.answer()


@router.message(TzForm.name, F.text)
async def input_tz_name(message: Message, state: FSMContext) -> None:
    note = await _apply_tz(message.text.strip())
    if not note:
        await message.answer(
            "Не знаю такой пояс. Формат IANA, например <code>Asia/Novosibirsk</code>. Попробуйте ещё раз:"
        )
        return
    await state.clear()
    await message.answer(note)


@router.callback_query(F.data == "st:add")
async def cb_add_type(callback: CallbackQuery, state: FSMContext) -> None:
    await state.set_state(TypeForm.name)
    await callback.message.answer("Введите название нового типа мероприятия:")
    await callback.answer()


@router.message(TypeForm.name, F.text)
async def input_type_name(message: Message, state: FSMContext) -> None:
    name = " ".join(message.text.split())
    if not name or len(name) > 64:
        await message.answer("Название должно быть не длиннее 64 символов. Попробуйте ещё раз:")
        return
    event_type = await repo.add_type(name)
    await state.clear()
    if not event_type:
        await message.answer(f"Тип «{escape(name)}» уже существует.")
        return
    await message.answer(
        f"Тип «{escape(name)}» создан ✅\n\n"
        f"Теперь отправьте <code>/bind {escape(name)}</code> в той теме группы, "
        f"где должны публиковаться эти мероприятия."
    )
