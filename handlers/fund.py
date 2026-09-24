from aiogram import F, Router
from aiogram.filters import Command
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message
from sqlalchemy import func, select
from sqlalchemy.orm import selectinload

from database.models import PenaltyFund, User
from database.session import get_session

router = Router(name="fund_router")


async def render_fund_report(session) -> tuple[str, InlineKeyboardMarkup]:
    """Calculate penalties and render fund balance with inline payment buttons."""
    # Total collected vs pending
    res_paid = await session.execute(
        select(func.sum(PenaltyFund.amount)).where(PenaltyFund.is_paid.is_(True))
    )
    total_paid = res_paid.scalar_one() or 0

    res_unpaid = await session.execute(
        select(func.sum(PenaltyFund.amount)).where(PenaltyFund.is_paid.is_(False))
    )
    total_unpaid = res_unpaid.scalar_one() or 0

    # Get all unpaid penalties with user relationship
    unpaid_list_res = await session.execute(
        select(PenaltyFund)
        .options(selectinload(PenaltyFund.user))
        .where(PenaltyFund.is_paid.is_(False))
        .order_by(PenaltyFund.id.desc())
    )
    unpaid_penalties = list(unpaid_list_res.scalars().all())

    lines = [
        "💰 <b>Kvartira Jarima Jamg'armasi va Fond Balansi</b>\n",
        f"✅ <b>Yig'ilgan (to'langan) mablag':</b> <b>{total_paid:,} so'm</b>",
        f"⏳ <b>To'lanishi kutilayotgan qarzdorlik:</b> <b>{total_unpaid:,} so'm</b>\n",
        f"━━━━━━━━━━━━━━━━━━",
        f"📋 <b>To'lanmagan jarimalar ro'yxati ({len(unpaid_penalties)} ta):</b>",
    ]

    buttons = []
    if not unpaid_penalties:
        lines.append("<i>Hozirda hech kimda to'lanmagan jarima mavjud emas. Kvartirada tartib a'lo darajada! 🎉</i>")
    else:
        for idx, p in enumerate(unpaid_penalties, 1):
            user_name = p.user.full_name if p.user else f"Foydalanuvchi #{p.user_id}"
            lines.append(
                f"<b>{idx}. {user_name}</b> — <b>{p.amount:,} so'm</b>\n"
                f"   <i>Sabab: {p.reason}</i>"
            )
            # Inline button for admin / roommate to mark fine as settled
            btn_text = f"✅ #{idx} {user_name.split()[0]} to'ladi"
            buttons.append([InlineKeyboardButton(text=btn_text, callback_data=f"pay_fine:{p.id}")])

    buttons.append([InlineKeyboardButton(text="🔄 Yangilash", callback_data="ref_fund")])
    keyboard = InlineKeyboardMarkup(inline_keyboard=buttons)

    return "\n".join(lines), keyboard


@router.message(Command("fond"))
@router.message(Command("jarimalar"))
async def handle_fund_command(message: Message):
    """Show apartment penalty fund status and unpaid fines."""
    async with get_session() as session:
        text, keyboard = await render_fund_report(session)

    await message.answer(text, reply_markup=keyboard)


@router.callback_query(F.data.startswith("pay_fine:"))
async def process_pay_fine(callback: CallbackQuery):
    """Mark penalty as paid (settled) in PenaltyFund."""
    penalty_id = int(callback.data.split(":")[1])

    async with get_session() as session:
        res = await session.execute(
            select(PenaltyFund).options(selectinload(PenaltyFund.user)).where(PenaltyFund.id == penalty_id)
        )
        penalty = res.scalar_one_or_none()

        if not penalty:
            await callback.answer("Jarima topilmadi.", show_alert=True)
            return

        if penalty.is_paid:
            await callback.answer("Ushbu jarima allaqachon to'langan.")
        else:
            penalty.is_paid = True
            session.add(penalty)
            await session.commit()
            user_name = penalty.user.full_name if penalty.user else "Xonadosh"
            await callback.answer(f"✅ {user_name}ning {penalty.amount:,} so'mlik jarimasi to'landi deb belgilandi!", show_alert=True)

        text, keyboard = await render_fund_report(session)

    try:
        await callback.message.edit_text(text, reply_markup=keyboard)
    except Exception:
        pass


@router.callback_query(F.data == "ref_fund")
async def process_refresh_fund(callback: CallbackQuery):
    """Refresh fund report."""
    async with get_session() as session:
        text, keyboard = await render_fund_report(session)

    await callback.answer("🔄 Yangilandi")
    try:
        await callback.message.edit_text(text, reply_markup=keyboard)
    except Exception:
        pass
