import re
from datetime import date, datetime, time, timedelta

from bot.config import get_tz

DATE_RE = re.compile(r"(\d{1,2})[.\-/](\d{1,2})(?:[.\-/](\d{2,4}))?")
# «21:15», «21.15», «21-15», «21 15» — час и минуты через любой разделитель
TIME_HM_RE = re.compile(r"(\d{1,2})(?:\s*[:.,\-]\s*|\s+)(\d{1,2})")
# «2115», «930» — без разделителя
TIME_COMPACT_RE = re.compile(r"(\d{1,2})(\d{2})")
# «21» — только час, минуты нулевые
TIME_H_RE = re.compile(r"(\d{1,2})")


def today() -> date:
    return datetime.now(get_tz()).date()


def day_end(d: date, tz) -> datetime:
    """Момент, когда день d считается прошедшим, — полночь следующего дня."""
    return datetime.combine(d + timedelta(days=1), time(0, 0), tzinfo=tz)


def parse_date(text: str, base: date | None = None) -> date | None:
    """Разбирает '13.08', '13.08.2026', '13/08' и т.п.
    base — «сегодня» в часовом поясе группы (для года по умолчанию)."""
    m = DATE_RE.fullmatch(text.strip())
    if not m:
        return None
    day, month = int(m.group(1)), int(m.group(2))
    year_raw = m.group(3)
    now = base or today()
    if year_raw:
        year = int(year_raw)
        if year < 100:
            year += 2000
    else:
        year = now.year
    try:
        result = date(year, month, day)
    except ValueError:
        return None
    # без года: если дата уже прошла — берём следующий год
    if not year_raw and result < now:
        try:
            result = date(year + 1, month, day)
        except ValueError:
            return None
    return result


def parse_time(text: str) -> time | None:
    """Разбирает '19:00', '9:30', '19.00', '19-00', '19 30', '1930', '19' (→ 19:00)."""
    raw = " ".join(text.split())
    for pattern in (TIME_HM_RE, TIME_COMPACT_RE):
        m = pattern.fullmatch(raw)
        if m:
            hour, minute = int(m.group(1)), int(m.group(2))
            break
    else:
        m = TIME_H_RE.fullmatch(raw)
        if not m:
            return None
        hour, minute = int(m.group(1)), 0
    if hour > 23 or minute > 59:
        return None
    return time(hour, minute)


def fmt_date(d: date) -> str:
    return d.strftime("%d.%m.%Y")


def fmt_time(t: time) -> str:
    return t.strftime("%H:%M")


def message_link(chat_id: int, message_id: int) -> str | None:
    """Ссылка на сообщение в приватной супергруппе (t.me/c/...)."""
    cid = str(chat_id)
    if cid.startswith("-100"):
        return f"https://t.me/c/{cid[4:]}/{message_id}"
    return None


def clean_nick(text: str) -> str | None:
    nick = " ".join(text.split())
    if not nick or len(nick) > 32:
        return None
    return nick
