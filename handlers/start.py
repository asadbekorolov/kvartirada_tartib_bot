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
from keyboards.inline import get_leave_confirm_keyboard, get_room_selection_keyboard
from keyboards.reply import get_main_menu_keyboard
from services.duty_service import (
    get_active_users,
    get_duty_for_date,
    leave_and_rebalance,
    register_or_join,
)

router = Router(name="start_router")


class RegistrationState(StatesGroup):
    waiting_for_name = State()
    waiting_for_room = State()


APARTMENT_RULES_SUMMARY = (
    "📜 <b>Kvartiramizning Asosiy Tartib Qoidalari:</b>\n\n"
    "1️⃣ <b>Kunlik Navbatchilik:</b> Har kuni 1 kishi navbatchi bo'ladi. "
    "5 ta asosiy vazifa: ovqat, non/dasturxon, xontaxta, umumiy idishlar/qozon, oshxona va hojatxona axlatini to'kish.\n"
    "2️⃣ <b>Kechki Sukunat Rejimi:</b> Soat <b>22:30</b> dan boshlab xonalarda shovqin qilmaslik, "
    "telefon suhbatlarini balkonda o'tkazish, video va musiqalarni faqat quloqchinda ko'rish shart.\n"
    "3️⃣ <b>Kir Yuvish Tartibi:</b> Har kuni belgilangan navbatdagi xonadosh kir yuvish mashinasidan foydalanish huquqiga ega.\n"
    "4️⃣ <b>Suv Navbati:</b> 1-xona va 2-xona navbatma-navbat 19L toza ichimlik suvi ta'minotiga mas'ul.\n"
    "5️⃣ <b>Dam Olish Kuni:</b> Shanba/Yakshanba kunlari bozorlik juftligi xarid qiladi va barcha xonadoshlar 11 bandlik tozalash checklistini bajaradi."
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

            await message.answer(
                f"👋 Assalomu alaykum, <b>{user.full_name}</b>!\n"
                f"🏠 Kvartira: <b>{settings.APARTMENT_NAME}</b>\n"
                f"🏢 Xonangiz: <b>{user.room_number}-Xona</b>\n"
                f"🔢 Navbat tartib raqamingiz (index): <b>{user.order_index}</b> (Slot: #{user.order_index + 1})\n\n"
                f"{duty_info}\n\n"
                f"Quyidagi menyu orqali kerakli bo'limni tanlang:",
                reply_markup=get_main_menu_keyboard(),
            )
            return

    # User is not registered or currently inactive
    await state.clear()
    await state.set_state(RegistrationState.waiting_for_name)
    await message.answer(
        f"Assalomu alaykum! 🏠 <b>{settings.APARTMENT_NAME}</b> tartib va navbatchilik botiga xush kelibsiz.\n\n"
        f"Kvartiraning dinamik navbatchilik tizimiga qo'shilish uchun, iltimos, "
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
    """Step 2: Save room, assign slot index, rebalance, and display rules summary."""
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
        active_users = await get_active_users(session)
        total = len(active_users)

    await state.clear()
    await callback.message.delete()

    await callback.message.answer(
        f"🎉 <b>Tabriklaymiz, {user.full_name}! Siz muvaffaqiyatli ro'yxatdan o'tdingiz.</b>\n\n"
        f"🏢 Xona: <b>{user.room_number}-Xona</b>\n"
        f"🔢 Navbat tartib raqamingiz: <b>{user.order_index}</b> (Jami a'zolar: {total} ta)\n\n"
        f"{APARTMENT_RULES_SUMMARY}\n\n"
        f"<i>Barcha buyruqlardan foydalanish uchun pastdagi menyu tugmalaridan foydalanishingiz mumkin.</i>",
        reply_markup=get_main_menu_keyboard(),
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
        f"Chiqib ketsangiz, qolgan barcha a'zolarning navbat slotlari "
        f"avtomatik uzluksiz qayta muvozanatlanadi (rebalance qilinadi).",
        reply_markup=get_leave_confirm_keyboard(),
    )


@router.callback_query(F.data == "confirm_leave")
async def process_confirm_leave(callback: CallbackQuery):
    """Deactivate user, rebalance remaining members and announce to group."""
    user_id = callback.from_user.id
    async with get_session() as session:
        user_res = await session.execute(select(User).where(User.id == user_id))
        user = user_res.scalar_one_or_none()
        success = await leave_and_rebalance(session, user_id)
        active_users = await get_active_users(session)

    await callback.message.edit_text(
        f"✅ <b>Siz kvartira a'zoligidan chiqarildingiz.</b>\n\n"
        f"Qolgan {len(active_users)} ta xonadosh uchun navbatlar uzluksiz qayta indekslandi.\n"
        f"Kelgusida qaytmoqchi bo'lsangiz, /start orqali qayta qo'shilishingiz mumkin."
    )

    if settings.GROUP_CHAT_ID and user:
        try:
            await callback.bot.send_message(
                chat_id=settings.GROUP_CHAT_ID,
                text=(
                    f"📢 <b>Kvartira tarkibi yangilandi!</b>\n\n"
                    f"<b>{user.full_name}</b> kvartirani tark etdi.\n"
                    f"Qolgan {len(active_users)} kishi uchun navbatchilik zanjiri uzluksiz qayta muvozanatlandi!"
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
    """Display active roommates, their room, and order_index (0 to N-1)."""
    async with get_session() as session:
        active_users = await get_active_users(session)

    if not active_users:
        await message.answer("Hozircha kvartirada faol a'zolar yo'q. /start orqali qo'shiling.")
        return

    text_lines = [
        f"👥 <b>{settings.APARTMENT_NAME} faol xonadoshlari ({len(active_users)} kishi):</b>\n",
    ]
    for user in active_users:
        username_part = f" (@{user.username})" if user.username else ""
        text_lines.append(
            f"<b>Tartib: {user.order_index}</b> (Slot #{user.order_index + 1}) • {user.full_name}{username_part} — 🏢 <i>{user.room_number}-Xona</i>"
        )

    text_lines.append("\n<i>Tartib raqamlari (0 dan N-1 gacha) Round-Robin navbat zanjirini belgilaydi.</i>")
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

        active_users = await get_active_users(session)
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

    await message.answer(
        f"👤 <b>Kvartirant Profili:</b>\n\n"
        f"Ism-familiya: <b>{user.full_name}</b>\n"
        f"Telegram ID: <code>{user.id}</code>\n"
        f"Xona: <b>{user.room_number}-Xona</b>\n"
        f"Navbat tartib raqami: <b>{user.order_index}</b> (Slot: #{user.order_index + 1} / {len(active_users)})\n"
        f"Holat: <b>Faol xonadosh</b>\n\n"
        f"💰 <b>Jarima jamg'armasi holati:</b>\n"
        f"{debt_info}\n\n"
        f"<i>Kvartiradan chiqmoqchi bo'lsangiz: /leave buyrug'idan foydalaning.</i>"
    )
