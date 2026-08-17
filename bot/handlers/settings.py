from html import escape

from aiogram import F, Router
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import CallbackQuery, Message

from bot import keyboards as kb
from bot.db import repo

router = Router()
router.message.filter(F.chat.type == "private")


class TypeForm(StatesGroup):
    name = State()


def _bind_status(chat_id: int | None) -> str:
    return "привязана ✅" if chat_id else "не привязана ⚠"


async def _settings_text() -> str:
    lines = ["<b>Типы мероприятий:</b>", ""]
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
