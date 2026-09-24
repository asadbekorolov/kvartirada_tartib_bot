from datetime import date
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
    get_day_slots_keyboard,
    get_leave_confirm_keyboard,
    get_room_selection_keyboard,
)
from keyboards.reply import get_main_menu_keyboard
from services.duty_service import (
    assign_user_slot,
    get_active_users,
    get_duty_for_date,
    get_occupied_slots_map,
    leave_and_rebalance,
    register_or_join,
)

router = Router(name="start_router")


class RegistrationState(StatesGroup):
    waiting_for_name = State()
    waiting_for_room = State()
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
    """Handle /start command. Register new user or display dashboard for active user."""
    user_id = message.from_user.id
    async with get_session() as session:
        result = await session.execute(select(User).where(User.id == user_id))
        user = result.scalar_one_or_none()

        if user and user.is_active:
            today = date.today()
            duty_user, _ = await get_duty_for_date(session, today)
            duty_info = (
                f"🧹 Bugungi navbatchi: <b>{duty_user.full_name}</b> ({duty_user.room_number}-Xona)"
                if duty_user
                else "🧹 <i>Navbatchi topilmadi</i>"
            )

            day_text = SLOT_NAMES.get(user.assigned_day, "Belgilanmagan")

            await message.answer(
                f"👋 Assalomu alaykum, <b>{user.full_name}</b>!\n"
                f"🏠 Kvartira: <b>{settings.APARTMENT_NAME}</b>\n"
                f"🏢 Xonangiz: <b>{user.room_number}-Xona</b>\n"
                f"📅 Belgilangan navbatchilik kuningiz: <b>{day_text}</b>\n\n"
                f"{duty_info}\n\n"
                f"Quyidagi menyu orqali kerakli bo'limni tanlang:",
                reply_markup=get_main_menu_keyboard(),
            )
            return

    # Start registration process
    await state.clear()
    await state.set_state(RegistrationState.waiting_for_name)
    await message.answer(
        f"Assalomu alaykum! 🏠 <b>{settings.APARTMENT_NAME}</b> tartib va navbatchilik botiga xush kelibsiz.\n\n"
        f"Kvartiraning navbatchilik tizimiga qo'shilish uchun, iltimos, "
        f"<b>To'liq ism-familiyangizni</b> kiriting (Masalan: <i>Ali Valiyev</i>):"
    )


@router.message(RegistrationState.waiting_for_name)
async def process_name(message: Message, state: FSMContext):
    """Step 1: Save full name and prompt for room selection via inline buttons."""
    name = message.text.strip()
    if len(name) < 2 or len(name) > 100:
        await message.answer("⚠️ Iltimos, haqiqiy ism va familiyangizni to'g'ri kiriting:")
        return

    await state.update_data(full_name=name)
    await state.set_state(RegistrationState.waiting_for_room)
    await message.answer(
        f"Rahmat, <b>{name}</b>!\n\n"
        f"Endi qaysi xonada istiqomat qilishingizni tanlang:",
        reply_markup=get_room_selection_keyboard(),
    )


