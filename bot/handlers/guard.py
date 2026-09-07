"""Команда вместо значения: пока бот ждёт ввод, «/что-то» не должно стать
ником, местом или названием типа.

Роутер подключается первым: иначе /new, /my и /settings разберут свои
хендлеры и молча уронят наполовину заполненную форму, а всё остальное
осядет в базе как значение.
"""
from html import escape

from aiogram import F, Router
from aiogram.filters import StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.types import Message

from bot.handlers.create import CreateForm
from bot.handlers.edit import EditForm
from bot.handlers.profile import FriendForm, NickForm, RegTimeForm
from bot.handlers.settings import TypeForm, TzForm

router = Router()
router.message.filter(F.chat.type == "private")

# что бот ждёт на каждом шаге ввода — винительный падеж:
# «отправили команду, а не дату», «жду дату»
EXPECTED = {
    NickForm.waiting.state: "ник",
    FriendForm.nick.state: "ник друга",
    RegTimeForm.arrive.state: "время",
    RegTimeForm.leave.state: "время",
    CreateForm.date_manual.state: "дату",
    CreateForm.time_.state: "время",
    CreateForm.place.state: "место",
    CreateForm.host.state: "имя ведущего",
    EditForm.date_manual.state: "дату",
    EditForm.time_.state: "время",
    EditForm.place.state: "место",
    EditForm.host.state: "имя ведущего",
    TzForm.name.state: "часовой пояс",
    TypeForm.name.state: "название типа",
}

# /start пропускаем: это и выход из залипшей формы, и вход по ссылке
# из группы (deep link) — перехватим, и выбраться будет нечем
ALLOWED = {"start"}


def command_name(message: Message) -> str | None:
    """Имя команды, если сообщение — команда боту, иначе None.

    Telegram размечает «/что-угодно» в начале строки как bot_command, даже
    незарегистрированное, — на entities полагаться надёжнее, чем на текст.
    Разбор текста оставлен запасным путём: у пересланных и отредактированных
    сообщений разметка приходит не всегда.
    """
    text = message.text or ""
    if not text:
        return None
    marked = any(
        e.type == "bot_command" and e.offset == 0 for e in (message.entities or [])
    )
    if not marked and not text.startswith("/"):
        return None
    return text.split(maxsplit=1)[0][1:].split("@", 1)[0]


def is_blocked_command(message: Message) -> bool:
    name = command_name(message)
    return name is not None and name.lower() not in ALLOWED


@router.message(StateFilter(*EXPECTED), F.text, is_blocked_command)
async def command_instead_of_value(message: Message, state: FSMContext) -> None:
    expected = EXPECTED[await state.get_state()]
    name = command_name(message)
    await message.answer(
        f"Похоже, вы отправили команду <code>/{escape(name)}</code>, а не {expected}.\n"
        f"Жду {expected} обычным текстом. Прервать ввод — /start."
    )
