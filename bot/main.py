import asyncio
import logging
import sys

from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.types import BotCommand, BotCommandScopeAllPrivateChats

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
    await repo.ensure_default_type("Мафия")

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

    sched.setup(bot)
    sched.scheduler.start()
    await sched.restore_jobs()

    logger.info("Бот запущен")
    await bot.delete_webhook(drop_pending_updates=True)
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())
