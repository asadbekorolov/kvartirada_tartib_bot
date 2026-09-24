import logging
from datetime import date, timedelta
from aiogram import Bot
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger

from config import settings
from database.models import DutyStatus
from database.session import get_session
from keyboards.inline import get_checklist_inline_keyboard
from services.cleaning_service import (
    get_or_create_week_checklist,
    get_weekend_date_for,
    render_progress_bar,
)
from services.duty_service import (
    apply_missed_duty_fine,
    get_duty_for_date,
    get_laundry_duty_for_date,
    get_weekend_grocery_duty,
)

logger = logging.getLogger(__name__)


async def send_morning_reminder(bot: Bot) -> None:
    """
    08:00 Tonggi start xabarnomasi:
    Bugungi kunlik navbatchi, uning 5 ta asosiy vazifasi va bugungi kir yuvish kuni egasi.
    """
    today = date.today()
    async with get_session() as session:
        user, record = await get_duty_for_date(session, today)
        laundry_user = await get_laundry_duty_for_date(session, today)

        if not user:
            logger.info("Morning reminder: Faol a'zolar topilmadi.")
            return

        user_mention = f"<a href='tg://user?id={user.id}'>{user.full_name}</a>" if user.id else user.full_name
        laundry_mention = f"<b>{laundry_user.full_name}</b> ({laundry_user.room_number}-Xona)" if laundry_user else "Belgilanmagan"

        msg = (
            f"☀️ <b>Xayrli tong, xonadoshlar! (08:00 — Tonggi Start)</b>\n\n"
            f"📅 Bugungi sana: <b>{today.strftime('%d.%m.%Y')}</b>\n"
            f"🧹 <b>Bugungi kunlik navbatchi:</b> {user_mention} ({user.room_number}-Xona)\n"
            f"🧺 <b>Bugungi kir yuvish navbati:</b> {laundry_mention}\n\n"
            f"<b>Navbatchining 5 ta asosiy vazifasi:</b>\n"
            f"1️⃣ 🍲 <b>Ovqat:</b> Kechki taomni tayyorlash yoki umumiy ovqatga qarash\n"
            f"2️⃣ 🍞 <b>Non va dasturxon:</b> Dasturxon atrofini toza saqlash, nonni nazorat qilish\n"
            f"3️⃣ 🧽 <b>Xontaxta:</b> Xontaxta va oshxona stollarini nam latta bilan tozalab artish\n"
            f"4️⃣ 🍳 <b>Idishlar:</b> Umumiy idish-tovoqlar va qozonlarni yuvib qo'yish\n"
            f"5️⃣ 🗑 <b>Axlat:</b> Oshxona va hojatxona axlat chelaklarini to'plash va to'kib kelish\n\n"
            f"<i>Kun oxirida vazifalarni yakunlab, /bugun orqali '✅ Bajardim' deb belgilashni unutmang!</i>"
        )

        # Broadcast to group
        if settings.GROUP_CHAT_ID:
            try:
                await bot.send_message(chat_id=settings.GROUP_CHAT_ID, text=msg)
            except Exception as e:
                logger.error(f"Error sending morning reminder to group {settings.GROUP_CHAT_ID}: {e}")

        # Send direct DM to duty user
        try:
            await bot.send_message(chat_id=user.id, text=msg)
        except Exception as e:
            logger.warning(f"Could not send direct message to user {user.id}: {e}")


