import os
from dataclasses import dataclass
from zoneinfo import ZoneInfo

from dotenv import load_dotenv

load_dotenv()


@dataclass
class Settings:
    bot_token: str = os.getenv("BOT_TOKEN", "")
    tz_name: str = os.getenv("TZ", "Europe/Moscow")
    db_path: str = os.getenv("DB_PATH", "data/bot.db")


settings = Settings()
TZ = ZoneInfo(settings.tz_name)