@router.callback_query(RegistrationState.waiting_for_room, F.data.startswith("room_select:"))
async def process_room(callback: CallbackQuery, state: FSMContext):
    """Step 2: Save room, register in DB, and prompt for day slot selection."""
    room_number = int(callback.data.split(":")[1])
    data = await state.get_data()
    full_name = data.get("full_name")
    username = callback.from_user.username

    async with get_session() as session:
        user, is_created = await register_or_join(
            session=session,
            user_id=callback.from_user.id,
            full_name=full_name,
            room_number=room_number,
            username=username,
        )
        occupied_map = await get_occupied_slots_map(session)

    await state.set_state(RegistrationState.waiting_for_slot)
    await callback.message.delete()

    await callback.message.answer(
        f"Xonangiz: <b>{room_number}-Xona</b> deb saqlandi.\n\n"
        f"📅 <b>Haftalik navbatchilik kuningizni tanlang:</b>\n"
        f"<i>(Yashil 🟢 — bo'sh kunlar, Qulf 🔒 — boshqa xonadoshlar band qilgan kunlar)</i>",
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
        user_res = await session.execute(select(User).where(User.id == user_id))
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

    # Broadcast notification to group chat
    if settings.GROUP_CHAT_ID:
        try:
            await callback.bot.send_message(
                chat_id=settings.GROUP_CHAT_ID,
                text=(
                    f"📢 <b>Yangi navbatchi biriktirildi!</b>\n\n"
                    f"👤 <b>{user_name}</b> ({room_num}-Xona)\n"
                    f"📅 Navbatchilik kuni: <b>{day_title}</b>"
                ),
            )
        except Exception:
            pass


@router.message(Command("kun"))
async def handle_change_day_slot(message: Message, state: FSMContext):
    """Allow active roommate to choose or change their duty day slot."""
    user_id = message.from_user.id
    async with get_session() as session:
        user_res = await session.execute(select(User).where(User.id == user_id, User.is_active.is_(True)))
        user = user_res.scalar_one_or_none()
        if not user:
            await message.answer("Siz faol xonadoshlar ro'yxatida emassiz. /start orqali ro'yxatdan o'ting.")
            return

        occupied_map = await get_occupied_slots_map(session)

    await state.set_state(RegistrationState.waiting_for_slot)
    await message.answer(
        f"📅 <b>Haftalik navbatchilik kuningizni tanlang:</b>\n"
        f"<i>Hozirgi kuningiz: {SLOT_NAMES.get(user.assigned_day, 'Belgilanmagan')}</i>\n\n"
        f"(Yashil 🟢 — bo'sh kunlar, Qulf 🔒 — band kunlar)",
        reply_markup=get_day_slots_keyboard(occupied_map),
    )


@router.message(Command("leave"))
async def handle_leave_command(message: Message):
    """Prompt user to confirm leaving the apartment with inline buttons."""
    user_id = message.from_user.id
    async with get_session() as session:
        result = await session.execute(select(User).where(User.id == user_id, User.is_active.is_(True)))
        user = result.scalar_one_or_none()

    if not user:
        await message.answer("Siz hozirda faol xonadoshlar ro'yxatida emassiz.")
        return

    await message.answer(
        f"⚠️ <b>Diqqat, {user.full_name}!</b>\n\n"
        f"Rostdan ham kvartira safidan chiqmoqchimisiz?\n\n"
        f"Chiqib ketsangiz, sizning navbatchilik kuningiz bo'shatiladi "
        f"va boshqa a'zolar uchun ochiladi.",
        reply_markup=get_leave_confirm_keyboard(),
    )


@router.callback_query(F.data == "confirm_leave")
async def process_confirm_leave(callback: CallbackQuery):
    """Deactivate user, free their slot, and announce to group."""
    user_id = callback.from_user.id
    async with get_session() as session:
        user_res = await session.execute(select(User).where(User.id == user_id))
        user = user_res.scalar_one_or_none()
        day_name = SLOT_NAMES.get(user.assigned_day, "Navbat") if user else "Navbat"
        success = await leave_and_rebalance(session, user_id)
        active_users = await get_active_users(session)

    await callback.message.edit_text(
        f"✅ <b>Siz kvartira a'zoligidan chiqarildingiz.</b>\n\n"
        f"Sizning <b>{day_name}</b> kuningiz bo'shatildi.\n"
        f"Kelgusida qaytmoqchi bo'lsangiz, /start orqali qayta qo'shilishingiz mumkin."
    )

    if settings.GROUP_CHAT_ID and user:
        try:
            await callback.bot.send_message(
                chat_id=settings.GROUP_CHAT_ID,
                text=(
                    f"📢 <b>Kvartira tarkibi yangilandi!</b>\n\n"
                    f"<b>{user.full_name}</b> kvartirani tark etdi.\n"
                    f"Uning <b>{day_name}</b> navbatchilik kuni bo'shadi!"
                ),
            )
        except Exception:
            pass


@router.callback_query(F.data == "cancel_leave")
async def process_cancel_leave(callback: CallbackQuery):
    """Cancel leave request."""
    await callback.message.edit_text("Amal bekor qilindi. Siz kvartiramiz safidasiz! 🤝")


@router.message(F.text == "👥 Kvartirantlar")
@router.message(Command("azolar"))
@router.message(Command("members"))
async def handle_members(message: Message):
    """Display active roommates and their assigned duty days (Monday to Sunday + Reserve)."""
    async with get_session() as session:
        occupied_map = await get_occupied_slots_map(session)
        active_users = await get_active_users(session)

    if not active_users:
        await message.answer("Hozircha kvartirada faol a'zolar yo'q. /start orqali qo'shiling.")
        return

    text_lines = [
        f"👥 <b>{settings.APARTMENT_NAME} faol xonadoshlari va kunlik navbat taqsimoti:</b>\n",
    ]

    for day_idx in range(8):
        day_title = SLOT_NAMES[day_idx]
        user = occupied_map.get(day_idx)
        if user:
            username_part = f" (@{user.username})" if user.username else ""
            text_lines.append(
                f"📅 <b>{day_title}:</b> <b>{user.full_name}</b>{username_part} — 🏢 <i>{user.room_number}-Xona</i>"
            )
        else:
            text_lines.append(f"📅 <b>{day_title}:</b> <i>🟢 Bo'sh (hali tanlanmagan)</i>")

    text_lines.append("\n<i>O'z kuningizni tanlash yoki o'zgartirish uchun: /kun buyrug'idan foydalaning.</i>")
    await message.answer("\n".join(text_lines))


@router.message(F.text == "👤 Profilim")
@router.message(Command("profil"))
async def handle_profile(message: Message):
    """Display user's apartment profile, room, slot, and penalty debts."""
    user_id = message.from_user.id
    async with get_session() as session:
        result = await session.execute(select(User).where(User.id == user_id))
        user = result.scalar_one_or_none()
        if not user or not user.is_active:
            await message.answer("Siz tizimda faol a'zo emassiz. /start orqali ro'yxatdan o'ting.")
            return

        penalties_res = await session.execute(
            select(PenaltyFund).where(PenaltyFund.user_id == user_id, PenaltyFund.is_paid.is_(False))
        )
        unpaid_penalties = penalties_res.scalars().all()
        total_debt = sum(p.amount for p in unpaid_penalties)

    debt_info = (
        f"⚠️ To'lanmagan jarima: <b>{total_debt:,} so'm</b> ({len(unpaid_penalties)} ta holat)"
        if total_debt > 0
        else "✅ Jarimalar mavjud emas"
    )

    day_str = SLOT_NAMES.get(user.assigned_day, "Tanlanmagan (/kun orqali tanlang)")

    await message.answer(
        f"👤 <b>Kvartirant Profili:</b>\n\n"
        f"Ism-familiya: <b>{user.full_name}</b>\n"
        f"Telegram ID: <code>{user.id}</code>\n"
        f"Xona: <b>{user.room_number}-Xona</b>\n"
        f"Navbatchilik kuni: <b>{day_str}</b>\n"
        f"Holat: <b>Faol xonadosh</b>\n\n"
        f"💰 <b>Jarima jamg'armasi holati:</b>\n"
        f"{debt_info}\n\n"
        f"<i>Kuningizni o'zgartirish: /kun | Chiqish: /leave</i>"
    )
