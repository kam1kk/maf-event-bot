from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

from bot.db.models import Event, EventType, Group, Registration


def group_picker_keyboard(groups: list[Group], prefix: str) -> InlineKeyboardMarkup:
    rows = [
        [InlineKeyboardButton(
            text=group.title or str(group.chat_id),
            callback_data=f"{prefix}:{group.chat_id}",
        )]
        for group in groups
    ]
    return InlineKeyboardMarkup(inline_keyboard=rows)


def event_keyboard(event_id: int, has_guests: bool = False) -> InlineKeyboardMarkup:
    rows = [
        [
            InlineKeyboardButton(text="✅ Записаться", callback_data=f"reg:{event_id}"),
            InlineKeyboardButton(text="🕐 Со временем", callback_data=f"regt:{event_id}"),
        ],
        [
            InlineKeyboardButton(text="➕ Записать друга", callback_data=f"friend:{event_id}"),
            InlineKeyboardButton(text="🔗 Друг замена", callback_data=f"frsl:{event_id}"),
        ],
    ]
    if has_guests:
        rows.append(
            [InlineKeyboardButton(text="➖ Выписать друга", callback_data=f"unfriend:{event_id}")]
        )
    rows.append([
        InlineKeyboardButton(text="🚪 Выписаться", callback_data=f"unreg:{event_id}"),
        InlineKeyboardButton(text="⚙ Управление", callback_data=f"manage:{event_id}"),
    ])
    return InlineKeyboardMarkup(inline_keyboard=rows)


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


def date_keyboard(prefix: str, cancel_cb: str = "cform:cancel", cancel_text: str = "✖ Отмена") -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="Сегодня", callback_data=f"{prefix}:today"),
            InlineKeyboardButton(text="Завтра", callback_data=f"{prefix}:tomorrow"),
        ],
        [InlineKeyboardButton(text="📅 Ввести дату", callback_data=f"{prefix}:manual")],
        [InlineKeyboardButton(text=cancel_text, callback_data=cancel_cb)],
    ])


def cancel_create_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="✖ Отмена", callback_data="cform:cancel")],
    ])


def back_to_manage_keyboard(event_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="« Назад", callback_data=f"mng:{event_id}:menu")],
    ])


def back_to_reg_keyboard(reg_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="« Назад", callback_data=f"my:{reg_id}")],
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
        [InlineKeyboardButton(text="🕵 Кто записал друзей", callback_data=f"mng:{e}:guests")],
        [InlineKeyboardButton(text="❌ Отменить стол", callback_data=f"mng:{e}:cancel")],
        [InlineKeyboardButton(text="✔ Готово", callback_data=f"mng:{e}:close")],
    ])


def kick_keyboard(event_id: int, regs: list[Registration]) -> InlineKeyboardMarkup:
    rows = []
    for reg in regs:
        marks = []
        if reg.attached_to:
            marks.append("через /")
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


def restore_keyboard(event_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="♻ Восстановить стол", callback_data=f"rst:{event_id}")],
    ])


def cancel_confirm_keyboard(event_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="Да, отменить стол", callback_data=f"mngc:{event_id}:yes"),
            InlineKeyboardButton(text="Нет", callback_data=f"mngc:{event_id}:no"),
        ],
    ])


