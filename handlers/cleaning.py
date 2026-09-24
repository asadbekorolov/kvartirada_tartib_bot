from datetime import date
from aiogram import F, Router
from aiogram.filters import Command
from aiogram.types import CallbackQuery, Message

from config import settings
from database.session import get_session
from keyboards.inline import get_checklist_inline_keyboard
from services.cleaning_service import (
    CLEANING_TASKS,
    get_or_create_week_checklist,
    get_weekend_date_for,
    render_progress_bar,
    toggle_checklist_task,
)

router = Router(name="cleaning_router")


def build_cleaning_message_text(items, week_date: date) -> str:
    """Format checklist overview text with progress bar and detailed task statuses."""
    total = len(items)
    completed = sum(1 for item in items if item.is_done)
    progress_bar = render_progress_bar(completed, total)
    is_all_finished = (completed == total and total > 0)

    lines = [
        f"🧹 <b>Katta Tozalash: 11 Bandlik Interaktiv Checklist</b>",
        f"📅 Hafta yakuni: <b>{week_date.strftime('%d.%m.%Y')}</b>\n",
        f"<b>Bajarilish ko'rsatkichi:</b>",
        f"<code>{progress_bar}</code>\n",
    ]

    if is_all_finished:
        lines.append(
            "🎉 <b>Barcha 11 ta tozalash vazifasi muvaffaqiyatli yakunlandi!</b>\n"
            "Kvartirada to'liq tartib, tozalik va ozodalik ta'minlandi! Barcha xonadoshlarga rahmat! ✨\n"
        )
    else:
        lines.append(
            "Quyidagi tugmalardan birini bosib, siz bajargan vazifani belgilang. "
            "Har bir band <b>[❌]</b> holatidan <b>[✅]</b> holatiga o'tadi va ismingiz qayd etiladi:\n"
        )

    # Detailed status list
    lines.append("<b>Vazifalar holati:</b>")
    for idx, item in enumerate(items, 1):
        task_name = CLEANING_TASKS.get(item.task_key, item.task_key)
        if item.is_done:
            by_user = item.completed_by_user.full_name if item.completed_by_user else "Bajarildi"
            lines.append(f"  ✅ <b>{idx}. {task_name}</b> — <i>{by_user}</i>")
        else:
            lines.append(f"  ❌ {idx}. {task_name}")

    return "\n".join(lines)


@router.message(F.text == "🧹 Tozalash")
@router.message(Command("tozalash"))
async def handle_cleaning_checklist(message: Message):
    """Display the 11-step interactive weekend cleaning checklist."""
    weekend_date = get_weekend_date_for()

    async with get_session() as session:
        items = await get_or_create_week_checklist(session, weekend_date)

    text = build_cleaning_message_text(items, weekend_date)
    keyboard = get_checklist_inline_keyboard(items, weekend_date)
    await message.answer(text, reply_markup=keyboard)


@router.callback_query(F.data.startswith("clean_tog:"))
async def process_task_toggle(callback: CallbackQuery):
    """Toggle chore from [❌] to [✅] and persist completion state with user attribution."""
    parts = callback.data.split(":")
    task_key = parts[1]
    week_date = date.fromisoformat(parts[2])
    user_id = callback.from_user.id

    async with get_session() as session:
        item, new_status = await toggle_checklist_task(
            session=session,
            task_key=task_key,
            user_id=user_id,
            week_date=week_date,
        )
        items = await get_or_create_week_checklist(session, week_date)

    alert_msg = "✅ Vazifa bajarildi deb qayd etildi!" if new_status else "❌ Vazifa belgisi olib tashlandi"
    await callback.answer(alert_msg)

    text = build_cleaning_message_text(items, week_date)
    keyboard = get_checklist_inline_keyboard(items, week_date)

    try:
        await callback.message.edit_text(text, reply_markup=keyboard)
    except Exception:
        pass

    # If all 11 chores completed just now, announce to group chat
    all_done = all(it.is_done for it in items)
    if all_done and new_status and settings.GROUP_CHAT_ID:
        try:
            await callback.bot.send_message(
                chat_id=settings.GROUP_CHAT_ID,
                text=(
                    f"🎉 <b>Ajoyib xabar! Katta tozalash yakunlandi!</b>\n\n"
                    f"Barcha 11 ta tozalash vazifalari xonadoshlar tomonidan to'liq bajarildi.\n"
                    f"Kvartirada poklik va shinamlik hukm surmoqda! Rahmat barchaga! 🧹✨"
                ),
            )
        except Exception:
            pass


@router.callback_query(F.data.startswith("clean_ref:"))
async def process_checklist_refresh(callback: CallbackQuery):
    """Refresh the 11-step checklist state."""
    week_date_str = callback.data.split(":")[1]
    week_date = date.fromisoformat(week_date_str)

    async with get_session() as session:
        items = await get_or_create_week_checklist(session, week_date)

    text = build_cleaning_message_text(items, week_date)
    keyboard = get_checklist_inline_keyboard(items, week_date)

    await callback.answer("🔄 Checklist yangilandi")
    try:
        await callback.message.edit_text(text, reply_markup=keyboard)
    except Exception:
        pass
