from datetime import date, timedelta
from aiogram import F, Router
from aiogram.filters import Command
from aiogram.types import CallbackQuery, Message

from config import settings
from database.models import DutyStatus
from database.session import get_session
from keyboards.inline import get_duty_complete_keyboard, get_water_complete_keyboard
from services.duty_service import (
    complete_water_duty,
    get_duty_for_date,
    get_laundry_duty_for_date,
    get_water_duty_schedule,
    get_weekly_schedule,
    get_weekend_grocery_duty,
    mark_daily_duty_completed,
)

router = Router(name="duty_router")

UZ_DAYS = {
    0: "Dushanba",
    1: "Seshanba",
    2: "Chorshanba",
    3: "Payshanba",
    4: "Juma",
    5: "Shanba",
    6: "Yakshanba",
}

DUTY_5_TASKS = (
    "<b>Kunlik navbatchining 5 ta asosiy vazifasi:</b>\n"
    "1️⃣ 🍲 <b>Ovqat:</b> Kechki taomni tayyorlash yoki umumiy ovqatga qarash\n"
    "2️⃣ 🍞 <b>Non va dasturxon:</b> Dasturxon atrofini toza saqlash, non bo'lishini nazorat qilish\n"
    "3️⃣ 🧽 <b>Xontaxta:</b> Xontaxta va oshxona stollarini nam latta bilan artib tozalash\n"
    "4️⃣ 🍳 <b>Idishlar:</b> Umumiy idish-tovoqlar va qozonlarni yuvib qo'yish\n"
    "5️⃣ 🗑 <b>Axlat:</b> Oshxona va hojatxona axlat chelaklarini to'plash va tashlab kelish"
)


@router.message(F.text == "📋 Bugun")
@router.message(Command("bugun"))
async def handle_today_duty(message: Message):
    """Show today's daily duty holder, 5 main tasks, and laundry slot holder."""
    today = date.today()
    day_name = UZ_DAYS[today.weekday()]

    async with get_session() as session:
        user, record = await get_duty_for_date(session, today)
        laundry_user = await get_laundry_duty_for_date(session, today)

    if not user:
        await message.answer(
            "⚠️ Kvartirada faol a'zolar mavjud emas.\n"
            "Avval /start orqali xonadoshlarni ro'yxatdan o'tkazing."
        )
        return

    status_str = "⏳ <b>Bajarilishi kutilmoqda</b>"
    if record:
        if record.status == DutyStatus.COMPLETED:
            status_str = "✅ <b>Muvaffaqiyatli bajarildi</b>"
        elif record.status == DutyStatus.SWAPPED:
            status_str = "🔄 <b>O'zaro almashtirilgan</b>"
        elif record.status == DutyStatus.FINED:
            status_str = "❌ <b>Bajarilmadi (Jarima qo'llangan)</b>"

    laundry_text = (
        f"🧺 <b>Bugungi kir yuvish huquqi:</b> <b>{laundry_user.full_name}</b> ({laundry_user.room_number}-Xona)"
        if laundry_user
        else "🧺 <i>Kir yuvish navbatchisi topilmadi</i>"
    )

    text = (
        f"📋 <b>Bugungi Kunlik Navbatchilik:</b>\n\n"
        f"📅 Sana: <b>{today.strftime('%d.%m.%Y')} ({day_name})</b>\n"
        f"🧹 Navbatchi: <b>{user.full_name}</b>\n"
        f"🏢 Xona: <b>{user.room_number}-Xona</b> (Tartib: {user.order_index})\n"
        f"📌 Holat: {status_str}\n\n"
        f"{laundry_text}\n\n"
        f"{DUTY_5_TASKS}\n\n"
        f"<i>Vazifalarni yakunlagach, quyidagi tugma orqali tasdiqlang:</i>"
    )

    keyboard = get_duty_complete_keyboard(today)
    await message.answer(text, reply_markup=keyboard)


@router.callback_query(F.data.startswith("duty_complete:"))
async def process_duty_complete(callback: CallbackQuery):
    """Mark daily duty as completed."""
    date_str = callback.data.split(":")[1]
    target_date = date.fromisoformat(date_str)

    async with get_session() as session:
        record = await mark_daily_duty_completed(
            session=session,
            user_id=callback.from_user.id,
            duty_date=target_date,
        )

    await callback.answer("✅ Navbatchilik bajarildi deb belgilandi!", show_alert=True)
    await callback.message.edit_text(
        f"🎉 <b>Rahmat! Bugungi barcha 5 ta vazifa to'liq bajarildi deb qabul qilindi.</b>\n\n"
        f"📅 Sana: <b>{target_date.strftime('%d.%m.%Y')}</b>\n"
        f"👤 Bajaruvchi: <b>{callback.from_user.full_name}</b>\n"
        f"✅ Holat: <b>Bajarildi</b>\n\n"
        f"<i>Kvartirada tozalik va ozodalik ta'minlandi! ✨</i>"
    )

    if settings.GROUP_CHAT_ID:
        try:
            await callback.bot.send_message(
                chat_id=settings.GROUP_CHAT_ID,
                text=(
                    f"✅ <b>{callback.from_user.full_name}</b> bugungi navbatchilik vazifalarini "
                    f"(ovqat, dasturxon, idishlar va axlat) to'liq yakunladi. Rahmat! ✨"
                ),
            )
        except Exception:
            pass


