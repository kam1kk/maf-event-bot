from aiogram import Bot, F, Router
from aiogram.filters import Command, CommandObject
from aiogram.types import CallbackQuery, ChatMemberUpdated, Message

from bot.db import repo
from bot.services import roster

router = Router()


@router.my_chat_member()
async def on_bot_membership(update: ChatMemberUpdated) -> None:
    """Бота добавили в группу — регистрируем её и создаём тип по умолчанию."""
    if update.chat.type not in ("group", "supergroup"):
        return
    if update.new_chat_member.status in ("member", "administrator"):
        await repo.ensure_group(update.chat.id, update.chat.title)
        await repo.ensure_default_type(update.chat.id)


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

    ok, text = await roster.register(
        bot, event_id, callback.from_user.id, user.nick, callback.from_user.username
    )
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


@router.callback_query(F.data.startswith("friend:"))
async def cb_add_friend(callback: CallbackQuery, bot: Bot) -> None:
    """Запись друга: нужен ввод ника, поэтому всегда через личку."""
    event_id = int(callback.data.split(":")[1])
    event = await repo.get_event(event_id)
    if not event or event.status != "active":
        await callback.answer("Запись закрыта", show_alert=True)
        return
    me = await bot.get_me()
    await callback.answer(url=f"https://t.me/{me.username}?start=friend_{event_id}")


@router.callback_query(F.data.startswith("unfriend:"))
async def cb_remove_friend(callback: CallbackQuery, bot: Bot) -> None:
    event_id = int(callback.data.split(":")[1])
    event = await repo.get_event(event_id)
    if not event or event.status != "active":
        await callback.answer("Запись закрыта", show_alert=True)
        return
    guests = await repo.get_guest_regs(event_id, callback.from_user.id)
    if not guests:
        await callback.answer("Вы не записывали друзей на это мероприятие", show_alert=True)
        return
    if len(guests) == 1:
        await repo.delete_reg(guests[0].id)
        await roster.refresh_event_message(bot, event_id)
        await callback.answer(f"Выписан: {guests[0].nick} ✅")
        return
    # друзей несколько — выбор в личке
    me = await bot.get_me()
    await callback.answer(url=f"https://t.me/{me.username}?start=unfriend_{event_id}")


@router.callback_query(F.data.startswith("unreg:"))
async def cb_unregister(callback: CallbackQuery, bot: Bot) -> None:
    event_id = int(callback.data.split(":")[1])
    ok, text = await roster.unregister(bot, event_id, callback.from_user.id)
    await callback.answer(text, show_alert=not ok)


# ---------- привязка тем ----------

@router.message(Command("bind"), F.chat.type.in_({"group", "supergroup"}))
async def cmd_bind(message: Message, command: CommandObject) -> None:
    # подстраховка, если бота добавили, пока он был выключен
    await repo.ensure_group(message.chat.id, message.chat.title)
    await repo.ensure_default_type(message.chat.id)
    name = (command.args or "").strip()
    if not name:
        await message.reply("Укажите тип: <code>/bind Мафия</code>")
        return
    event_type = await repo.get_type_by_name(message.chat.id, name)
    if not event_type:
        await message.reply(
            f"Тип «{name}» не найден в этой группе. Список типов и добавление — /settings в личке с ботом."
        )
        return
    await repo.bind_type_topic(event_type.id, message.chat.id, message.message_thread_id)
    await message.reply(f"Готово ✅ Мероприятия «{event_type.name}» будут публиковаться в этой теме.")


@router.message(Command("bind_remind"), F.chat.type.in_({"group", "supergroup"}))
async def cmd_bind_remind(message: Message, command: CommandObject) -> None:
    await repo.ensure_group(message.chat.id, message.chat.title)
    await repo.ensure_default_type(message.chat.id)
    name = (command.args or "").strip()
    if not name:
        await message.reply("Укажите тип: <code>/bind_remind Мафия</code>")
        return
    event_type = await repo.get_type_by_name(message.chat.id, name)
    if not event_type:
        await message.reply(
            f"Тип «{name}» не найден в этой группе. Список типов и добавление — /settings в личке с ботом."
        )
        return
    await repo.bind_type_remind(event_type.id, message.chat.id, message.message_thread_id)
    await message.reply(f"Готово ✅ Напоминания «{event_type.name}» будут приходить в эту тему.")
