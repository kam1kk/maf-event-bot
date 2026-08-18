import asyncio
import logging
import sys

from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.types import BotCommand, BotCommandScopeAllChatAdministrators, BotCommandScopeAllPrivateChats

from bot import config
from bot.config import settings
from bot.db import repo
from bot.db.models import init_db
from bot.handlers import create, edit, group, profile
from bot.handlers import settings as settings_handlers
from bot.services import scheduler as sched

logger = logging.getLogger(__name__)


async def main() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    if not settings.bot_token:
        logger.error("BOT_TOKEN не задан. Скопируйте .env.example в .env и впишите токен от @BotFather.")
        sys.exit(1)

    await init_db()

    # миграция: глобальная настройка пояса (v1.5.0) переезжает в группы
    saved_tz = await repo.get_setting("timezone")
    if saved_tz:
        for g in await repo.list_groups():
            if not g.timezone:
                await repo.set_group_timezone(g.chat_id, saved_tz)
        await repo.delete_setting("timezone")

    groups = await repo.list_groups()
    for g in groups:
        await repo.ensure_default_type(g.chat_id)
    logger.info("Групп: %d, часовой пояс по умолчанию: %s", len(groups), config.get_tz())

    bot = Bot(settings.bot_token, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
    dp = Dispatcher(storage=MemoryStorage())
    dp.include_routers(
        profile.router,
        create.router,
        edit.router,
        settings_handlers.router,
        group.router,
    )

    await bot.set_my_commands(
        [
            BotCommand(command="new", description="Создать мероприятие"),
            BotCommand(command="my", description="Мои записи"),
            BotCommand(command="nick", description="Сменить игровой ник"),
            BotCommand(command="settings", description="Типы мероприятий"),
        ],
        scope=BotCommandScopeAllPrivateChats(),
    )
    # подсказки при вводе «/» в группе — только у Telegram-админов;
    # рядовым участникам эти команды не показываются
    await bot.set_my_commands(
        [
            BotCommand(command="bind", description="Публиковать тип мероприятий в этой теме"),
            BotCommand(command="unbind", description="Снять привязку темы мероприятий"),
            BotCommand(command="bind_remind", description="Напоминания типа — в эту тему"),
            BotCommand(command="unbind_remind", description="Отвязать тему напоминаний"),
            BotCommand(command="promote", description="Выдать права админа бота (ответом на сообщение)"),
            BotCommand(command="demote", description="Снять права админа бота (ответом на сообщение)"),
        ],
        scope=BotCommandScopeAllChatAdministrators(),
    )

    sched.setup(bot)
    sched.scheduler.start()
    await sched.restore_jobs()

    logger.info("Бот запущен")
    await bot.delete_webhook(drop_pending_updates=True)
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())
