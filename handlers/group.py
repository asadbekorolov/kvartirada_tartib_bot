import logging
from typing import Any, Awaitable, Callable, Dict, Optional
from aiogram import BaseMiddleware, Bot, F, Router
from aiogram.filters import Command
from aiogram.types import ChatMemberUpdated, Message, TelegramObject

from config import settings
from database.session import get_session
from services.duty_service import get_active_group_chat_id, set_active_group_chat_id

logger = logging.getLogger(__name__)

router = Router(name="group_router")

WELCOME_GROUP_TEXT = (
    "🎉 <b>Assalomu alaykum, xonadoshlar!</b>\n\n"
    "🏠 <b>Kvartira Tartib Boti</b> ushbu guruhga muvaffaqiyatli ulandi!\n\n"
    "Endi quyidagi barcha eslatmalar va ma'lumotlar avtomatik tarzda ushbu guruhga yuborib turiladi:\n\n"
    "☀️ <b>Har kuni 08:00 da:</b> Kunlik navbatchi, 5 ta asosiy vazifa, kir yuvish grafigi va 10L suv navbati\n"
    "⚖️ <b>Har kuni 10:00 da:</b> Kechagi vazifalar nazorati (bajarilmagan bo'lsa, xonadoshlar ovoz berishi)\n"
    "🔔 <b>Har kuni 20:00 da:</b> Kechki eslatma va qolgan vazifalar hisoboti\n"
    "🌙 <b>Har kuni 22:30 da:</b> Kechki sukunat rejimi e'loni\n"
    "🧹 <b>Shanba 09:00 da:</b> Bozorlik juftligi va 11 bandlik umumiy tozalash checklisti\n"
    "💧 <b>Jonli o'zgarishlar:</b> 10L toza suv keltirilganda, yangi a'zo ulanganda yoki bozorlik xarajati taqsimlanganda darhol guruhga bildiriladi.\n\n"
    "<i>O'z profilingizni tanlash uchun botga shaxsiy xabarda /start yuboring.</i>"
)


class GroupAutoRegisterMiddleware(BaseMiddleware):
    """
    Auto-detect and register group ID from any incoming group message
    if it hasn't been registered yet.
    """
    async def __call__(
        self,
        handler: Callable[[TelegramObject, Dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: Dict[str, Any],
    ) -> Any:
        if isinstance(event, Message) and event.chat.type in ("group", "supergroup"):
            chat_id = event.chat.id
            if settings.GROUP_CHAT_ID != chat_id:
                async with get_session() as session:
                    current_id = await get_active_group_chat_id(session)
                    if current_id != chat_id:
                        logger.info(f"GroupAutoRegister: Auto-registered group '{event.chat.title}' (ID: {chat_id})")
                        await set_active_group_chat_id(session, chat_id)
                        if not current_id:
                            bot: Optional[Bot] = data.get("bot")
                            if bot:
                                try:
                                    await bot.send_message(chat_id=chat_id, text=WELCOME_GROUP_TEXT)
                                except Exception as e:
                                    logger.error(f"GroupAutoRegister: Failed to send welcome: {e}")
        return await handler(event, data)


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


@router.message(F.new_chat_members)
async def handle_new_chat_members(message: Message, bot: Bot):
    """Handle new members joining or bot being added via member invitation."""
    bot_info = await bot.get_me()
    for member in message.new_chat_members:
        if member.id == bot_info.id:
            chat_id = message.chat.id
            logger.info(f"Bot joined group via new_chat_members '{message.chat.title}' (ID: {chat_id})")
            async with get_session() as session:
                await set_active_group_chat_id(session, chat_id)
            try:
                await bot.send_message(chat_id=chat_id, text=WELCOME_GROUP_TEXT)
            except Exception as e:
                logger.error(f"Failed to send welcome message to group {chat_id}: {e}")
            return

    # If another user joined the group
    names = ", ".join(m.first_name for m in message.new_chat_members)
    await message.reply(
        f"👋 Xush kelibsiz, <b>{names}</b>!\n\n"
        f"Kvartira tartib botimizdagi profilingizni tasdiqlash uchun botga shaxsiy xabarda <b>/start</b> yuboring."
    )


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
            f"Guruh ID: <code>{chat_id}</code>\n\n"
            f"Har kuni ertalab soat <b>08:00</b> da kunlik eslatmalar ushbu guruhga yuboriladi."
        )
    else:
        await message.reply("⚠️ Ushbu buyruqni faqat kvartira Telegram guruhida yuboring.")
