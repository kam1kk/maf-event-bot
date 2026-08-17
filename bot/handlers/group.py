from aiogram import Bot, F, Router
from aiogram.filters import Command, CommandObject
from aiogram.types import CallbackQuery, Message

from bot.db import repo
from bot.services import roster

router = Router()


# ---------- кнопки под сообщением мероприятия ----------

@router.callback_query(F.data.startswith("reg:"))
async def cb_register(callback: CallbackQuery, bot: Bot) -> None:
    event_id = int(callback.data.split(":")[1])
    event = await repo.get_event(event_id)
    if not event or event.status != "active":
        await callback.answer("Запись закрыта", show_alert=True)
        return

    user = await repo.get_or_create_user(callback.from_user.id)
    if not user.nick:
        # текстовый ввод из группы невозможен — уводим в личку deep-link'ом,
        # после ввода ника бот сам допишет человека на это мероприятие
        me = await bot.get_me()
        await callback.answer(url=f"https://t.me/{me.username}?start=reg_{event_id}")
        return

    ok, text = await roster.register(bot, event_id, callback.from_user.id, user.nick)
    await callback.answer(text, show_alert=not ok)


@router.callback_query(F.data.startswith("regt:"))
async def cb_register_timed(callback: CallbackQuery, bot: Bot) -> None:
    """Запись с указанием времени: выбор опций возможен только в личке,
    поэтому всегда уводим deep-link'ом. Если человек уже записан —
    в личке откроется изменение его записи."""
    event_id = int(callback.data.split(":")[1])
    event = await repo.get_event(event_id)
    if not event or event.status != "active":
        await callback.answer("Запись закрыта", show_alert=True)
        return
    me = await bot.get_me()
    await callback.answer(url=f"https://t.me/{me.username}?start=time_{event_id}")


@router.callback_query(F.data.startswith("unreg:"))
async def cb_unregister(callback: CallbackQuery, bot: Bot) -> None:
    event_id = int(callback.data.split(":")[1])
    ok, text = await roster.unregister(bot, event_id, callback.from_user.id)
    await callback.answer(text, show_alert=not ok)


# ---------- привязка тем ----------

@router.message(Command("bind"), F.chat.type.in_({"group", "supergroup"}))
async def cmd_bind(message: Message, command: CommandObject) -> None:
    name = (command.args or "").strip()
    if not name:
        await message.reply("Укажите тип: <code>/bind Мафия</code>")
        return
    event_type = await repo.get_type_by_name(name)
    if not event_type:
        await message.reply(f"Тип «{name}» не найден. Список типов и добавление — /settings в личке с ботом.")
        return
    await repo.bind_type_topic(event_type.id, message.chat.id, message.message_thread_id)
    await message.reply(f"Готово ✅ Мероприятия «{event_type.name}» будут публиковаться в этой теме.")


@router.message(Command("bind_remind"), F.chat.type.in_({"group", "supergroup"}))
async def cmd_bind_remind(message: Message, command: CommandObject) -> None:
    name = (command.args or "").strip()
    if not name:
        await message.reply("Укажите тип: <code>/bind_remind Мафия</code>")
        return
    event_type = await repo.get_type_by_name(name)
    if not event_type:
        await message.reply(f"Тип «{name}» не найден. Список типов и добавление — /settings в личке с ботом.")
        return
    await repo.bind_type_remind(event_type.id, message.chat.id, message.message_thread_id)
    await message.reply(f"Готово ✅ Напоминания «{event_type.name}» будут приходить в эту тему.")
