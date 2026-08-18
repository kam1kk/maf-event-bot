import logging

from aiogram import Bot
from aiogram.types import BotCommand, BotCommandScopeChatMember

logger = logging.getLogger(__name__)

# Команды для меню админов. Используются в двух scope:
# - все Telegram-админы чатов (main.py, AllChatAdministrators);
# - точечно для участников с правами через /promote (ChatMember —
#   Telegram сам про них не знает, поэтому выдаём каждому отдельно).
ADMIN_COMMANDS = [
    BotCommand(command="bind", description="Публиковать тип мероприятий в этой теме"),
    BotCommand(command="unbind", description="Снять привязку темы мероприятий"),
    BotCommand(command="bind_remind", description="Напоминания типа — в эту тему"),
    BotCommand(command="unbind_remind", description="Отвязать тему напоминаний"),
    BotCommand(command="promote", description="Выдать права админа бота (ответом на сообщение)"),
    BotCommand(command="demote", description="Снять права админа бота (ответом на сообщение)"),
]


async def set_member_hints(bot: Bot, chat_id: int, user_id: int, grant: bool) -> None:
    """Точечные подсказки команд для админа, назначенного /promote.
    Ошибка Telegram не должна ломать выдачу/снятие прав — права уже в БД."""
    scope = BotCommandScopeChatMember(chat_id=chat_id, user_id=user_id)
    try:
        if grant:
            await bot.set_my_commands(ADMIN_COMMANDS, scope=scope)
        else:
            await bot.delete_my_commands(scope=scope)
    except Exception as e:
        logger.warning("Не удалось обновить подсказки команд %s в %s: %s", user_id, chat_id, e)
