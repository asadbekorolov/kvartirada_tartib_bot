from datetime import date, timedelta
from typing import Optional
from aiogram import F, Router
from aiogram.filters import Command
from aiogram.types import CallbackQuery, Message
from sqlalchemy import select

from config import settings
from database.models import User
from database.session import get_session
from keyboards.inline import (
    get_swap_candidates_keyboard,
    get_swap_request_keyboard,
)
from services.duty_service import (
    execute_duty_swap,
    get_active_users,
    get_duty_for_date,
)

router = Router(name="swap_router")


async def find_user_next_duty_date(session, user_id: int, start_from: date, max_days: int = 21) -> Optional[date]:
    """Find the next date a user is assigned for daily duty."""
    for i in range(max_days):
        check_date = start_from + timedelta(days=i)
        user, _ = await get_duty_for_date(session, check_date)
        if user and user.id == user_id:
            return check_date
    return None


@router.message(F.text == "🔄 Almashtirish")
@router.message(Command("almashtirish"))
async def handle_swap_command(message: Message):
    """Initiate duty swap process with roommates."""
    user_id = message.from_user.id
    today = date.today()

    async with get_session() as session:
        active_users = await get_active_users(session)
        requester = next((u for u in active_users if u.id == user_id), None)
        if not requester:
            await message.answer("Siz faol xonadoshlar ro'yxatida emassiz. /start orqali qo'shiling.")
            return

        # Find requester's upcoming duty date
        requester_duty_date = await find_user_next_duty_date(session, user_id, today)
        if not requester_duty_date:
            await message.answer("Yaqin kunlarda sizga navbatchilik belgilanmagan.")
            return

        candidates = [u for u in active_users if u.id != user_id]
        if not candidates:
            await message.answer("Navbat almashtirish uchun boshqa xonadoshlar topilmadi.")
            return

    keyboard = get_swap_candidates_keyboard(candidates, requester_duty_date)
    await message.answer(
        f"🔄 <b>Navbatchilik Kunini Almashtirish</b>\n\n"
        f"Sizning yaqin navbatchilik kuningiz: <b>{requester_duty_date.strftime('%d.%m.%Y')}</b>\n"
        f"Ushbu kun o'rniga kim bilan navbat almashmoqchisiz? Quyidagi xonadoshlardan birini tanlang:",
        reply_markup=keyboard,
    )


@router.callback_query(F.data.startswith("swap_user:"))
async def process_select_swap_partner(callback: CallbackQuery):
    """Send swap request to the chosen flatmate."""
    parts = callback.data.split(":")
    target_user_id = int(parts[1])
    requester_date = date.fromisoformat(parts[2])
    requester_id = callback.from_user.id

    async with get_session() as session:
        target_res = await session.execute(select(User).where(User.id == target_user_id))
        target_user = target_res.scalar_one_or_none()

        requester_res = await session.execute(select(User).where(User.id == requester_id))
        requester_user = requester_res.scalar_one_or_none()

        if not target_user:
            await callback.answer("Tanlangan foydalanuvchi topilmadi.", show_alert=True)
            return

        target_duty_date = await find_user_next_duty_date(
            session, target_user_id, date.today() + timedelta(days=1)
        )
        if not target_duty_date:
            target_duty_date = requester_date + timedelta(days=1)

    # Prepare inline keyboard with [✅ Roziman] and [❌ Rad etaman]
    swap_kb = get_swap_request_keyboard(
        requester_id=requester_id,
        requester_date_str=requester_date.isoformat(),
        target_date_str=target_duty_date.isoformat(),
    )

    req_name = requester_user.full_name if requester_user else callback.from_user.full_name
    invite_text = (
        f"📩 <b>Navbatchilik almashish taklifi!</b>\n\n"
        f"Hurmatli <b>{target_user.full_name}</b>, xonadoshingiz <b>{req_name}</b> "
        f"siz bilan navbatchilik kunlarini almashtirishni so'ramoqda:\n\n"
        f"• Uning navbatchilik kuni: <b>{requester_date.strftime('%d.%m.%Y')}</b>\n"
        f"• Sizning navbatchilik kuningiz: <b>{target_duty_date.strftime('%d.%m.%Y')}</b>\n\n"
        f"Ushbu taklifga rozimisiz?"
    )

    sent = False
    try:
        await callback.bot.send_message(chat_id=target_user.id, text=invite_text, reply_markup=swap_kb)
        sent = True
    except Exception:
        sent = False

    if sent:
        await callback.message.edit_text(
            f"✅ Taklif <b>{target_user.full_name}</b>ga yuborildi!\n"
            f"U tasdiqlashi bilan navbatchilik grafigi avtomatik o'zgaradi va guruhga e'lon qilinadi."
        )
    else:
        await callback.message.edit_text(
            f"⚠️ <b>{target_user.full_name}</b>ga xabar yetkazib bo'lmadi. "
            f"Ehtimol, u botni ishga tushirmagan yoki bloklagan."
        )


