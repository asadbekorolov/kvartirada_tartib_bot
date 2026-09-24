import re
from datetime import date
from typing import Optional
from aiogram import F, Router
from aiogram.filters import Command, CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import CallbackQuery, Message
from sqlalchemy import select

from config import settings
from database.models import PenaltyFund, User
from database.session import get_session
from keyboards.inline import (
    SLOT_NAMES,
    get_claim_profiles_keyboard,
    get_day_slots_keyboard,
    get_leave_confirm_keyboard,
)
from keyboards.reply import get_main_menu_keyboard
from services.duty_service import (
    assign_user_slot,
    get_active_users,
    get_duty_for_date,
    get_occupied_slots_map,
    leave_and_rebalance,
)

router = Router(name="start_router")


class RegistrationState(StatesGroup):
    waiting_for_slot = State()


APARTMENT_RULES_SUMMARY = (
    "📜 <b>Kvartiramizning Asosiy Tartib Qoidalari:</b>\n\n"
    "1️⃣ <b>Kunlik Navbatchilik:</b> Har kuni 1 kishi navbatchi bo'ladi. "
    "5 ta asosiy vazifa (ovqat, non, xontaxta, idishlar, axlat) to'liq bajarilishi shart.\n"
    "2️⃣ <b>Kechki Sukunat Rejimi:</b> Soat <b>22:30</b> dan boshlab xonalarda shovqin qilmaslik, "
    "qo'ng'iroqlarni balkonda amalga oshirish, video/musiqani faqat quloqchinda ko'rish shart.\n"
    "3️⃣ <b>Kir Yuvish Tartibi:</b> Har kuni belgilangan navbatdagi xonadosh kir mashinasidan foydalanadi.\n"
    "4️⃣ <b>Suv Navbati:</b> 1-xona va 2-xona navbatma-navbat 19L toza ichimlik suvi olib keladi.\n"
    "5️⃣ <b>Bozorlik va Tozalash:</b> Shanba kuni bozorlik juftligi xarid qiladi va 11 bandlik tozalash checklisti bajariladi."
)


@router.message(CommandStart())
async def handle_start(message: Message, state: FSMContext):
    """
    Handle /start command.
    1. Agar foydalanuvchi allaqachon biriktirilgan bo'lsa:
       To'g'ridan-to'g'ri salomlashib, menyuni ochib berish.
    2. Agar hali bog'lanmagan bo'lsa:
       8 ta xonadosh profil tugmalarini vertikal chiqarish (1-Click Claim).
    """
    await state.clear()
    user_id = message.from_user.id

    async with get_session() as session:
        # Check if this Telegram account is already claimed
        res = await session.execute(
            select(User).where((User.telegram_id == user_id) | (User.id == user_id))
        )
        user = res.scalar_one_or_none()

        if user and user.telegram_id == user_id and user.is_active:
            await message.answer(
                f"Assalomu alaykum, <b>{user.full_name}</b>! Profilingiz faol ({user.room_number}-Xona). "
                f"Menyudan foydalanishingiz mumkin.",
                reply_markup=get_main_menu_keyboard(),
            )
            return

        # Fetch all 8 apartment profiles
        profiles_res = await session.execute(select(User).order_by(User.order_index.asc()))
        profiles = profiles_res.scalars().all()

    first_name = message.from_user.first_name or "Xonadosh"

    welcome_text = (
        f"👋 Assalomu alaykum, {first_name}!\n\n"
        f"🏢 <b>Kvartira Bot</b> tizimiga xush kelibsiz!\n"
        f"Ushbu bot 8 kishilik xonadonimizdagi kunlik navbatchilik, kir yuvish, "
        f"2 ta xona baki suvini keltirish, bozorlik va general uborqa jarayonlarini boshqaradi.\n\n"
        f"⚠️ Sizning Telegram hisobingiz hali xonadondagi profilingizga bog'lanmagan. Iltimos, ismingizni tanlang:"
    )

    await message.answer(
        welcome_text,
        reply_markup=get_claim_profiles_keyboard(profiles),
    )


@router.callback_query(F.data.startswith("profile_claimed:"))
async def handle_already_claimed_click(callback: CallbackQuery):
    """Alert user that this profile is already taken by someone else."""
    await callback.answer("⚠️ Bu profil allaqachon bog'langan!", show_alert=True)


