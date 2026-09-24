import logging
from aiogram import Bot, F, Router
from aiogram.filters import Command
from aiogram.types import ChatMemberUpdated, Message

from config import settings
from database.session import get_session
from services.duty_service import set_active_group_chat_id

logger = logging.getLogger(__name__)

router = Router(name="group_router")

WELCOME_GROUP_TEXT = (
    "🎉 <b>Assalomu alaykum, xonadoshlar!</b>\n\n"
    "🏠 <b>Kvartira Tartib Boti</b> ushbu guruhga muvaffaqiyatli ulandi!\n\n"
    "Endi quyidagi barcha eslatmalar va ma'lumotlar avtomatik tarzda ushbu guruhga yuborib turiladi:\n\n"
    "☀️ <b>Har kuni 08:00 da:</b> Kunlik navbatchi, 5 ta asosiy vazifa va kir yuvish grafigi\n"
    "⚖️ <b>Har kuni 10:00 da:</b> Kechagi vazifalar nazorati (bajarilmagan bo'lsa, xonadoshlar ovoz berishi)\n"
    "🔔 <b>Har kuni 20:00 da:</b> Kechki eslatma va qolgan vazifalar hisoboti\n"
    "🌙 <b>Har kuni 22:30 da:</b> Kechki sukunat rejimi e'loni\n"
    "🧹 <b>Shanba 09:00 da:</b> Bozorlik juftligi va 11 bandlik umumiy tozalash checklisti\n"
    "💧 <b>Jonli o'zgarishlar:</b> 10L toza suv keltirilganda, yangi a'zo ulanganda yoki bozorlik xarajati taqsimlanganda darhol guruhga bildiriladi.\n\n"
    "<i>O'z profilingizni tanlash uchun botga shaxsiy xabarda /start yuboring.</i>"
)


@router.my_chat_member()
async def handle_bot_added_to_group(event: ChatMemberUpdated, bot: Bot):
    """Triggered when bot is added to a group or promoted to admin."""
    if event.chat.type in ("group", "supergroup"):
        if event.new_chat_member.status in ("member", "administrator"):
            chat_id = event.chat.id
            logger.info(f"Bot added to group '{event.chat.title}' (ID: {chat_id})")

            async with get_session() as session:
                await set_active_group_chat_id(session, chat_id)

            try:
                await bot.send_message(chat_id=chat_id, text=WELCOME_GROUP_TEXT)
            except Exception as e:
                logger.error(f"Failed to send welcome message to group {chat_id}: {e}")


@router.message(Command("setgroup"))
async def handle_set_group_command(message: Message):
    """Explicitly set current group as official notification chat."""
    if message.chat.type in ("group", "supergroup"):
        chat_id = message.chat.id
        async with get_session() as session:
            await set_active_group_chat_id(session, chat_id)

        await message.reply(
            f"✅ <b>Guruh muvaffaqiyatli bog'landi!</b>\n\n"
            f"Ushbu guruh (<b>{message.chat.title}</b>) barcha kunlik navbatchilik, kir, suv va tozalash "
            f"eslatmalari yuboriladigan rasmiy guruh sifatida saqlandi.\n"
            f"Guruh ID: <code>{chat_id}</code>"
        )
    else:
        await message.reply("⚠️ Ushbu buyruqni faqat kvartira Telegram guruhida yuboring.")
