from aiogram import Bot

from bot.db import repo
from bot.db.models import Group

# статусы, при которых человек реально состоит в группе
MEMBER_STATUSES = {"creator", "administrator", "member", "restricted"}
# статусы Telegram-админов группы — они всегда админы бота
TG_ADMIN_STATUSES = {"creator", "administrator"}


async def is_tg_admin(bot: Bot, chat_id: int, user_id: int) -> bool:
    """Админ самой группы Telegram (только они выдают/снимают права бота)."""
    try:
        member = await bot.get_chat_member(chat_id, user_id)
    except Exception:
        return False
    return member.status in TG_ADMIN_STATUSES


async def is_bot_admin(bot: Bot, chat_id: int, user_id: int) -> bool:
    """Админ бота в группе: Telegram-админ или участник с выданными правами."""
    if await repo.is_group_admin(chat_id, user_id):
        return True
    return await is_tg_admin(bot, chat_id, user_id)


async def admin_groups(bot: Bot, user_id: int) -> list[Group]:
    """Группы пользователя, где он админ бота."""
    result = []
    for group in await user_groups(bot, user_id):
        if await is_bot_admin(bot, group.chat_id, user_id):
            result.append(group)
    return result


async def user_groups(bot: Bot, user_id: int) -> list[Group]:
    """Группы, где установлен бот и где пользователь состоит на данный момент."""
    result = []
    for group in await repo.list_groups():
        try:
            member = await bot.get_chat_member(group.chat_id, user_id)
        except Exception:
            continue  # бот выкинут из группы или чат недоступен
        if member.status in MEMBER_STATUSES:
            result.append(group)
    return result
