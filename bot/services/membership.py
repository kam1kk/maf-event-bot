from aiogram import Bot

from bot.db import repo
from bot.db.models import Group

# статусы, при которых человек реально состоит в группе
MEMBER_STATUSES = {"creator", "administrator", "member", "restricted"}


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
