import logging
from datetime import date, timedelta
from aiogram import Bot
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger

from sqlalchemy import select

from config import settings
from database.models import DutyStatus, PenaltyFund
from database.session import get_session
from keyboards.inline import (
    get_checklist_inline_keyboard,
    get_daily_tasks_keyboard,
    get_vote_keyboard,
)
from services.cleaning_service import (
    get_or_create_week_checklist,
    get_weekend_date_for,
    render_progress_bar,
)
from services.duty_service import (
    are_all_daily_tasks_done,
    get_active_group_chat_id,
    get_duty_for_date,
    get_duty_votes_count,
    get_laundry_duty_for_date,
    get_or_create_daily_tasks,
    get_water_duty_schedule,
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
        tasks = await get_or_create_daily_tasks(session, today)
        water_sched = await get_water_duty_schedule(session)

        if not user:
            logger.info("Morning reminder: Faol a'zolar topilmadi.")
            return

        tg_id = user.telegram_id
        user_mention = f"<a href='tg://user?id={tg_id}'>{user.full_name}</a>" if tg_id else f"<b>{user.full_name}</b>"
        laundry_mention = f"<b>{laundry_user.full_name}</b> ({laundry_user.room_number}-Xona)" if laundry_user else "Belgilanmagan"
        water_room = water_sched.get("current_room", 1)
        water_user = water_sched.get("current_user")
        water_user_str = f" ({water_user.full_name})" if water_user else ""

        msg = (
            f"☀️ <b>Xayrli tong, xonadoshlar! (08:00 — Tonggi Start)</b>\n\n"
            f"📅 Bugungi sana: <b>{today.strftime('%d.%m.%Y')}</b>\n"
            f"🧹 <b>Bugungi kunlik navbatchi:</b> {user_mention} ({user.room_number}-Xona)\n"
            f"🧺 <b>Bugungi kir yuvish navbati:</b> {laundry_mention}\n"
            f"💧 <b>Ichimlik suvi (10L) navbati:</b> 🏢 <b>{water_room}-Xona</b>{water_user_str}\n\n"
            f"<b>Navbatchining 5 ta asosiy vazifasi:</b>\n"
            f"1️⃣ 🍲 <b>Ovqat:</b> Kechki taomni tayyorlash yoki umumiy ovqatga qarash\n"
            f"2️⃣ 🍞 <b>Non va dasturxon:</b> Dasturxon atrofini toza saqlash, nonni nazorat qilish\n"
            f"3️⃣ 🧽 <b>Xontaxta:</b> Xontaxta va oshxona stollarini nam latta bilan tozalab artish\n"
            f"4️⃣ 🍳 <b>Idishlar:</b> Umumiy idish-tovoqlar va qozonlarni yuvib qo'yish\n"
            f"5️⃣ 🗑 <b>Axlat:</b> Oshxona va hojatxona axlat chelaklarini to'plash va to'kib kelish\n\n"
            f"<i>Vazifalarni bajarganingiz sari pastdagi tugmalar orqali belgilang:</i>"
        )
        keyboard = get_daily_tasks_keyboard(tasks, today)

        # Broadcast to group
        group_id = await get_active_group_chat_id(session)
        if group_id:
            try:
                await bot.send_message(chat_id=group_id, text=msg, reply_markup=keyboard)
            except Exception as e:
                logger.error(f"Error sending morning reminder to group {group_id}: {e}")

        # Send direct DM to duty user if Telegram account is linked
        if tg_id:
            try:
                await bot.send_message(chat_id=tg_id, text=msg, reply_markup=keyboard)
            except Exception as e:
                logger.warning(f"Could not send direct message to user {tg_id}: {e}")


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

        group_id = await get_active_group_chat_id(session)
        if group_id:
            try:
                await bot.send_message(chat_id=group_id, text=msg)
            except Exception as e:
                logger.error(f"Error sending evening reminder to group {group_id}: {e}")

        tg_id = user.telegram_id
        if tg_id:
            try:
                await bot.send_message(chat_id=tg_id, text=msg)
            except Exception as e:
                logger.warning(f"Could not send evening reminder to user {tg_id}: {e}")


async def send_night_quiet_mode_and_summary(bot: Bot) -> None:
    """
    22:30 Kechki sukunat rejimi va kunlik yakun:
    1. Soat 22:30 — Kechki sukunat vaqti talabi
    2. Navbatchiga ertaga 10:00 gacha muddat borligi eslatmasi (Avtomatik jarima olib tashlangan)
    3. Ertangi navbatchi e'loni
    """
    today = date.today()
    tomorrow = today + timedelta(days=1)

    async with get_session() as session:
        today_user, today_record = await get_duty_for_date(session, today)
        tomorrow_user, _ = await get_duty_for_date(session, tomorrow)
        tasks = await get_or_create_daily_tasks(session, today)

        if not today_user:
            return

        done_count = sum(1 for t in tasks if t.is_done)
        all_done = (done_count == len(tasks)) and len(tasks) > 0

        if all_done:
            status_text = "✅ <b>Vazifalar to'liq bajarildi (5/5)</b>"
        else:
            status_text = (
                f"⏳ <b>Vazifalar jarayonda ({done_count}/5 bajarildi)</b>\n"
                f"💡 <i>Eslatma: Agar vazifalarni to'liq yakunlashga ulgurmagan bo'lsangiz, ertaga soat 10:00 gacha vaqtingiz bor.</i>"
            )

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

        group_id = await get_active_group_chat_id(session)
        if group_id:
            try:
                await bot.send_message(chat_id=group_id, text=msg)
            except Exception as e:
                logger.error(f"Error sending night quiet mode to group {group_id}: {e}")

        today_tg_id = today_user.telegram_id
        tomorrow_tg_id = tomorrow_user.telegram_id if tomorrow_user else None

        if today_tg_id:
            try:
                await bot.send_message(chat_id=today_tg_id, text=msg)
            except Exception as e:
                logger.warning(f"Could not send night summary to user {today_tg_id}: {e}")

            if not all_done:
                try:
                    reminder_dm = (
                        f"🌙 <b>Eslatma, {today_user.full_name}:</b>\n\n"
                        f"Bugungi navbatchilik vazifalarini to'liq yakunlashga ulgurmagan bo'lsangiz, "
                        f"<b>ertaga soat 10:00 gacha</b> vaqtingiz bor.\n"
                        f"Ertaga soat 10:00 da yakunlanmagan vazifalar xonadoshlar ovoziga qo'yiladi."
                    )
                    await bot.send_message(chat_id=today_tg_id, text=reminder_dm)
                except Exception as e:
                    logger.warning(f"Could not send grace period reminder to {today_tg_id}: {e}")

        if tomorrow_tg_id and tomorrow_tg_id != today_tg_id:
            try:
                t_msg = (
                    f"🔔 <b>Eslatma:</b> Ertaga (<b>{tomorrow.strftime('%d.%m.%Y')}</b>) navbatchilik sizda!\n"
                    f"5 ta asosiy vazifani bajarishga tayyor turing."
                )
                await bot.send_message(chat_id=tomorrow_tg_id, text=t_msg)
            except Exception as e:
                logger.warning(f"Could not notify tomorrow user: {e}")


async def check_morning_10am_duty_status(bot: Bot) -> None:
    """
    10:00 AM Grace Period tekshiruvi:
    Kechagi kunning 5 ta vazifasini tekshiradi:
    1. Agar 5 ta vazifa to'liq [✅] bo'lgan bo'lsa: Muvaffaqiyatli yopiladi.
    2. Agar 1 yoki undan ko'p vazifa [❌] qolgan bo'lsa:
       Guruhga ovoz berish (Poll) so'rovini chiqaradi:
       "⚠️ Kechagi navbatchi {Navbatchi Ismi} soat 10:00 gacha barcha vazifalarni yakunlamadi.
       Qolgan xonadoshlar, jarimaga tortilsinmi yoki kechirilsinmi?"
    """
    yesterday = date.today() - timedelta(days=1)

    async with get_session() as session:
        user, record = await get_duty_for_date(session, yesterday)
        if not user:
            return

        all_done = await are_all_daily_tasks_done(session, yesterday)
        if all_done:
            logger.info(f"10:00 Check: Kechagi ({yesterday}) vazifalar to'liq bajarilgan.")
            return

        # Check if already fine was recorded or concluded
        fine_count, forgive_count = await get_duty_votes_count(session, yesterday, "INCOMPLETE")
        existing_fine = await session.execute(
            select(PenaltyFund).where(
                PenaltyFund.user_id == user.id,
                PenaltyFund.reason.like(f"%INCOMPLETE%{yesterday}%"),
            )
        )
        if existing_fine.scalar_one_or_none():
            return

        poll_text = (
            f"⚠️ <b>Navbatchilik Vazifalari Bo'yicha Ovoz Berish (10:00 Yakun)</b>\n\n"
            f"Kechagi navbatchi <b>{user.full_name}</b> (🏢 {user.room_number}-Xona) "
            f"soat 10:00 gacha barcha vazifalarni to'liq yakunlamadi.\n\n"
            f"Qolgan xonadoshlar, jarimaga tortilsinmi yoki kechirilsinmi?\n\n"
            f"<i>(Ko'pchilik ovozi bilan {settings.DAILY_FINE_AMOUNT:,} so'm jarima yoziladi yoki kechiriladi)</i>"
        )
        keyboard = get_vote_keyboard(
            yesterday,
            user.id,
            reason="INCOMPLETE",
            fine_count=fine_count,
            forgive_count=forgive_count,
        )

        group_id = await get_active_group_chat_id(session)
        if group_id:
            try:
                await bot.send_message(
                    chat_id=group_id,
                    text=poll_text,
                    reply_markup=keyboard,
                )
            except Exception as e:
                logger.error(f"Error sending 10:00 voting poll to group {group_id}: {e}")


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
        group_id = await get_active_group_chat_id(session)

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

    if group_id:
        try:
            await bot.send_message(
                chat_id=group_id,
                text=msg,
                reply_markup=keyboard,
            )
        except Exception as e:
            logger.error(f"Error sending Saturday cleaning reminder to group {group_id}: {e}")


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

    # 2. 10:00 AM Daily Grace Period Check & Voting Poll
    scheduler.add_job(
        check_morning_10am_duty_status,
        trigger=CronTrigger(hour=10, minute=0),
        args=[bot],
        id="morning_10am_duty_check",
        name="10:00 Kunlik vazifalar yakuni va ovoz berish",
        replace_existing=True,
    )

    # 3. 20:00 PM Daily Evening Warning
    scheduler.add_job(
        send_evening_reminder,
        trigger=CronTrigger(hour=20, minute=0),
        args=[bot],
        id="evening_warning",
        name="20:00 Kechki ogohlantirish",
        replace_existing=True,
    )

    # 4. 22:30 PM Daily Quiet Mode & Summary (No auto-fine; 10:00 AM grace period notice)
    scheduler.add_job(
        send_night_quiet_mode_and_summary,
        trigger=CronTrigger(hour=22, minute=30),
        args=[bot],
        id="night_quiet_mode",
        name="22:30 Kechki sukunat rejimi va hisobot",
        replace_existing=True,
    )

    # 5. Saturday 09:00 AM Grocery Shopping & Deep Cleaning Checklist
    scheduler.add_job(
        send_saturday_morning_cleaning,
        trigger=CronTrigger(day_of_week="sat", hour=9, minute=0),
        args=[bot],
        id="saturday_cleaning",
        name="Shanba 09:00 bozorlik va 11 bandlik tozalash checklisti",
        replace_existing=True,
    )

    return scheduler