@router.callback_query(F.data.startswith("claim_profile:"))
async def handle_claim_profile(callback: CallbackQuery, state: FSMContext):
    """1-Click Claim: Bind Telegram account to chosen roommate profile."""
    profile_id = int(callback.data.split(":")[1])
    tg_user_id = callback.from_user.id
    tg_username = callback.from_user.username

    async with get_session() as session:
        # 1. Check if user already claimed another profile
        existing_res = await session.execute(
            select(User).where(User.telegram_id == tg_user_id)
        )
        existing_user = existing_res.scalar_one_or_none()
        if existing_user:
            await callback.answer("⚠️ Siz allaqachon profilingizni bog'lagansiz!", show_alert=True)
            return

        # 2. Check target profile
        target_res = await session.execute(select(User).where(User.id == profile_id))
        target_user = target_res.scalar_one_or_none()
        if not target_user:
            await callback.answer("⚠️ Profil topilmadi!", show_alert=True)
            return

        # 3. Anti-Hijack: Check if someone else just claimed it
        if target_user.telegram_id is not None:
            await callback.answer("⚠️ Bu profil allaqachon bog'langan!", show_alert=True)
            all_users = (await session.execute(select(User).order_by(User.order_index.asc()))).scalars().all()
            try:
                await callback.message.edit_reply_markup(reply_markup=get_claim_profiles_keyboard(all_users))
            except Exception:
                pass
            return

        # 4. Successfully claim and link Telegram details
        target_user.telegram_id = tg_user_id
        target_user.username = tg_username
        target_user.is_active = True
        session.add(target_user)
        await session.commit()

        claimed_name = target_user.full_name
        claimed_room = target_user.room_number

    await callback.answer("✅ Profil muvaffaqiyatli bog'landi!")

    confirm_msg = (
        f"✅ Profil muvaffaqiyatli bog'landi! Xush kelibsiz, <b>{claimed_name}</b> ({claimed_room}-Xona).\n\n"
        f"{APARTMENT_RULES_SUMMARY}"
    )

    try:
        await callback.message.edit_text(confirm_msg)
    except Exception:
        await callback.message.answer(confirm_msg)

    await callback.message.answer(
        "Quyidagi menyu orqali botdan foydalanishingiz mumkin:",
        reply_markup=get_main_menu_keyboard(),
    )

    # Broadcast to apartment group if configured
    if settings.GROUP_CHAT_ID:
        try:
            uname_part = f" (@{tg_username})" if tg_username else ""
            await callback.bot.send_message(
                chat_id=settings.GROUP_CHAT_ID,
                text=(
                    f"🎉 <b>Xonadosh botga ulandi!</b>\n\n"
                    f"👤 <b>{claimed_name}</b>{uname_part}\n"
                    f"🏢 Xona: <b>{claimed_room}-Xona</b>"
                ),
            )
        except Exception:
            pass


@router.message(Command("kun"))
async def handle_change_day_slot(message: Message, state: FSMContext):
    """Allow active roommate to choose or change their duty day slot."""
    user_id = message.from_user.id
    async with get_session() as session:
        user_res = await session.execute(
            select(User).where((User.telegram_id == user_id) | (User.id == user_id), User.is_active.is_(True))
        )
        user = user_res.scalar_one_or_none()
        if not user:
            await message.answer("Siz faol xonadoshlar ro'yxatida emassiz. /start orqali profilingizni tanlang.")
            return

        occupied_map = await get_occupied_slots_map(session)

    await state.set_state(RegistrationState.waiting_for_slot)
    await message.answer(
        f"📅 <b>Haftalik navbatchilik kuningizni tanlang:</b>\n"
        f"<i>Hozirgi kuningiz: {SLOT_NAMES.get(user.assigned_day, 'Belgilanmagan')}</i>\n\n"
        f"(Yashil 🟢 — bo'sh kunlar, Qulf 🔒 — band kunlar)",
        reply_markup=get_day_slots_keyboard(occupied_map),
    )


@router.callback_query(RegistrationState.waiting_for_slot, F.data.startswith("slot_occ:"))
@router.callback_query(F.data.startswith("slot_occ:"))
async def process_occupied_slot_click(callback: CallbackQuery):
    """Alert user that this day is already taken by someone else."""
    day_idx = int(callback.data.split(":")[1])
    async with get_session() as session:
        occupied_map = await get_occupied_slots_map(session)

    owner = occupied_map.get(day_idx)
    owner_name = owner.full_name if owner else "boshqa xonadosh"
    day_title = SLOT_NAMES.get(day_idx, "Ushbu kun")

    await callback.answer(
        f"⚠️ {day_title} allaqachon {owner_name} tomonidan band qilingan! Iltimos, bo'sh kunlardan birini tanlang.",
        show_alert=True,
    )


