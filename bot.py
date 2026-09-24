import asyncio
import logging
import sys
from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.types import BotCommand

from config import settings
from database.session import get_session, init_db
from handlers import (
    cleaning_router,
    duty_router,
    expense_router,
    fund_router,
    guest_router,
    rules_router,
    start_router,
    swap_router,
    group_router,
)
from handlers.group import GroupAutoRegisterMiddleware
from services.duty_service import get_active_group_chat_id
from services.scheduler import setup_scheduler

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - [%(levelname)s] - %(name)s - %(message)s",
    handlers=[
        logging.StreamHandler(sys.stdout),
    ],
)
logger = logging.getLogger("kvartira_bot")


async def set_default_bot_commands(bot: Bot) -> None:
    """Register all bot commands visible in Telegram chat menu."""
    commands = [
        BotCommand(command="start", description="Boshlash / Ro'yxatdan o'tish"),
        BotCommand(command="bugun", description="Bugungi navbatchi va vazifalar"),
        BotCommand(command="ertaga", description="Ertangi navbatchi va kir grafigi"),
        BotCommand(command="haftalik", description="7 kunlik to'liq jadval"),
        BotCommand(command="tozalash", description="11 bandlik tozalash checklisti"),
        BotCommand(command="bozorlik", description="Bozorlik hisob-kitobi (Split-Bill)"),
        BotCommand(command="mehmon", description="Mehmon kelishini e'lon qilish"),
        BotCommand(command="suv", description="10L ichimlik suvi navbati"),
        BotCommand(command="fond", description="Jarima jamg'armasi va balansi"),
        BotCommand(command="qoidalar", description="Kvartiraning 6 ta asosiy qoidasi"),
        BotCommand(command="almashtirish", description="Navbatchilikni almashtirish"),
        BotCommand(command="azolar", description="Xonadoshlar ro'yxati va slotlar"),
        BotCommand(command="profil", description="Shaxsiy slot va hisob"),
        BotCommand(command="kun", description="Navbatchilik kunini tanlash / o'zgartirish"),
        BotCommand(command="leave", description="Navbatchilikdan chiqish (dam olish / safar)"),
    ]
    try:
        await bot.set_my_commands(commands)
        logger.info("Bot commands set successfully.")
    except Exception as e:
        logger.warning(f"Could not set bot commands: {e}")


async def main() -> None:
    """Bot startup and main lifecycle entrypoint."""
    logger.info("Initializing database...")
    await init_db()
    logger.info("Database initialized successfully.")

    # Load active group chat id from DB if previously registered
    async with get_session() as session:
        active_group_id = await get_active_group_chat_id(session)
        if active_group_id:
            logger.info(f"Active group chat ID loaded: {active_group_id}")

    bot = Bot(
        token=settings.BOT_TOKEN,
        default=DefaultBotProperties(parse_mode=ParseMode.HTML),
    )
    dp = Dispatcher(storage=MemoryStorage())

    # Register auto-registration middleware for groups
    dp.message.outer_middleware(GroupAutoRegisterMiddleware())

    # Include all handler routers
    dp.include_router(start_router)
    dp.include_router(duty_router)
    dp.include_router(cleaning_router)
    dp.include_router(swap_router)
    dp.include_router(expense_router)
    dp.include_router(guest_router)
    dp.include_router(fund_router)
    dp.include_router(rules_router)
    dp.include_router(group_router)

    # Initialize scheduler
    scheduler = setup_scheduler(bot)
    scheduler.start()
    logger.info("APScheduler initialized and started.")

    await set_default_bot_commands(bot)

    logger.info(f"Starting bot polling for '{settings.APARTMENT_NAME}'...")
    try:
        # Delete webhook to prevent conflicts with polling
        await bot.delete_webhook(drop_pending_updates=True)
        await dp.start_polling(bot)
    except (KeyboardInterrupt, SystemExit):
        logger.info("Bot polling stopped by user signal.")
    except Exception as e:
        logger.error(f"Polling loop terminated with error: {e}", exc_info=True)
    finally:
        logger.info("Shutting down bot and scheduler...")
        scheduler.shutdown(wait=False)
        await bot.session.close()
        logger.info("Bot stopped cleanly.")


if __name__ == "__main__":
    if sys.platform == "win32":
        # Required for aiosqlite / proactor event loop compatibility on Windows
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
    try:
        asyncio.run(main())
    except (KeyboardInterrupt, SystemExit):
        logger.info("Application exited.")