@router.message(F.text == "📅 Ertaga")
@router.message(Command("ertaga"))
async def handle_tomorrow_duty(message: Message):
    """Show tomorrow's duty holder and laundry slot holder."""
    tomorrow = date.today() + timedelta(days=1)
    day_name = UZ_DAYS[tomorrow.weekday()]

    async with get_session() as session:
        user, record = await get_duty_for_date(session, tomorrow)
        laundry_user = await get_laundry_duty_for_date(session, tomorrow)

    if not user:
        await message.answer("⚠️ Ertangi navbatchi topilmadi.")
        return

    note = " (Navbat almashtirilgan)" if record and record.status == DutyStatus.SWAPPED else ""

    laundry_text = (
        f"🧺 <b>Ertangi kir yuvish huquqi:</b> <b>{laundry_user.full_name}</b> ({laundry_user.room_number}-Xona)"
        if laundry_user
        else "—"
    )

    text = (
        f"📅 <b>Ertangi Navbatchilik Grafigi:</b>\n\n"
        f"Sana: <b>{tomorrow.strftime('%d.%m.%Y')} ({day_name})</b>\n"
        f"🧹 Navbatchi: <b>{user.full_name}</b>{note}\n"
        f"🏢 Xona: <b>{user.room_number}-Xona</b> (Tartib: {user.order_index})\n\n"
        f"{laundry_text}\n\n"
        f"<b>Eslatma:</b> Ertaga 5 ta asosiy vazifani bajarishga vaqtingiz bo'lmasa, "
        f"<b>/almashtirish</b> buyrug'i orqali boshqa xonadosh bilan o'rin almashing."
    )
    await message.answer(text)


@router.message(F.text == "🗓 Haftalik grafik")
@router.message(Command("haftalik"))
async def handle_weekly_schedule(message: Message):
    """Show complete 7-day schedule with duty holders and laundry turns."""
    today = date.today()
    monday = today - timedelta(days=today.weekday())
    sunday = monday + timedelta(days=6)

    async with get_session() as session:
        schedule = await get_weekly_schedule(session, start_date=monday)
        shopper1, shopper2 = await get_weekend_grocery_duty(session, sunday)

    if not schedule or not schedule[0]["user"]:
        await message.answer("⚠️ Navbat jadvalini tuzish uchun a'zolar yetarli emas.")
        return

    status_icons = {
        DutyStatus.COMPLETED: "✅",
        DutyStatus.SWAPPED: "🔄",
        DutyStatus.FINED: "❌",
        DutyStatus.PENDING: "⏳",
    }

    lines = [
        f"🗓 <b>Haftalik To'liq Navbatchilar Jadvali</b>\n"
        f"({monday.strftime('%d.%m')} — {sunday.strftime('%d.%m.%Y')}):\n",
    ]

    for item in schedule:
        cur_date = item["date"]
        user = item["user"]
        laundry = item.get("laundry_user")
        day_str = item["day_name"]
        icon = status_icons.get(item["status"], "⏳")

        user_name = f"{user.full_name} ({user.room_number}-Xona)" if user else "—"
        laundry_name = f"🧺 Kir: {laundry.full_name.split()[0]}" if laundry else ""

        is_today = cur_date == today
        pointer = "👉 " if is_today else "   "
        bold_s = "<b>" if is_today else ""
        bold_e = "</b> (Bugun)" if is_today else ""

        lines.append(
            f"{pointer}{bold_s}{cur_date.strftime('%d.%m')} {day_str[:3]}: {icon} {user_name} | {laundry_name}{bold_e}"
        )

    sh1_name = f"{shopper1.full_name} ({shopper1.room_number}-Xona)" if shopper1 else "—"
    sh2_name = f"{shopper2.full_name} ({shopper2.room_number}-Xona)" if shopper2 else "—"

    lines.append("\n🛍 <b>Dam Olish Kuni Bozorlik Juftligi:</b>")
    lines.append(f"1. {sh1_name}")
    lines.append(f"2. {sh2_name}")
    lines.append("\n<i>Belgilar: ✅ Bajarildi | ⏳ Kutilmoqda | 🔄 Almashgan | ❌ Jarima</i>")

    await message.answer("\n".join(lines))


