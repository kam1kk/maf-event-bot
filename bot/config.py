import os
from dataclasses import dataclass
from zoneinfo import ZoneInfo

from dotenv import load_dotenv
from tzlocal import get_localzone

load_dotenv()


@dataclass
class Settings:
    bot_token: str = os.getenv("BOT_TOKEN", "")
    tz_name: str = os.getenv("TZ", "").strip()
    db_path: str = os.getenv("DB_PATH", "data/bot.db")


settings = Settings()
# пустой TZ — часовой пояс системы, на которой работает бот
TZ = ZoneInfo(settings.tz_name) if settings.tz_name else get_localzone()
