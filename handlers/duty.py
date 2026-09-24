from datetime import date, timedelta
from aiogram import F, Router
from aiogram.filters import Command
from aiogram.types import CallbackQuery, Message

from config import settings
from database.models import DutyStatus
from database.session import get_session
from keyboards.inline import (
    DAILY_5_TASKS,
    get_daily_tasks_keyboard,
    get_water_complete_keyboard,
)
from services.duty_service import (
    complete_water_duty,
    get_duty_for_date,
    get_laundry_duty_for_date,
    get_or_create_daily_tasks,
    get_water_duty_schedule,
    get_weekly_schedule,
    get_weekend_grocery_duty,
    toggle_daily_task,
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


def render_duty_text(
    duty_date: date,
    user,
    record,
    laundry_user,
    tasks,
) -> str:
    day_name = UZ_DAYS[duty_date.weekday()]
    done_count = sum(1 for t in tasks if t.is_done)
    all_done = (done_count == len(DAILY_5_TASKS))

    if all_done:
        status_str = "✅ <b>Barcha vazifalar to'liq bajarildi (5/5)</b>"
    elif record and record.status == DutyStatus.FINED:
        status_str = "❌ <b>Bajarilmadi (Jarima qo'llangan)</b>"
    elif record and record.status == DutyStatus.SWAPPED:
        status_str = "🔄 <b>O'zaro almashtirilgan</b>"
    else:
        status_str = f"⏳ <b>Bajarilishi kutilmoqda ({done_count}/5 bajarildi)</b>"

    user_name = user.full_name if user else "Belgilanmagan"
    room_info = f"{user.room_number}-Xona" if user else "—"

    laundry_text = (
        f"🧺 <b>Bugungi kir yuvish huquqi:</b> <b>{laundry_user.full_name}</b> ({laundry_user.room_number}-Xona)"
        if laundry_user
        else "🧺 <i>Kir yuvish navbatchisi topilmadi</i>"
    )

    if all_done:
        return (
            f"🎉 <b>Bugungi barcha kunlik vazifalar to'liq bajarildi!</b>\n\n"
            f"📅 Sana: <b>{duty_date.strftime('%d.%m.%Y')} ({day_name})</b>\n"
            f"🧹 Navbatchi: <b>{user_name}</b> (🏢 {room_info})\n"
            f"📌 Holat: {status_str}\n\n"
            f"{laundry_text}\n\n"
            f"Kvartirada tozalik va ozodalikni ta'minlaganingiz uchun tashakkur, <b>{user_name}</b>! ✨"
        )

    return (
        f"📋 <b>Bugungi Kunlik Navbatchilik Checklisti:</b>\n\n"
        f"📅 Sana: <b>{duty_date.strftime('%d.%m.%Y')} ({day_name})</b>\n"
        f"🧹 Navbatchi: <b>{user_name}</b> (🏢 {room_info})\n"
        f"📌 Holat: {status_str}\n\n"
        f"{laundry_text}\n\n"
        f"<b>Kunlik 5 ta asosiy vazifa:</b>\n"
        f"1. 🍲 Kechki taom / ovqat\n"
        f"2. 🍞 Non olib kelish\n"
        f"3. 🧽 Xontaxta va stollarni artish\n"
        f"4. 🍳 Qozon va umumiy idishlar\n"
        f"5. 🗑 Oshxona va hojatxona axlati\n\n"
        f"<i>Vazifalarni bajarganingiz sari quyidagi tugmalarni bosib tasdiqlang:</i>"
    )


@router.message(F.text == "📋 Bugun")
@router.message(Command("bugun"))
async def handle_today_duty(message: Message):
    """Show today's daily duty holder, 5 checklist tasks, and laundry slot holder."""
    today = date.today()

    async with get_session() as session:
        user, record = await get_duty_for_date(session, today)
        laundry_user = await get_laundry_duty_for_date(session, today)
        tasks = await get_or_create_daily_tasks(session, today)

    if not user:
        await message.answer(
            "⚠️ Kvartirada faol a'zolar mavjud emas.\n"
            "Avval /start orqali xonadoshlarni ro'yxatdan o'tkazing."
        )
        return

    text = render_duty_text(today, user, record, laundry_user, tasks)
    keyboard = get_daily_tasks_keyboard(tasks, today)
    await message.answer(text, reply_markup=keyboard)


@router.callback_query(F.data.startswith("dtask_tog:"))
async def process_toggle_daily_task(callback: CallbackQuery):
    """Toggle one of the 5 daily checklist tasks."""
    parts = callback.data.split(":")
    task_key = parts[1]
    duty_date = date.fromisoformat(parts[2])

    async with get_session() as session:
        task_item, new_status, is_all_completed, completed_count = await toggle_daily_task(
            session=session,
            duty_date=duty_date,
            task_key=task_key,
            user_id=callback.from_user.id,
        )
        tasks = await get_or_create_daily_tasks(session, duty_date)
        user, record = await get_duty_for_date(session, duty_date)
        laundry_user = await get_laundry_duty_for_date(session, duty_date)

    task_title = DAILY_5_TASKS.get(task_key, task_key)
    stat_msg = "✅ Bajarildi" if new_status else "❌ Bajarilmadi"

    if is_all_completed:
        user_name = user.full_name if user else callback.from_user.full_name
        await callback.answer("🎉 Barcha 5 ta vazifa to'liq bajarildi!", show_alert=True)
        text = render_duty_text(duty_date, user, record, laundry_user, tasks)
        kb = get_daily_tasks_keyboard(tasks, duty_date)
        try:
            await callback.message.edit_text(text, reply_markup=kb)
        except Exception:
            pass

        if settings.GROUP_CHAT_ID:
            try:
                await callback.bot.send_message(
                    chat_id=settings.GROUP_CHAT_ID,
                    text=(
                        f"🎉 <b>Bugungi barcha kunlik vazifalar to'liq bajarildi!</b>\n\n"
                        f"Kvartirada tozalik va ozodalikni ta'minlaganingiz uchun tashakkur, <b>{user_name}</b>! ✨"
                    ),
                )
            except Exception:
                pass
    else:
        await callback.answer(f"{task_title}: {stat_msg} ({completed_count}/5)")
        text = render_duty_text(duty_date, user, record, laundry_user, tasks)
        kb = get_daily_tasks_keyboard(tasks, duty_date)
        try:
            await callback.message.edit_text(text, reply_markup=kb)
        except Exception:
            pass


@router.callback_query(F.data.startswith("dtask_ref:"))
async def process_refresh_daily_tasks(callback: CallbackQuery):
    """Refresh daily tasks checklist."""
    parts = callback.data.split(":")
    duty_date = date.fromisoformat(parts[1])

    async with get_session() as session:
        user, record = await get_duty_for_date(session, duty_date)
        laundry_user = await get_laundry_duty_for_date(session, duty_date)
        tasks = await get_or_create_daily_tasks(session, duty_date)

    text = render_duty_text(duty_date, user, record, laundry_user, tasks)
    kb = get_daily_tasks_keyboard(tasks, duty_date)
    await callback.answer("🔄 Vazifalar holati yangilandi")
    try:
        await callback.message.edit_text(text, reply_markup=kb)
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