@router.callback_query(RegistrationState.waiting_for_slot, F.data.startswith("slot_sel:"))
@router.callback_query(F.data.startswith("slot_sel:"))
async def process_slot_selection(callback: CallbackQuery, state: FSMContext):
    """Assign selected day to user with concurrency check."""
    day_idx = int(callback.data.split(":")[1])
    user_id = callback.from_user.id

    async with get_session() as session:
        success, occupied_name = await assign_user_slot(session, user_id, day_idx)
        user_res = await session.execute(
            select(User).where((User.telegram_id == user_id) | (User.id == user_id))
        )
        user = user_res.scalar_one_or_none()
        occupied_map = await get_occupied_slots_map(session)

    day_title = SLOT_NAMES.get(day_idx, "Tanlangan kun")

    if not success:
        await callback.answer(
            f"⚠️ Kechirasiz, {day_title} hozirgina {occupied_name} tomonidan band qilindi! Boshqa bo'sh kunni tanlang.",
            show_alert=True,
        )
        try:
            await callback.message.edit_reply_markup(reply_markup=get_day_slots_keyboard(occupied_map))
        except Exception:
            pass
        return

    await state.clear()
    await callback.answer("✅ Kun muvaffaqiyatli band qilindi!", show_alert=False)
    await callback.message.delete()

    user_name = user.full_name if user else callback.from_user.full_name
    room_num = user.room_number if user else 1

    confirm_msg = (
        f"🎉 <b>Tabriklaymiz, {user_name}!</b>\n\n"
        f"✅ <b>Siz {day_title} kuniga navbatchi qilib belgilandingiz!</b>\n"
        f"🏢 Xona: <b>{room_num}-Xona</b>\n\n"
        f"{APARTMENT_RULES_SUMMARY}\n\n"
        f"<i>Quyidagi menyu orqali botdan foydalanishingiz mumkin:</i>"
    )

    await callback.message.answer(confirm_msg, reply_markup=get_main_menu_keyboard())


@router.message(Command("leave"))
async def handle_leave_command(message: Message):
    """Prompt user to confirm pausing/leaving the duty rotation."""
    user_id = message.from_user.id
    async with get_session() as session:
        result = await session.execute(
            select(User).where((User.telegram_id == user_id) | (User.id == user_id), User.is_active.is_(True))
        )
        user = result.scalar_one_or_none()

    if not user:
        await message.answer("Siz hozirda faol xonadoshlar ro'yxatida emassiz. /start orqali profilingizni tanlang.")
        return

    if user.assigned_day is None:
        await message.answer(
            "Siz allaqachon navbatchilik ro'yxatidan chiqqansiz.\n"
            "Qaytadan navbatchilikka qo'shilish uchun /kun yoki /start buyrug'ini bosing."
        )
        return

    day_name = SLOT_NAMES.get(user.assigned_day, "Navbatchilik kuni")

    await message.answer(
        f"⚠️ <b>Navbatchilikdan chiqish (vaqtincha dam olish / safar):</b>\n\n"
        f"Hurmatli <b>{user.full_name}</b>!\n"
        f"Haqiqatan ham navbatchilik ro'yxatidan chiqmoqchimisiz?\n\n"
        f"Sizning <b>{day_name}</b> navbatchilik kuningiz bo'shaydi va qolgan xonadoshlar o'rtasida navbat qayta muvozanatlanadi.\n"
        f"<i>(Kvartiradagi profilingiz va xonangiz saqlanib qoladi)</i>",
        reply_markup=get_leave_confirm_keyboard(),
    )


@router.callback_query(F.data == "confirm_leave")
async def process_confirm_leave(callback: CallbackQuery):
    """Pause user's duty, free their slot, and announce to group."""
    user_id = callback.from_user.id
    async with get_session() as session:
        user_res = await session.execute(
            select(User).where((User.telegram_id == user_id) | (User.id == user_id))
        )
        user = user_res.scalar_one_or_none()
        day_name = SLOT_NAMES.get(user.assigned_day, "Navbatchilik") if user and user.assigned_day is not None else "Navbatchilik"
        success = await leave_and_rebalance(session, user.id if user else user_id)

    await callback.message.edit_text(
        f"✅ <b>Siz navbatchilik ro'yxatidan chiqdingiz.</b>\n\n"
        f"Sizning <b>{day_name}</b> kuningiz bo'shatildi.\n"
        f"Qaytadan navbatchilikka qo'shilish uchun istalgan vaqtda <b>/start</b> yoki <b>/kun</b> buyrug'ini bosing va bo'sh kunni tanlang."
    )

    if settings.GROUP_CHAT_ID and user:
        try:
            await callback.bot.send_message(
                chat_id=settings.GROUP_CHAT_ID,
                text=(
                    f"📢 <b>Navbatchilik tarkibi yangilandi!</b>\n\n"
                    f"<b>{user.full_name}</b> ({user.room_number}-Xona) navbatchilikdan vaqtincha chiqdi.\n"
                    f"Uning <b>{day_name}</b> navbatchilik kuni bo'shadi!"
                ),
            )
        except Exception:
            pass