async def send_evening_reminder(bot: Bot) -> None:
    """
    20:00 Kechki ogohlantirish:
    Navbatchiga idishlarni qoldirmaslik va axlatlarni olib chiqish eslatmasi.
    """
    today = date.today()
    async with get_session() as session:
        user, record = await get_duty_for_date(session, today)
        if not user:
            return

        if record and record.status == DutyStatus.COMPLETED:
            logger.info("Evening reminder: Bugungi vazifalar allaqachon bajarilgan.")
            return

        msg = (
            f"🌙 <b>Kechki Ogohlantirish (20:00)</b>\n\n"
            f"Hurmatli <b>{user.full_name}</b>!\n"
            f"Bugungi navbatchilik vazifalarini yakunlash vaqti keldi:\n\n"
            f"⚠️ <b>Muhim eslatmalar:</b>\n"
            f"• <b>Idishlarni qoldirmang:</b> Barcha choynak, kosa, likopcha va qozonlarni yuvib qo'ying!\n"
            f"• <b>Axlatlarni olib chiqing:</b> Oshxona va hojatxona axlat paketlarini to'kib keling!\n"
            f"• <b>Xontaxtani tozalang:</b> Dasturxon atrofini tartibga keltiring!\n\n"
            f"Barcha ishlarni bajarib bo'lgach, <b>/bugun</b> buyrug'i orqali "
            f"<b>'✅ Navbatchilikni bajardim'</b> tugmasini bosing!"
        )

        if settings.GROUP_CHAT_ID:
            try:
                await bot.send_message(chat_id=settings.GROUP_CHAT_ID, text=msg)
            except Exception as e:
                logger.error(f"Error sending evening reminder to group: {e}")

        try:
            await bot.send_message(chat_id=user.id, text=msg)
        except Exception as e:
            logger.warning(f"Could not send evening reminder to user {user.id}: {e}")


async def send_night_quiet_mode_and_summary(bot: Bot) -> None:
    """
    22:30 Kechki sukunat rejimi va kunlik yakun:
    1. Soat 22:30 — Kechki sukunat vaqti talabi
    2. Navbatchilik holati tekshiruvi (jarima)
    3. Ertangi navbatchi e'loni
    """
    today = date.today()
    tomorrow = today + timedelta(days=1)

    async with get_session() as session:
        today_user, today_record = await get_duty_for_date(session, today)
        tomorrow_user, _ = await get_duty_for_date(session, tomorrow)

        if not today_user:
            return

        fine_applied = False
        if not today_record or today_record.status != DutyStatus.COMPLETED:
            fine = await apply_missed_duty_fine(session, today)
            fine_applied = fine is not None

        status_text = "✅ <b>Vazifalar to'liq bajarildi</b>"
        if fine_applied:
            status_text = (
                f"❌ <b>Vazifalar bajarilmadi!</b>\n"
                f"⚠️ <i>Jarima jamg'armasiga {settings.DAILY_FINE_AMOUNT:,} so'm jarima yozildi.</i>"
            )
        elif not today_record or today_record.status != DutyStatus.COMPLETED:
            status_text = "⏳ <b>Bajarilmadi</b>"

        tomorrow_info = (
            f"🌅 <b>Ertangi navbatchi:</b> <b>{tomorrow_user.full_name}</b> ({tomorrow_user.room_number}-Xona)"
            if tomorrow_user
            else "🌅 <i>Ertangi navbatchi belgilanmagan</i>"
        )

        msg = (
            f"🤫 <b>Soat 22:30 — Kechki sukunat vaqti boshlandi.</b>\n"
            f"<i>Xonalarda shovqin qilmaslik, telefon qo'ng'iroqlarini balkonda amalga oshirish "
            f"va videolarni faqat quloqchinda ko'rish so'raladi.</i>\n\n"
            f"━━━━━━━━━━━━━━━━━━\n"
            f"📋 <b>Kun yakuni hisoboti:</b>\n"
            f"Bugungi navbatchi: <b>{today_user.full_name}</b>\n"
            f"Holat: {status_text}\n\n"
            f"{tomorrow_info}\n"
            f"━━━━━━━━━━━━━━━━━━\n"
            f"Barchaga xayrli tun, xonadoshlar! Ertangi kunga yaxshi dam oling. 😴"
        )

        if settings.GROUP_CHAT_ID:
            try:
                await bot.send_message(chat_id=settings.GROUP_CHAT_ID, text=msg)
            except Exception as e:
                logger.error(f"Error sending night quiet mode to group: {e}")

        try:
            await bot.send_message(chat_id=today_user.id, text=msg)
        except Exception as e:
            logger.warning(f"Could not send night summary to user {today_user.id}: {e}")

        if tomorrow_user and tomorrow_user.id != today_user.id:
            try:
                t_msg = (
                    f"🔔 <b>Eslatma:</b> Ertaga (<b>{tomorrow.strftime('%d.%m.%Y')}</b>) navbatchilik sizda!\n"
                    f"5 ta asosiy vazifani bajarishga tayyor turing."
                )
                await bot.send_message(chat_id=tomorrow_user.id, text=t_msg)
            except Exception as e:
                logger.warning(f"Could not notify tomorrow user: {e}")