@router.message(F.text == "💧 Suv navbati")
@router.message(Command("suv"))
async def handle_water_duty(message: Message):
    """
    1-xona va 2-xona bo'yicha 2 haftalik suv olib kelish navbatini aniq ko'rsatish
    (qaysi xona navbatdaligi va xona ichidagi mas'ul a'zo).
    """
    async with get_session() as session:
        data = await get_water_duty_schedule(session)

    cur_room = data["current_room"]
    cur_user = data["current_user"]
    next_room = data["next_room"]
    next_user = data["next_user"]
    c_start, c_end = data["current_week_dates"]
    n_start, n_end = data["next_week_dates"]

    cur_user_str = (
        f"<b>{cur_user.full_name}</b> (🏢 {cur_user.room_number}-Xona)"
        if cur_user
        else "<i>Belgilanmagan</i>"
    )
    next_user_str = (
        f"<b>{next_user.full_name}</b> (🏢 {next_user.room_number}-Xona)"
        if next_user
        else "<i>Belgilanmagan</i>"
    )

    text = (
        f"💧 <b>19L Toza Ichimlik Suvi Navbati Tizimi</b>\n\n"
        f"Navbat 1-xona va 2-xona o'rtasida haftama-hafta almashib boradi.\n\n"
        f"📍 <b>HOZIRGI NAVBATDAGI XONA:</b> 🏢 <b>{cur_room}-XONA</b>\n"
        f"👤 <b>Xona ichidagi mas'ul xonadosh:</b> {cur_user_str}\n\n"
        f"━━━━━━━━━━━━━━━━━━\n"
        f"📅 <b>2 Haftalik Suv Navbati Grafigi:</b>\n\n"
        f"1️⃣ <b>1-Hafta (Joriy: {c_start.strftime('%d.%m')} - {c_end.strftime('%d.%m')}):</b>\n"
        f"   • Navbat: 🏢 <b>{cur_room}-Xona</b>\n"
        f"   • Mas'ul: {cur_user_str}\n\n"
        f"2️⃣ <b>2-Hafta (Keyingi: {n_start.strftime('%d.%m')} - {n_end.strftime('%d.%m')}):</b>\n"
        f"   • Navbat: 🏢 <b>{next_room}-Xona</b>\n"
        f"   • Mas'ul: {next_user_str}\n"
        f"━━━━━━━━━━━━━━━━━━\n"
        f"<i>Jami keltirilgan suv ballonlari: {data['total_deliveries']} ta</i>\n\n"
        f"Yangi suv balloni keltirilganda yoki buyurtma qilinganda, quyidagi tugmani bosing:"
    )

    await message.answer(text, reply_markup=get_water_complete_keyboard())


@router.callback_query(F.data == "water_complete")
async def process_water_complete(callback: CallbackQuery):
    """Record water delivery and advance the 2-week room rotation."""
    user_id = callback.from_user.id
    async with get_session() as session:
        user = await complete_water_duty(session, user_id)
        next_data = await get_water_duty_schedule(session)

    await callback.answer("💧 Suv keltirilgani tasdiqlandi!", show_alert=True)

    n_room = next_data["current_room"]
    n_user = next_data["current_user"]
    n_user_str = f"<b>{n_user.full_name}</b> (🏢 {n_user.room_number}-Xona)" if n_user else f"🏢 {n_room}-Xona"

    msg_text = (
        f"💧 <b>Yangi 19L suv keltirilgani qayd etildi!</b>\n\n"
        f"Olib kelgan xonadosh: <b>{user.full_name}</b> (🏢 {user.room_number}-Xona)\n\n"
        f"👉 <b>Keyingi navbat:</b> 🏢 <b>{n_room}-XONA</b>\n"
        f"👤 Keyingi mas'ul: {n_user_str}\n\n"
        f"<i>Katta rahmat! Toza ichimlik suvi ta'minlandi! 🥤</i>"
    )

    await callback.message.edit_text(msg_text)

    if settings.GROUP_CHAT_ID:
        try:
            await callback.bot.send_message(
                chat_id=settings.GROUP_CHAT_ID,
                text=(
                    f"💧 <b>Suv ta'minoti yangilandi!</b>\n\n"
                    f"<b>{user.full_name}</b> 19L toza suv keltirdi. Rahmat!\n"
                    f"Keyingi navbat: 🏢 <b>{n_room}-Xona</b> ({n_user_str})."
                ),
            )
        except Exception:
            pass
