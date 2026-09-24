from datetime import date
from typing import Dict, List, Optional
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

from database.models import CleaningChecklistState, DailyTaskState, User
from services.cleaning_service import CLEANING_TASKS

SLOT_NAMES = {
    0: "Dushanba",
    1: "Seshanba",
    2: "Chorshanba",
    3: "Payshanba",
    4: "Juma",
    5: "Shanba",
    6: "Yakshanba",
    7: "Zaxira slot",
}

DAILY_5_TASKS = {
    "task_meal": "🍲 Kechki taom / ovqat",
    "task_bread": "🍞 Non olib kelish",
    "task_table": "🧽 Xontaxta va stollarni artish",
    "task_dishes": "🍳 Qozon va umumiy idishlar",
    "task_trash": "🗑 Oshxona va hojatxona axlati",
}


def format_claim_button_text(full_name: str, room_number: int) -> str:
    """Format label: e.g. 'Avazbek' -> '👤 Men Avazbekman (Xona 1)'"""
    if full_name.endswith("man"):
        affix_name = full_name
    elif full_name.endswith("bro"):
        affix_name = f"{full_name}man"
    else:
        affix_name = f"{full_name}man"
    return f"👤 Men {affix_name} (Xona {room_number})"


def get_claim_profiles_keyboard(users: List[User]) -> InlineKeyboardMarkup:
    """
    8 ta xonadon a'zosi profilini egallash (Claim) uchun vertikal tugmalar:
    Bo'sh bo'lsa: [ 👤 Men {Ism}man (Xona {Xona}) ]
    Band bo'lsa:  [ 🔒 {Ism} (Band) ]
    """
    keyboard = []
    sorted_users = sorted(users, key=lambda u: u.order_index)
    for u in sorted_users:
        if u.telegram_id is not None:
            btn_text = f"🔒 {u.full_name} (Band)"
            cb_data = f"profile_claimed:{u.id}"
        else:
            btn_text = format_claim_button_text(u.full_name, u.room_number)
            cb_data = f"claim_profile:{u.id}"
        keyboard.append([InlineKeyboardButton(text=btn_text, callback_data=cb_data)])

    return InlineKeyboardMarkup(inline_keyboard=keyboard)


def get_room_selection_keyboard() -> InlineKeyboardMarkup:
    """Inline keyboard for selecting room number during registration."""
    keyboard = [
        [
            InlineKeyboardButton(text="🏢 1-Xona", callback_data="room_select:1"),
            InlineKeyboardButton(text="🏢 2-Xona", callback_data="room_select:2"),
        ]
    ]
    return InlineKeyboardMarkup(inline_keyboard=keyboard)


def get_day_slots_keyboard(occupied_map: Dict[int, User]) -> InlineKeyboardMarkup:
    """
    Haftaning 7 kuni + 1 ta zaxira sloti klaviaturasi.
    Agar bo'sh bo'lsa: [ 🟢 Dushanba ]
    Agar band bo'lsa: [ 🔒 Dushanba (Ism) ]
    """
    keyboard = []
    for day_idx in range(8):
        day_title = SLOT_NAMES[day_idx]
        if day_idx in occupied_map:
            user = occupied_map[day_idx]
            first_name = user.full_name.split()[0]
            text = f"🔒 {day_title} ({first_name})"
            cb = f"slot_occ:{day_idx}"
        else:
            text = f"🟢 {day_title}"
            cb = f"slot_sel:{day_idx}"

        keyboard.append([InlineKeyboardButton(text=text, callback_data=cb)])

    return InlineKeyboardMarkup(inline_keyboard=keyboard)


def get_daily_tasks_keyboard(
    tasks: List[DailyTaskState],
    duty_date: date,
) -> InlineKeyboardMarkup:
    """
    Kunlik navbatchi uchun 5 ta alohida vazifa tugmasi.
    Bajarilmagan bo'lsa: [❌] 🍲 Kechki taom / ovqat
    Bajarilgan bo'lsa:   [✅] 🍲 Kechki taom / ovqat
    """
    buttons = []
    task_dict = {t.task_key: t for t in tasks}

    for key, label in DAILY_5_TASKS.items():
        task_item = task_dict.get(key)
        is_done = task_item.is_done if task_item else False
        status_icon = "✅" if is_done else "❌"
        btn_text = f"[{status_icon}] {label}"
        cb = f"dtask_tog:{key}:{duty_date.isoformat()}"
        buttons.append([InlineKeyboardButton(text=btn_text, callback_data=cb)])

    # Refresh & Jazolash/E'tiroz row
    buttons.append([
        InlineKeyboardButton(
            text="🔄 Yangilash",
            callback_data=f"dtask_ref:{duty_date.isoformat()}",
        ),
        InlineKeyboardButton(
            text="🚨 Jazolash / E'tiroz",
            callback_data=f"dfraud_rep:{duty_date.isoformat()}",
        ),
    ])
    return InlineKeyboardMarkup(inline_keyboard=buttons)


