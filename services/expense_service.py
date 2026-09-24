from datetime import datetime
from typing import Optional, Tuple
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from database.models import Expense, ExpenseShare, User
from services.duty_service import get_active_users


async def create_expense(
    session: AsyncSession,
    payer_id: int,
    total_amount: int,
    description: str,
) -> Expense:
    """
    Bozorlik yoki umumiy xarajatni qayd etish va uni barcha hozirgi faol
    a'zolar soniga (N) teng taqsimlash (Split-Bill).
    """
    active_users = await get_active_users(session)
    n = len(active_users)
    if n <= 0:
        n = 1

    per_person = round(total_amount / n)

    expense = Expense(
        payer_id=payer_id,
        total_amount=total_amount,
        per_person=per_person,
        description=description,
    )
    session.add(expense)
    await session.flush()  # to obtain expense.id

    now = datetime.now()
    for user in active_users:
        # Payer is considered already paid
        is_payer = (user.id == payer_id)
        share = ExpenseShare(
            expense_id=expense.id,
            user_id=user.id,
            is_paid=is_payer,
            paid_at=now if is_payer else None,
        )
        session.add(share)

    await session.commit()

    # Re-fetch with relationships loaded
    result = await session.execute(
        select(Expense)
        .options(
            selectinload(Expense.payer),
            selectinload(Expense.shares).selectinload(ExpenseShare.user),
        )
        .where(Expense.id == expense.id)
    )
    return result.scalar_one()


async def get_expense_by_id(session: AsyncSession, expense_id: int) -> Optional[Expense]:
    """Retrieve expense by ID with payer and shares loaded."""
    result = await session.execute(
        select(Expense)
        .options(
            selectinload(Expense.payer),
            selectinload(Expense.shares).selectinload(ExpenseShare.user),
        )
        .where(Expense.id == expense_id)
    )
    return result.scalar_one_or_none()


async def mark_expense_share_paid(
    session: AsyncSession,
    expense_id: int,
    user_id: int,
) -> Tuple[bool, Optional[Expense]]:
    """
    Foydalanuvchi o'z ulushini to'laganini belgilash (is_paid=True).
    Agar allaqachon to'langan bo'lsa yoki topilmasa, False qaytaradi.
    """
    result = await session.execute(
        select(ExpenseShare).where(
            ExpenseShare.expense_id == expense_id,
            ExpenseShare.user_id == user_id,
        )
    )
    share = result.scalar_one_or_none()
    if not share or share.is_paid:
        expense = await get_expense_by_id(session, expense_id)
        return False, expense

    share.is_paid = True
    share.paid_at = datetime.now()
    session.add(share)
    await session.commit()

    expense = await get_expense_by_id(session, expense_id)
    return True, expense


def format_expense_report(expense: Expense) -> str:
    """Format beautiful HTML split-bill report showing payment progress."""
    payer_name = expense.payer.full_name if expense.payer else "Kvartirant"
    shares = expense.shares or []
    total_count = len(shares)
    paid_count = sum(1 for s in shares if s.is_paid)

    lines = [
        "🛒 <b>Bozorlik va Xarajatlar Hisob-kitobi (Split-Bill)</b>\n",
        f"📝 <b>Izoh / Mahsulotlar:</b> {expense.description}",
        f"💰 <b>Jami sarflangan summa:</b> <b>{expense.total_amount:,} so'm</b>",
        f"👤 <b>Bozorlik qilgan xonadosh:</b> <b>{payer_name}</b>",
        f"👥 <b>Taqsimot:</b> {total_count} kishi orasida",
        f"💵 <b>Har bir a'zoga tushgan ulush:</b> <b>{expense.per_person:,} so'm</b>\n",
        f"📊 <b>To'lov holati ({paid_count}/{total_count}):</b>",
    ]

    for share in sorted(shares, key=lambda s: (not s.is_paid, s.user.full_name if s.user else "")):
        user_name = share.user.full_name if share.user else f"ID: {share.user_id}"
        if share.user_id == expense.payer_id:
            lines.append(f"  ✅ <b>{user_name}</b> — <i>(Xarid egasi)</i>")
        elif share.is_paid:
            lines.append(f"  ✅ <b>{user_name}</b> — <i>To'landi</i>")
        else:
            lines.append(f"  ⏳ <b>{user_name}</b> — <b>{expense.per_person:,} so'm</b> kutilmoqda")

    if paid_count == total_count:
        lines.append("\n🎉 <b>Barcha xonadoshlar o'z ulushlarini to'liq to'ladilar! Hisob yopildi.</b> ✨")
    else:
        lines.append(
            "\n<i>Ulushingizni xarid egasiga bergach, pastdagi '💸 To'ladim' tugmasini bosing:</i>"
        )

    return "\n".join(lines)
