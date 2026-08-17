from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

from bot.db.models import Event, EventType, Registration


def event_keyboard(event_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="✅ Записаться", callback_data=f"reg:{event_id}"),
            InlineKeyboardButton(text="🕐 Со временем", callback_data=f"regt:{event_id}"),
        ],
        [
            InlineKeyboardButton(text="🚪 Выписаться", callback_data=f"unreg:{event_id}"),
            InlineKeyboardButton(text="⚙ Управление", callback_data=f"manage:{event_id}"),
        ],
    ])


def types_keyboard(types: list[EventType]) -> InlineKeyboardMarkup:
    rows = [
        [InlineKeyboardButton(
            text=("⭐ " if t.is_default else "") + t.name,
            callback_data=f"ct:{t.id}",
        )]
        for t in types
    ]
    rows.append([InlineKeyboardButton(text="✖ Отмена", callback_data="cform:cancel")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def date_keyboard(prefix: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="Сегодня", callback_data=f"{prefix}:today"),
            InlineKeyboardButton(text="Завтра", callback_data=f"{prefix}:tomorrow"),
        ],
        [InlineKeyboardButton(text="📅 Ввести дату", callback_data=f"{prefix}:manual")],
        [InlineKeyboardButton(text="✖ Отмена", callback_data="cform:cancel")],
    ])


def confirm_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="🚀 Опубликовать", callback_data="cform:publish"),
            InlineKeyboardButton(text="✖ Отмена", callback_data="cform:cancel"),
        ],
    ])


def manage_keyboard(event: Event) -> InlineKeyboardMarkup:
    remind_label = "🔔 Напоминание: вкл" if event.remind_enabled else "🔕 Напоминание: выкл"
    e = event.id
    return InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="📅 Дата", callback_data=f"mng:{e}:date"),
            InlineKeyboardButton(text="🕐 Время", callback_data=f"mng:{e}:time"),
        ],
        [
            InlineKeyboardButton(text="📍 Место", callback_data=f"mng:{e}:place"),
            InlineKeyboardButton(text="🎤 Ведущий", callback_data=f"mng:{e}:host"),
        ],
        [InlineKeyboardButton(text=remind_label, callback_data=f"mng:{e}:remind")],
        [InlineKeyboardButton(text="👥 Выписать участника", callback_data=f"mng:{e}:kick")],
        [InlineKeyboardButton(text="❌ Отменить стол", callback_data=f"mng:{e}:cancel")],
        [InlineKeyboardButton(text="✔ Готово", callback_data=f"mng:{e}:close")],
    ])


def kick_keyboard(event_id: int, regs: list[Registration]) -> InlineKeyboardMarkup:
    rows = []
    for reg in regs:
        marks = []
        if reg.category == "late":
            marks.append("опаздывает")
        if reg.leave_time:
            marks.append(f"до {reg.leave_time.strftime('%H:%M')}")
        suffix = f" ({', '.join(marks)})" if marks else ""
        rows.append([InlineKeyboardButton(
            text=f"🚪 {reg.nick}{suffix}",
            callback_data=f"kick:{event_id}:{reg.id}",
        )])
    rows.append([InlineKeyboardButton(text="« Назад", callback_data=f"mng:{event_id}:menu")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def cancel_confirm_keyboard(event_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="Да, отменить стол", callback_data=f"mngc:{event_id}:yes"),
            InlineKeyboardButton(text="Нет", callback_data=f"mngc:{event_id}:no"),
        ],
    ])


def my_regs_keyboard(items: list) -> InlineKeyboardMarkup:
    """items: list[(Registration, Event)]"""
    rows = [
        [InlineKeyboardButton(
            text=f"{event.type_name} — {event.date_.strftime('%d.%m')} {event.time_.strftime('%H:%M')}",
            callback_data=f"my:{reg.id}",
        )]
        for reg, event in items
    ]
    return InlineKeyboardMarkup(inline_keyboard=rows)


def my_reg_menu_keyboard(reg: Registration) -> InlineKeyboardMarkup:
    r = reg.id
    rows = [
        [InlineKeyboardButton(text="🕐 Приду позже (к …)", callback_data=f"myr:{r}:arrive")],
        [InlineKeyboardButton(text="🕗 Уйду раньше (до …)", callback_data=f"myr:{r}:leave")],
    ]
    if reg.arrive_time or reg.leave_time:
        rows.append([InlineKeyboardButton(text="♻ Сбросить время", callback_data=f"myr:{r}:reset")])
    rows.append([InlineKeyboardButton(text="🚪 Выписаться", callback_data=f"myr:{r}:unreg")])
    rows.append([InlineKeyboardButton(text="« Назад", callback_data="myr:back")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def settings_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="➕ Добавить тип мероприятия", callback_data="st:add")],
    ])