def my_regs_keyboard(items: list) -> InlineKeyboardMarkup:
    """items: list[(Registration, Event)]"""
    rows = []
    for reg, event in items:
        label = f"{event.type_name} — {event.date_.strftime('%d.%m')} {event.time_.strftime('%H:%M')}"
        if reg.user_id is None:
            label += f" · друг: {reg.nick}"
        rows.append([InlineKeyboardButton(text=label, callback_data=f"my:{reg.id}")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def my_reg_menu_keyboard(reg: Registration) -> InlineKeyboardMarkup:
    r = reg.id
    guest = reg.user_id is None
    arrive_label = "🕐 Опоздает (к …)" if guest else "🕐 Приду позже (к …)"
    leave_label = "🕗 Уйдёт раньше (до …)" if guest else "🕗 Уйду раньше (до …)"
    unreg_label = "🚪 Выписать друга" if guest else "🚪 Выписаться"
    rows = []
    # друг «через /» живёт в строке хозяина — своего времени у него нет
    if reg.attached_to is None:
        rows = [
            [InlineKeyboardButton(text=arrive_label, callback_data=f"myr:{r}:arrive")],
            [InlineKeyboardButton(text=leave_label, callback_data=f"myr:{r}:leave")],
        ]
        if reg.arrive_time or reg.leave_time:
            rows.append([InlineKeyboardButton(text="♻ Сбросить время", callback_data=f"myr:{r}:reset")])
    rows.append([InlineKeyboardButton(text=unreg_label, callback_data=f"myr:{r}:unreg")])
    rows.append([InlineKeyboardButton(text="« Назад", callback_data="myr:back")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def unfriend_keyboard(event_id: int, guests: list[Registration]) -> InlineKeyboardMarkup:
    rows = [
        [InlineKeyboardButton(
            text=f"🚪 {reg.nick}" + (" (через /)" if reg.attached_to else ""),
            callback_data=f"unfr:{event_id}:{reg.id}",
        )]
        for reg in guests
    ]
    return InlineKeyboardMarkup(inline_keyboard=rows)


def cancel_friend_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="✖ Отмена", callback_data="frx")],
    ])


def settings_keyboard(group: Group) -> InlineKeyboardMarkup:
    chat_id = group.chat_id
    mode_label = (
        "🎛 Создание: только админы" if group.only_admins_create else "🎛 Создание: все участники"
    )
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="➕ Добавить тип мероприятия", callback_data=f"st:add:{chat_id}")],
        [InlineKeyboardButton(text="🌍 Часовой пояс", callback_data=f"st:tz:{chat_id}")],
        [InlineKeyboardButton(text=mode_label, callback_data=f"st:mode:{chat_id}")],
        [InlineKeyboardButton(text="👮 Админы бота", callback_data=f"st:adm:{chat_id}")],
    ])


def admins_keyboard(chat_id: int, admins: list) -> InlineKeyboardMarkup:
    """admins: list[GroupAdmin]"""
    rows = [
        [InlineKeyboardButton(
            text=f"✖ {admin.name or admin.user_id}",
            callback_data=f"unadm:{chat_id}:{admin.user_id}",
        )]
        for admin in admins
    ]
    rows.append([InlineKeyboardButton(text="« Назад", callback_data=f"sg:{chat_id}")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


TZ_CHOICES = [
    ("Калининград +2", "Europe/Kaliningrad"),
    ("Москва +3", "Europe/Moscow"),
    ("Самара +4", "Europe/Samara"),
    ("Екатеринбург +5", "Asia/Yekaterinburg"),
    ("Омск +6", "Asia/Omsk"),
    ("Красноярск +7", "Asia/Krasnoyarsk"),
    ("Иркутск +8", "Asia/Irkutsk"),
    ("Якутск +9", "Asia/Yakutsk"),
    ("Владивосток +10", "Asia/Vladivostok"),
    ("Магадан +11", "Asia/Magadan"),
    ("Камчатка +12", "Asia/Kamchatka"),
]


def tz_keyboard(chat_id: int) -> InlineKeyboardMarkup:
    rows = []
    for i in range(0, len(TZ_CHOICES), 2):
        rows.append([
            InlineKeyboardButton(text=label, callback_data=f"tzset:{chat_id}:{name}")
            for label, name in TZ_CHOICES[i:i + 2]
        ])
    rows.append([InlineKeyboardButton(text="✏ Ввести вручную", callback_data=f"st:tzm:{chat_id}")])
    return InlineKeyboardMarkup(inline_keyboard=rows)