async def send_saturday_morning_cleaning(bot: Bot) -> None:
    """
    Shanba 09:00:
    Bozorlik qiluvchi juftlik nomi, chekni tashlash eslatmasi va
    Katta tozalash checklistini guruhga chiqarish.
    """
    today = date.today()
    weekend_sun = get_weekend_date_for(today)

    async with get_session() as session:
        shopper1, shopper2 = await get_weekend_grocery_duty(session, today)
        items = await get_or_create_week_checklist(session, weekend_sun)

    sh1_name = f"<b>{shopper1.full_name}</b> ({shopper1.room_number}-Xona)" if shopper1 else "Belgilanmagan"
    sh2_name = f"<b>{shopper2.full_name}</b> ({shopper2.room_number}-Xona)" if shopper2 else "Belgilanmagan"

    completed = sum(1 for it in items if it.is_done)
    progress_bar = render_progress_bar(completed, len(items))

    msg = (
        f"🛒 <b>Shanba 09:00 — Bozorlik va Katta Tozalash Vaqti!</b>\n\n"
        f"🛍 <b>Bozorlik qiluvchi mas'ul juftlik:</b>\n"
        f"1. {sh1_name}\n"
        f"2. {sh2_name}\n\n"
        f"🧾 <b>ESLATMA:</b> Bozorlikdan so'ng xarid chekini va jami hisob-kitobni "
        f"guruhga tashlashni unutmang!\n\n"
        f"━━━━━━━━━━━━━━━━━━\n"
        f"🧹 <b>Katta Tozalash: 11 Bandlik Checklist:</b>\n"
        f"Bajarilish ko'rsatkichi: <code>{progress_bar}</code>\n\n"
        f"<i>Kvartiradagi barcha xonadoshlar tozalashda ishtirok etishi shart. "
        f"Quyidagi tugmalar orqali bajargan vazifalaringizni belgilang:</i>"
    )

    keyboard = get_checklist_inline_keyboard(items, weekend_sun)

    if settings.GROUP_CHAT_ID:
        try:
            await bot.send_message(
                chat_id=settings.GROUP_CHAT_ID,
                text=msg,
                reply_markup=keyboard,
            )
        except Exception as e:
            logger.error(f"Error sending Saturday cleaning reminder to group: {e}")


def setup_scheduler(bot: Bot) -> AsyncIOScheduler:
    """Setup and configure APScheduler with exact cron jobs."""
    scheduler = AsyncIOScheduler(timezone=settings.TIMEZONE)

    # 1. 08:00 AM Daily Morning Start
    scheduler.add_job(
        send_morning_reminder,
        trigger=CronTrigger(hour=8, minute=0),
        args=[bot],
        id="morning_start",
        name="08:00 Tonggi start xabarnomasi",
        replace_existing=True,
    )

    # 2. 20:00 PM Daily Evening Warning
    scheduler.add_job(
        send_evening_reminder,
        trigger=CronTrigger(hour=20, minute=0),
        args=[bot],
        id="evening_warning",
        name="20:00 Kechki ogohlantirish",
        replace_existing=True,
    )

    # 3. 22:30 PM Daily Quiet Mode & Summary
    scheduler.add_job(
        send_night_quiet_mode_and_summary,
        trigger=CronTrigger(hour=22, minute=30),
        args=[bot],
        id="night_quiet_mode",
        name="22:30 Kechki sukunat rejimi va hisobot",
        replace_existing=True,
    )

    # 4. Saturday 09:00 AM Grocery Shopping & Deep Cleaning Checklist
    scheduler.add_job(
        send_saturday_morning_cleaning,
        trigger=CronTrigger(day_of_week="sat", hour=9, minute=0),
        args=[bot],
        id="saturday_cleaning",
        name="Shanba 09:00 bozorlik va 11 bandlik tozalash checklisti",
        replace_existing=True,
    )

    return scheduler
