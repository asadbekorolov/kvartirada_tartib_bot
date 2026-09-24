import re
from aiogram import Router
from aiogram.filters import Command
from aiogram.types import Message
from sqlalchemy import select

from config import settings
from database.models import User
from database.session import get_session
from services.duty_service import get_active_users

router = Router(name="guest_router")


@router.message(Command("mehmon"))
async def handle_guest_command(message: Message):
    """
    Handle /mehmon command to notify flatmates in advance.
    Format: /mehmon [kelish vaqti] [odam soni] [izoh]
    Example: /mehmon 19:00 2 ta kursdoshim
    """
    user_id = message.from_user.id
    raw_text = message.text.strip()
    content = re.sub(r"^/mehmon(@\w+)?", "", raw_text, flags=re.IGNORECASE).strip()

    if not content:
        await message.answer(
            "👥 <b>Mehmon Kelishi Haqida Ogohlantirish Tizimi</b>\n\n"
            "Kvartira qoidasi bo'yicha: <i>Mehmon kelishidan kamida 3–4 soat oldin xabardor qilish shart.</i>\n\n"
            "<b>Buyruq formati:</b>\n"
            "<code>/mehmon [kelish vaqti] [odam soni] [izoh]</code>\n\n"
            "<b>Misol:</b>\n"
            "• <code>/mehmon 19:00 2 ta kursdoshim</code>\n"
            "• <code>/mehmon 20:30 1 kishi ukam mehmonga keladi</code>"
        )
        return

    # Extract time and description
    parts = content.split(maxsplit=2)
    time_str = parts[0]
    count_str = parts[1] if len(parts) > 1 else "1-2"
    detail_str = parts[2] if len(parts) > 2 else ""

    async with get_session() as session:
        user_res = await session.execute(select(User).where(User.id == user_id))
        host_user = user_res.scalar_one_or_none()
        active_users = await get_active_users(session)

    host_name = host_user.full_name if host_user else message.from_user.full_name
    room_info = f"({host_user.room_number}-Xona)" if host_user else ""

    # Build roommates mention list
    mentions = []
    for u in active_users:
        if u.id != user_id:
            if u.username:
                mentions.append(f"@{u.username}")
            else:
                mentions.append(f"<a href='tg://user?id={u.id}'>{u.full_name.split()[0]}</a>")

    mentions_text = " ".join(mentions) if mentions else "Barcha xonadoshlar"
    detail_part = f"\n📝 <b>Qo'shimcha izoh:</b> {detail_str}" if detail_str else ""

    announcement = (
        f"⚠️ <b>Diqqat, xonadoshlar! Kvartiraga mehmon kelmoqda!</b>\n\n"
        f"👤 <b>Chaqiruvchi:</b> <b>{host_name}</b> {room_info}\n"
        f"⏰ <b>Kelish vaqti:</b> <b>{time_str}</b>\n"
        f"👥 <b>Mehmonlar soni:</b> <b>{count_str}</b>"
        f"{detail_part}\n\n"
        f"🧹 <b>ESLATMA:</b> Iltimos, umumiy joylar (koridor, zal, oshxona va hojatxona) "
        f"tartibiga e'tibor bering, shaxsiy buyum va idishlarni joyiga olib qo'ying!\n\n"
        f"🔔 <i>Xabardor bo'ling:</i> {mentions_text}"
    )

    # Send in current chat
    await message.answer(announcement)

    # Broadcast to group chat if command was sent in private chat
    if settings.GROUP_CHAT_ID and message.chat.id != settings.GROUP_CHAT_ID:
        try:
            await message.bot.send_message(
                chat_id=settings.GROUP_CHAT_ID,
                text=announcement,
            )
            await message.answer("✅ Umumiy guruhga ham ogohlantirish xabari yetkazildi!")
        except Exception:
            pass
