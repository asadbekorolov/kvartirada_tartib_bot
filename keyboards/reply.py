from aiogram.types import KeyboardButton, ReplyKeyboardMarkup


def get_main_menu_keyboard() -> ReplyKeyboardMarkup:
    """Returns the persistent main navigation keyboard."""
    keyboard = [
        [
            KeyboardButton(text="📋 Bugun"),
            KeyboardButton(text="📅 Ertaga"),
        ],
        [
            KeyboardButton(text="🗓 Haftalik grafik"),
            KeyboardButton(text="🧹 Tozalash"),
        ],
        [
            KeyboardButton(text="🔄 Almashtirish"),
            KeyboardButton(text="💧 Suv navbati"),
        ],
        [
            KeyboardButton(text="👥 Kvartirantlar"),
            KeyboardButton(text="👤 Profilim"),
        ],
    ]
    return ReplyKeyboardMarkup(
        keyboard=keyboard,
        resize_keyboard=True,
        persistent=True,
    )
