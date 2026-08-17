from html import escape

from bot.db.models import Event, Registration
from bot.utils import fmt_date, fmt_time

MIN_SLOTS = 10


def reg_line(reg: Registration) -> str:
    parts = [escape(reg.nick)]
    if reg.arrive_time:
        parts.append(f"(придёт к {fmt_time(reg.arrive_time)})")
    if reg.leave_time:
        parts.append(f"(до {fmt_time(reg.leave_time)})")
    return " ".join(parts)


def render_event(event: Event, regs: list[Registration]) -> str:
    main = [r for r in regs if r.category == "main"]
    late = [r for r in regs if r.category == "late"]

    lines: list[str] = []
    if event.status == "cancelled":
        lines.append("❌ <b>Стол отменен</b>")
        lines.append("")
    lines.append(f"🎭 <b>{escape(event.type_name)}</b> — {fmt_date(event.date_)}, {fmt_time(event.time_)}")
    lines.append(f"📍 {escape(event.place)}  |  Ведущий: {escape(event.host)}")
    lines.append("")
    lines.append("<b>Состав:</b>")
    slots = max(MIN_SLOTS, len(main))
    for i in range(slots):
        if i < len(main):
            lines.append(f"{i + 1}. {reg_line(main[i])}")
        else:
            lines.append(f"{i + 1}.")
    if late:
        lines.append("")
        lines.append("<b>Опоздавшие:</b>")
        for i, reg in enumerate(late, 1):
            lines.append(f"{i}. {reg_line(reg)}")
    if event.status == "closed":
        lines.append("")
        lines.append("🔒 Запись закрыта")
    return "\n".join(lines)


def render_summary(event: Event) -> str:
    return (
        f"🎭 <b>{escape(event.type_name)}</b>\n"
        f"📅 {fmt_date(event.date_)}, {fmt_time(event.time_)}\n"
        f"📍 {escape(event.place)}\n"
        f"🎤 Ведущий: {escape(event.host)}"
    )
