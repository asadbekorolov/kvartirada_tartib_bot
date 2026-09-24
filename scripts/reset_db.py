import asyncio
import os
import sys

# Ensure parent directory is in sys.path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))
if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8")

from database.base import Base
from database.models import RotationState, User
from database.session import engine, get_session, init_db
from config import settings

INITIAL_ROOMMATES = [
    {"full_name": "Avazbek", "room_number": 1, "order_index": 0, "assigned_day": 0},
    {"full_name": "Firdavs", "room_number": 1, "order_index": 1, "assigned_day": 1},
    {"full_name": "Asadbek bro", "room_number": 1, "order_index": 2, "assigned_day": 2},
    {"full_name": "Omadbek", "room_number": 1, "order_index": 3, "assigned_day": 3},
    {"full_name": "Ilyosbek", "room_number": 2, "order_index": 4, "assigned_day": 4},
    {"full_name": "Jaloliddin", "room_number": 2, "order_index": 5, "assigned_day": 5},
    {"full_name": "Asadbek", "room_number": 2, "order_index": 6, "assigned_day": 6},
    {"full_name": "Mavlonbek", "room_number": 2, "order_index": 7, "assigned_day": 7},
]


async def reset_database():
    """Drop all tables, recreate them, and seed the 8 apartment roommate profiles."""
    print("🧹 Asosiy ma'lumotlar bazasini tozalash boshlandi...")
    async with engine.begin() as conn:
        print("  - Barcha mavjud jadvallarni o'chirish (drop_all)...")
        await conn.run_sync(Base.metadata.drop_all)

    print("  - Jadvallarni qaytadan yaratish (init_db)...")
    await init_db()

    print("  - 8 nafar xonadon a'zosi profillarini kiritish (seeding)...")
    async with get_session() as session:
        for idx, m in enumerate(INITIAL_ROOMMATES, start=1):
            user = User(
                id=idx,
                telegram_id=None,
                username=None,
                full_name=m["full_name"],
                room_number=m["room_number"],
                order_index=m["order_index"],
                assigned_day=m["assigned_day"],
                is_active=True,
            )
            session.add(user)

        # Initialize rotation state anchor
        state = RotationState(
            anchor_date=settings.parsed_base_date,
            anchor_slot=0,
        )
        session.add(state)
        await session.commit()

    await engine.dispose()
    print("✅ Ma'lumotlar bazasi (kvartira.db) muvaffaqiyatli tayyorlandi!")
    print(f"   8 ta profil kiritildi (barchasining telegram_id = None bo'sh holatda):")
    for m in INITIAL_ROOMMATES:
        print(f"   • {m['full_name']} (Xona {m['room_number']})")


if __name__ == "__main__":
    if sys.platform == "win32":
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
    asyncio.run(reset_database())
