import asyncio
import os
import sys

# Ensure parent directory is in sys.path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))
if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8")

from database.base import Base
from database.session import engine, init_db


async def reset_database():
    """Drop all tables and recreate them cleanly in the primary database."""
    print("🧹 Asosiy ma'lumotlar bazasini tozalash boshlandi...")
    async with engine.begin() as conn:
        print("  - Barcha mavjud jadvallarni o'chirish (drop_all)...")
        await conn.run_sync(Base.metadata.drop_all)

    print("  - Jadvallarni qaytadan yaratish (init_db)...")
    await init_db()
    await engine.dispose()
    print("✅ Ma'lumotlar bazasi (kvartira.db) to'liq tozalandi va yangi holatga keltirildi!")
    print("   Endi barcha kunlar bo'sh va soxta test foydalanuvchilar mavjud emas.")


if __name__ == "__main__":
    if sys.platform == "win32":
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
    asyncio.run(reset_database())
