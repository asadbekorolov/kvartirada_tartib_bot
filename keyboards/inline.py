from datetime import date
from typing import List
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

from database.models import CleaningChecklistState, User
from services.cleaning_service import CLEANING_TASKS


def get_room_selection_keyboard() -> InlineKeyboardMarkup:
    """Inline keyboard for selecting room number during registration."""
    keyboard = [
        [
            InlineKeyboardButton(text="🏢 1-Xona", callback_data="room_select:1"),
            InlineKeyboardButton(text="🏢 2-Xona", callback_data="room_select:2"),
        ]
    ]
    return InlineKeyboardMarkup(inline_keyboard=keyboard)


def get_duty_complete_keyboard(duty_date: date) -> InlineKeyboardMarkup:
    """Inline button to mark daily duty as completed."""
    keyboard = [
        [
            InlineKeyboardButton(
                text="✅ Navbatchilikni bajardim",
                callback_data=f"duty_complete:{duty_date.isoformat()}",
            )
        ]
    ]
    return InlineKeyboardMarkup(inline_keyboard=keyboard)


def get_checklist_inline_keyboard(
    items: List[CleaningChecklistState],
    week_date: date,
) -> InlineKeyboardMarkup:
    """
    11 bandlik interaktiv tozalash checklist klaviaturasi.
    Har bir band bosilganda [❌] holatidan [✅] holatiga o'tadi.
    """
    buttons = []
    for idx, item in enumerate(items, 1):
        title = CLEANING_TASKS.get(item.task_key, item.task_key)

        if item.is_done:
            by_name = item.completed_by_user.full_name.split()[0] if item.completed_by_user else "Bajarildi"
            # Truncate title if needed
            short_title = title if len(title) <= 26 else title[:24] + ".."
            btn_text = f"✅ {idx}. {short_title} ({by_name})"
        else:
            short_title = title if len(title) <= 30 else title[:28] + ".."
            btn_text = f"❌ {idx}. {short_title}"

        cb_data = f"clean_tog:{item.task_key}:{week_date.isoformat()}"
        buttons.append([InlineKeyboardButton(text=btn_text, callback_data=cb_data)])

    # Control row
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
    """List active flatmates to choose from when requesting a swap."""
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
    """Buttons sent to target user to accept or reject a duty swap."""
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
    """Confirmation buttons for /leave command ([Ha, chiqaman], [Bekor qilish])."""
    keyboard = [
        [
            InlineKeyboardButton(text="Ha, chiqaman", callback_data="confirm_leave"),
            InlineKeyboardButton(text="Bekor qilish", callback_data="cancel_leave"),
        ]
    ]
    return InlineKeyboardMarkup(inline_keyboard=keyboard)


def get_water_complete_keyboard() -> InlineKeyboardMarkup:
    """Button to record water bottle replenishment."""
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
    """Buttons for split-bill expense payment confirmation."""
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
    """Button for admin to mark fine as paid."""
    keyboard = [
        [
            InlineKeyboardButton(
                text="✅ To'landi deb belgilash",
                callback_data=f"pay_fine:{penalty_id}",
            )
        ]
    ]
    return InlineKeyboardMarkup(inline_keyboard=keyboard)