def get_vote_keyboard(
    duty_date: date,
    target_user_id: int,
    reason: str,
    fine_count: int = 0,
    forgive_count: int = 0,
) -> InlineKeyboardMarkup:
    """
    Ovoz berish (Poll/Voting) tugmalari:
    - INCOMPLETE holati: [⚖️ Jarima berilsin (15,000 so'm)] ({fine_count}) | [🤝 Uzrli / Kechirilsin] ({forgive_count})
    - FRAUD holati:      [🔴 Ha, qoidabuzarlik (Jarima yozilsin)] ({fine_count}) | [⚪️ Yo'q, hammasi toza] ({forgive_count})
    """
    date_str = duty_date.isoformat()
    if reason == "INCOMPLETE":
        btn_fine_text = f"⚖️ Jarima berilsin (15,000 so'm) ({fine_count})"
        btn_forgive_text = f"🤝 Uzrli / Kechirilsin ({forgive_count})"
    else:
        btn_fine_text = f"🔴 Ha, qoidabuzarlik (Jarima yozilsin) ({fine_count})"
        btn_forgive_text = f"⚪️ Yo'q, hammasi toza ({forgive_count})"

    keyboard = [
        [
            InlineKeyboardButton(
                text=btn_fine_text,
                callback_data=f"dvote:FINE:{reason}:{target_user_id}:{date_str}",
            ),
        ],
        [
            InlineKeyboardButton(
                text=btn_forgive_text,
                callback_data=f"dvote:FORGIVE:{reason}:{target_user_id}:{date_str}",
            ),
        ],
    ]
    return InlineKeyboardMarkup(inline_keyboard=keyboard)


def get_checklist_inline_keyboard(
    items: List[CleaningChecklistState],
    week_date: date,
) -> InlineKeyboardMarkup:
    """11 bandlik interaktiv dam olish kuni tozalash checklist klaviaturasi."""
    buttons = []
    for idx, item in enumerate(items, 1):
        title = CLEANING_TASKS.get(item.task_key, item.task_key)

        if item.is_done:
            by_name = item.completed_by_user.full_name.split()[0] if item.completed_by_user else "Bajarildi"
            short_title = title if len(title) <= 26 else title[:24] + ".."
            btn_text = f"✅ {idx}. {short_title} ({by_name})"
        else:
            short_title = title if len(title) <= 30 else title[:28] + ".."
            btn_text = f"❌ {idx}. {short_title}"

        cb_data = f"clean_tog:{item.task_key}:{week_date.isoformat()}"
        buttons.append([InlineKeyboardButton(text=btn_text, callback_data=cb_data)])

    buttons.append([
        InlineKeyboardButton(
            text="🔄 Yangilash",
            callback_data=f"clean_ref:{week_date.isoformat()}",
        )
    ])
    return InlineKeyboardMarkup(inline_keyboard=buttons)


def get_swap_candidates_keyboard(
    candidates: List[User],
    requester_date: date,
) -> InlineKeyboardMarkup:
    """List active roommates to choose from for duty swap."""
    keyboard = []
    for candidate in candidates:
        text = f"👤 {candidate.full_name} ({candidate.room_number}-Xona)"
        cb = f"swap_user:{candidate.id}:{requester_date.isoformat()}"
        keyboard.append([InlineKeyboardButton(text=text, callback_data=cb)])

    keyboard.append([InlineKeyboardButton(text="Bekor qilish", callback_data="swap_cancel")])
    return InlineKeyboardMarkup(inline_keyboard=keyboard)


def get_swap_request_keyboard(
    requester_id: int,
    requester_date_str: str,
    target_date_str: str,
) -> InlineKeyboardMarkup:
    """Buttons sent to target user to accept or reject swap."""
    keyboard = [
        [
            InlineKeyboardButton(
                text="✅ Roziman",
                callback_data=f"swap_acc:{requester_id}:{requester_date_str}:{target_date_str}",
            ),
            InlineKeyboardButton(
                text="❌ Rad etaman",
                callback_data=f"swap_rej:{requester_id}",
            ),
        ]
    ]
    return InlineKeyboardMarkup(inline_keyboard=keyboard)


def get_leave_confirm_keyboard() -> InlineKeyboardMarkup:
    """Confirmation buttons for /leave command (navbatchilikdan chiqish)."""
    keyboard = [
        [
            InlineKeyboardButton(text="Ha, navbatchilikdan chiqaman", callback_data="confirm_leave"),
            InlineKeyboardButton(text="Bekor qilish", callback_data="cancel_leave"),
        ]
    ]
    return InlineKeyboardMarkup(inline_keyboard=keyboard)


def get_water_complete_keyboard() -> InlineKeyboardMarkup:
    """Button to record water replenishment."""
    keyboard = [
        [
            InlineKeyboardButton(
                text="💧 Suv olib kelindi (19L)",
                callback_data="water_complete",
            )
        ]
    ]
    return InlineKeyboardMarkup(inline_keyboard=keyboard)


def get_expense_inline_keyboard(expense_id: int) -> InlineKeyboardMarkup:
    """Buttons for split-bill payment confirmation."""
    keyboard = [
        [
            InlineKeyboardButton(
                text="💸 To'ladim",
                callback_data=f"pay_exp:{expense_id}",
            ),
            InlineKeyboardButton(
                text="🔄 Yangilash",
                callback_data=f"ref_exp:{expense_id}",
            ),
        ]
    ]
    return InlineKeyboardMarkup(inline_keyboard=keyboard)


def get_fine_payment_keyboard(penalty_id: int) -> InlineKeyboardMarkup:
    """Button to mark penalty as settled."""
    keyboard = [
        [
            InlineKeyboardButton(
                text="✅ To'landi deb belgilash",
                callback_data=f"pay_fine:{penalty_id}",
            )
        ]
    ]
    return InlineKeyboardMarkup(inline_keyboard=keyboard)
