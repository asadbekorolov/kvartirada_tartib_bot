import re
from aiogram import F, Router
from aiogram.filters import Command
from aiogram.types import CallbackQuery, Message
from sqlalchemy import select

from database.models import User
from database.session import get_session
from keyboards.inline import get_expense_inline_keyboard
from services.expense_service import (
    create_expense,
    format_expense_report,
    get_expense_by_id,
    mark_expense_share_paid,
)

router = Router(name="expense_router")


def parse_expense_text(text: str):
    """
    Parse text formatted as:
    /bozorlik 360000 Go'sht va kartoshka
    or /bozorlik 360,000 Go'sht
    Returns (amount: int, description: str) or None.
    """
    # Remove command prefix
    content = re.sub(r"^/bozorlik(@\w+)?", "", text.strip(), flags=re.IGNORECASE).strip()
    if not content:
        return None

    # Match first numerical value (amount)
    match = re.match(r"^([\d\s.,]+)(.*)$", content)
    if not match:
        return None

    raw_amount = match.group(1).replace(" ", "").replace(",", "").replace(".", "").strip()
    description = match.group(2).strip()

    if not raw_amount.isdigit():
        return None

    amount = int(raw_amount)
    if amount <= 0:
        return None

    if not description:
        description = "Bozorlik va umumiy xaridlar"

    return amount, description


@router.message(Command("bozorlik"))
@router.message(F.caption.startswith("/bozorlik"))
async def handle_bozorlik_command(message: Message):
    """
    Handle /bozorlik command via text or photo with caption.
    Splits total amount among all active flatmates.
    """
    user_id = message.from_user.id
    raw_text = message.text or message.caption or ""

    parsed = parse_expense_text(raw_text)
    if not parsed:
        await message.answer(
            "🛒 <b>Bozorlik xarajatini kiritish bo'yicha qo'llanma:</b>\n\n"
            "Format: <code>/bozorlik [summa] [izoh]</code>\n\n"
            "<b>Misollar:</b>\n"
            "• <code>/bozorlik 360000 Go'sht, yog' va sabzavotlar</code>\n"
            "• <code>/bozorlik 150 000 Nonushta mahsulotlari</code>\n\n"
            "📸 <i>Shuningdek, xarid cheki rasmini yuborib, rasm ostiga shu buyruqni yozishingiz ham mumkin!</i>"
        )
        return

    amount, description = parsed

    async with get_session() as session:
        # Check if user is registered
        u_res = await session.execute(select(User).where(User.id == user_id, User.is_active.is_(True)))
        payer = u_res.scalar_one_or_none()
        if not payer:
            await message.answer("Siz faol xonadoshlar ro'yxatida emassiz. /start orqali ro'yxatdan o'ting.")
            return

        expense = await create_expense(
            session=session,
            payer_id=user_id,
            total_amount=amount,
            description=description,
        )

    report_text = format_expense_report(expense)
    keyboard = get_expense_inline_keyboard(expense.id)

    # Reply to user or to photo
    await message.reply(report_text, reply_markup=keyboard)

    # Broadcast to apartment group if recorded in private chat
    if settings.GROUP_CHAT_ID and message.chat.id != settings.GROUP_CHAT_ID:
        try:
            await message.bot.send_message(
                chat_id=settings.GROUP_CHAT_ID,
                text=f"🛒 <b>Yangi bozorlik xarajati kiritildi!</b>\n\n{report_text}",
                reply_markup=keyboard,
            )
        except Exception:
            pass


@router.callback_query(F.data.startswith("pay_exp:"))
async def process_pay_expense(callback: CallbackQuery):
    """Mark user's share as paid and update the split-bill message."""
    expense_id = int(callback.data.split(":")[1])
    user_id = callback.from_user.id

    async with get_session() as session:
        success, expense = await mark_expense_share_paid(
            session=session,
            expense_id=expense_id,
            user_id=user_id,
        )

    if not expense:
        await callback.answer("Xarajat topilmadi.", show_alert=True)
        return

    if success:
        await callback.answer(f"✅ Sizning {expense.per_person:,} so'mlik ulushingiz to'landi deb belgilandi!", show_alert=True)
    else:
        await callback.answer("Sizning ulushingiz allaqachon to'langan yoki siz ushbu hisobda emassiz.")

    updated_text = format_expense_report(expense)
    keyboard = get_expense_inline_keyboard(expense.id)

    try:
        await callback.message.edit_text(updated_text, reply_markup=keyboard)
    except Exception:
        pass


@router.callback_query(F.data.startswith("ref_exp:"))
async def process_refresh_expense(callback: CallbackQuery):
    """Refresh split-bill status."""
    expense_id = int(callback.data.split(":")[1])
    async with get_session() as session:
        expense = await get_expense_by_id(session, expense_id)

    if not expense:
        await callback.answer("Xarajat topilmadi.")
        return

    await callback.answer("🔄 Yangilandi")
    updated_text = format_expense_report(expense)
    keyboard = get_expense_inline_keyboard(expense.id)

    try:
        await callback.message.edit_text(updated_text, reply_markup=keyboard)
    except Exception:
        pass
