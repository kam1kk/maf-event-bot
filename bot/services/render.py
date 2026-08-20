from html import escape

from bot.db.models import Event, Registration
from bot.utils import fmt_date, fmt_time

MIN_SLOTS = 10


def _reg_name(reg: Registration) -> str:
    name = escape(reg.nick)
    # ник — ссылка на профиль; уведомлений не порождает, т.к. список попадает
    # в сообщение только через редактирование
    if reg.username:
        name = f'<a href="https://t.me/{reg.username}">{name}</a>'
    elif reg.user_id:
        name = f'<a href="tg://user?id={reg.user_id}">{name}</a>'
    return name


def reg_line(reg: Registration, attached: list[Registration] | None = None) -> str:
    # друзья «через /» — в одной строке с хозяином: kam1kk / mirai
    # слэш отделяется пробелами: «/ник» вплотную Telegram подсвечивает как команду бота
    parts = [" / ".join([_reg_name(r) for r in [reg, *(attached or [])]])]
    if reg.arrive_time:
        parts.append(f"(придёт к {fmt_time(reg.arrive_time)})")
    if reg.leave_time:
        parts.append(f"(до {fmt_time(reg.leave_time)})")
    return " ".join(parts)


def render_event(event: Event, regs: list[Registration]) -> str:
    ids = {r.id for r in regs}
    attached: dict[int, list[Registration]] = {}
    hosts: list[Registration] = []
    for r in regs:
        # хозяин мог быть удалён напрямую в БД — тогда гость показывается своей строкой
        if r.attached_to is not None and r.attached_to in ids:
            attached.setdefault(r.attached_to, []).append(r)
        else:
            hosts.append(r)
    main = [r for r in hosts if r.category == "main"]
    late = [r for r in hosts if r.category == "late"]

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
            lines.append(f"{i + 1}. {reg_line(main[i], attached.get(main[i].id))}")
        else:
            lines.append(f"{i + 1}.")
    if late:
        lines.append("")
        lines.append("<b>Опоздавшие:</b>")
        for i, reg in enumerate(late, 1):
            lines.append(f"{i}. {reg_line(reg, attached.get(reg.id))}")
    if event.status == "closed":
        lines.append("")
        lines.append("🔒 Запись закрыта")
    return "\n".join(lines)


def render_guests(regs: list[Registration], names: dict[int, str]) -> str:
    """Кто кого записал — для создателя мероприятия и админов бота.
    names: tg_id записавшего → его имя (ник из записи на этом же мероприятии
    или сохранённый игровой ник); кого нет в словаре — показываем «id N»,
    но тоже ссылкой на профиль."""
    ids = {r.id for r in regs}
    guests = [r for r in regs if r.user_id is None]
    if not guests:
        return "Друзей на это мероприятие пока никто не записывал."
    lines = ["<b>Кто записал друзей:</b>", ""]
    for reg in guests:
        name = names.get(reg.added_by)
        label = escape(name) if name else f"id {reg.added_by}"
        who = f'<a href="tg://user?id={reg.added_by}">{label}</a>'
        # «через /» — только пока друг реально в строке хозяина; если хозяин
        # выписался, друг стал самостоятельной записью, а записавший тот же
        mark = " (через /)" if reg.attached_to is not None and reg.attached_to in ids else ""
        lines.append(f"• <b>{escape(reg.nick)}</b>{mark} — записал {who}")
    return "\n".join(lines)


def render_summary(event: Event) -> str:
    return (
        f"🎭 <b>{escape(event.type_name)}</b>\n"
        f"📅 {fmt_date(event.date_)}, {fmt_time(event.time_)}\n"
        f"📍 {escape(event.place)}\n"
        f"🎤 Ведущий: {escape(event.host)}"
    )