@router.callback_query(F.data == "cancel_leave")
async def process_cancel_leave(callback: CallbackQuery):
    """Cancel leave request."""
    await callback.message.edit_text("Amal bekor qilindi. Siz navbatchilik safidasiz! 🤝")


@router.message(F.text == "👥 Kvartirantlar")
@router.message(Command("azolar"))
@router.message(Command("members"))
async def handle_members(message: Message):
    """Display active roommates and their assigned duty days (Monday to Sunday + Reserve)."""
    async with get_session() as session:
        occupied_map = await get_occupied_slots_map(session)
        active_users = await get_active_users(session)

    if not active_users:
        await message.answer("Hozircha kvartirada a'zolar yo'q. /start orqali profilingizni tanlang.")
        return

    text_lines = [
        f"👥 <b>{settings.APARTMENT_NAME} faol xonadoshlari va kunlik navbat taqsimoti:</b>\n",
    ]

    for day_idx in range(8):
        day_title = SLOT_NAMES[day_idx]
        user = occupied_map.get(day_idx)
        if user:
            username_part = f" (@{user.username})" if user.username else ""
            status_tag = "" if user.telegram_id else " <i>(⏳ Kutilmoqda)</i>"
            text_lines.append(
                f"📅 <b>{day_title}:</b> <b>{user.full_name}</b>{username_part} — 🏢 <i>{user.room_number}-Xona</i>{status_tag}"
            )
        else:
            text_lines.append(f"📅 <b>{day_title}:</b> <i>🟢 Bo'sh (hali tanlanmagan)</i>")

    # Show any resting/paused roommates
    unassigned = [u for u in active_users if u.assigned_day is None]
    if unassigned:
        text_lines.append("\n⏸ <b>Navbatchilikdan vaqtincha chiqqanlar:</b>")
        for u in unassigned:
            text_lines.append(f"• {u.full_name} ({u.room_number}-Xona)")

    text_lines.append("\n<i>O'z profilingizni ko'rish: /profil | Navbatchilik kuni: /kun</i>")
    await message.answer("\n".join(text_lines))


@router.message(F.text == "👤 Profilim")
@router.message(Command("profil"))
async def handle_profile(message: Message):
    """Display user's apartment profile, room, slot, and penalty debts."""
    user_id = message.from_user.id
    async with get_session() as session:
        result = await session.execute(
            select(User).where((User.telegram_id == user_id) | (User.id == user_id))
        )
        user = result.scalar_one_or_none()
        if not user or not user.is_active:
            await message.answer("Siz tizimda hali profilingizni tanlamagansiz. /start orqali tanlang.")
            return

        penalties_res = await session.execute(
            select(PenaltyFund).where(PenaltyFund.user_id == user.id, PenaltyFund.is_paid.is_(False))
        )
        unpaid_penalties = penalties_res.scalars().all()
        total_debt = sum(p.amount for p in unpaid_penalties)

    debt_info = (
        f"⚠️ To'lanmagan jarima: <b>{total_debt:,} so'm</b> ({len(unpaid_penalties)} ta holat)"
        if total_debt > 0
        else "✅ Jarimalar mavjud emas"
    )

    day_str = (
        SLOT_NAMES.get(user.assigned_day)
        if user.assigned_day is not None
        else "⏸ Vaqtincha to'xtatilgan (/kun orqali qo'shiling)"
    )

    tg_display = f"<code>{user.telegram_id}</code>" if user.telegram_id else "<i>Bog'lanmagan</i>"

    await message.answer(
        f"👤 <b>Kvartirant Profili:</b>\n\n"
        f"Ism-familiya: <b>{user.full_name}</b>\n"
        f"Xona: <b>{user.room_number}-Xona</b>\n"
        f"Telegram ID: {tg_display}\n"
        f"Navbatchilik kuni: <b>{day_str}</b>\n"
        f"Holat: <b>Faol xonadosh</b>\n\n"
        f"💰 <b>Jarima jamg'armasi holati:</b>\n"
        f"{debt_info}\n\n"
        f"<i>Navbatchilik kunini tanlash: /kun | Navbatchilikdan chiqish: /leave</i>"
    )