@router.callback_query(F.data.startswith("swap_acc:"))
async def process_swap_accept(callback: CallbackQuery):
    """Target user accepts the swap via [✅ Roziman]."""
    parts = callback.data.split(":")
    requester_id = int(parts[1])
    date_req = date.fromisoformat(parts[2])
    date_target = date.fromisoformat(parts[3])
    target_user_id = callback.from_user.id

    async with get_session() as session:
        success = await execute_duty_swap(
            session=session,
            user_a_id=requester_id,
            date_a=date_req,
            user_b_id=target_user_id,
            date_b=date_target,
        )
        req_res = await session.execute(select(User).where(User.id == requester_id))
        requester = req_res.scalar_one_or_none()

    req_name = requester.full_name if requester else "Xonadoshingiz"
    target_name = callback.from_user.full_name

    await callback.message.edit_text(
        f"🎉 <b>Navbat muvaffaqiyatli almashtirildi!</b>\n\n"
        f"Sizning yangi navbatchilik kuningiz: <b>{date_req.strftime('%d.%m.%Y')}</b>\n"
        f"{req_name}ning yangi kuni: <b>{date_target.strftime('%d.%m.%Y')}</b>\n\n"
        f"Grafik bazada yangilandi va guruhga xabar berildi!"
    )

    # Notify requester
    try:
        await callback.bot.send_message(
            chat_id=requester_id,
            text=(
                f"🎉 <b>Xushxabar!</b>\n\n"
                f"<b>{target_name}</b> navbat almashish taklifingizni qabul qildi.\n"
                f"Endi sizning navbatchiligingiz: <b>{date_target.strftime('%d.%m.%Y')}</b> kungi bo'ldi!"
            ),
        )
    except Exception:
        pass

    # Broadcast notification to apartment group
    if settings.GROUP_CHAT_ID:
        try:
            await callback.bot.send_message(
                chat_id=settings.GROUP_CHAT_ID,
                text=(
                    f"🔄 <b>Navbatchilik almashinuvi tasdiqlandi!</b>\n\n"
                    f"• <b>{req_name}</b> ➡️ <b>{date_target.strftime('%d.%m.%Y')}</b>\n"
                    f"• <b>{target_name}</b> ➡️ <b>{date_req.strftime('%d.%m.%Y')}</b>\n\n"
                    f"Grafik avtomatik yangilandi. Ikkala xonadoshga ham omad! 👍"
                ),
            )
        except Exception:
            pass


@router.callback_query(F.data.startswith("swap_rej:"))
async def process_swap_reject(callback: CallbackQuery):
    """Target user rejects the swap via [❌ Rad etaman]."""
    requester_id = int(callback.data.split(":")[1])
    await callback.message.edit_text("❌ Navbat almashish taklifini rad etdingiz.")

    try:
        await callback.bot.send_message(
            chat_id=requester_id,
            text=f"⚠️ <b>{callback.from_user.full_name}</b> navbat almashish taklifingizni rad etdi.",
        )
    except Exception:
        pass


@router.callback_query(F.data == "swap_cancel")
async def process_swap_cancel(callback: CallbackQuery):
    """Cancel swap dialog."""
    await callback.message.edit_text("Navbat almashtirish bekor qilindi.")
