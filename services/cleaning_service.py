from datetime import date, timedelta
from typing import Dict, List, Optional, Tuple
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from database.models import CleaningChecklistState, User

# 11 ta rasmiy katta tozalash vazifalari
CLEANING_TASKS: Dict[str, str] = {
    "task_1_pilesos_xonalar": "2 ta katta xonani pilesos qilish",
    "task_2_xontaxta_artish": "Xontaxtalarni nam latta bilan tozalab artish",
    "task_3_pilesos_balkon_oshxona": "Balkon, oshxona va koridorni pilesos qilish",
    "task_4_gaz_plita_zar_qogoz": "Gaz plitadagi zar qog'ozni yangisiga almashtirish",
    "task_5_boz_yuvish": "Bo'zni yuvish va qayta to'shash",
    "task_6_hojatxona_pol_sholcha": "Hojatxona cho'tkasini chayish, polini artish, sholchasini yuvish",
    "task_7_deraza_oynalar": "Deraza tokchalarini tozalash va oynalarni artish",
    "task_8_vanna_rakovina_soda": "Vannani to'liq yuvish, rakovinani sodalab tozalash",
    "task_9_vanna_buyumlar": "Vanna xonasidagi buyumlarni tartibga keltirish",
    "task_10_oyoq_kiyim_javoni": "Koridordagi oyoq kiyim javonini to'liq tartiblash",
    "task_11_axlatlarni_tokish": "Barcha axlatlarni to'kib kelish",
}


def get_weekend_date_for(target_date: Optional[date] = None) -> date:
    """
    Berilgan sana haftasining Yakshanba kunini qaytaradi.
    Bu orqali Shanba/Yakshanba tozalash ishlari yagona week_date ostida guruhlanadi.
    """
    if target_date is None:
        target_date = date.today()
    days_to_sunday = 6 - target_date.weekday()
    return target_date + timedelta(days=days_to_sunday)


async def get_or_create_week_checklist(
    session: AsyncSession,
    week_date: Optional[date] = None,
) -> List[CleaningChecklistState]:
    """
    Belgilangan dam olish kunlari uchun 11 bandlik checklist holatini olish yoki yaratish.
    """
    if week_date is None:
        week_date = get_weekend_date_for()

    result = await session.execute(
        select(CleaningChecklistState)
        .options(selectinload(CleaningChecklistState.completed_by_user))
        .where(CleaningChecklistState.week_date == week_date)
        .order_by(CleaningChecklistState.id.asc())
    )
    existing_items = list(result.scalars().all())
    existing_keys = {item.task_key for item in existing_items}

    created_any = False
    for task_key in CLEANING_TASKS.keys():
        if task_key not in existing_keys:
            new_item = CleaningChecklistState(
                week_date=week_date,
                task_key=task_key,
                is_done=False,
                completed_by=None,
            )
            session.add(new_item)
            created_any = True

    if created_any:
        await session.commit()
        result = await session.execute(
            select(CleaningChecklistState)
            .options(selectinload(CleaningChecklistState.completed_by_user))
            .where(CleaningChecklistState.week_date == week_date)
            .order_by(CleaningChecklistState.id.asc())
        )
        existing_items = list(result.scalars().all())

    task_order = list(CLEANING_TASKS.keys())
    existing_items.sort(key=lambda item: task_order.index(item.task_key) if item.task_key in task_order else 999)
    return existing_items


async def toggle_checklist_task(
    session: AsyncSession,
    task_key: str,
    user_id: int,
    week_date: Optional[date] = None,
) -> Tuple[Optional[CleaningChecklistState], bool]:
    """
    Checklist bandi holatini almashtirish (Toggle: Bajardim / Bekor qildim).
    Bajargan xonadosh ID si qayd qilinadi.
    """
    if week_date is None:
        week_date = get_weekend_date_for()

    result = await session.execute(
        select(CleaningChecklistState)
        .options(selectinload(CleaningChecklistState.completed_by_user))
        .where(
            CleaningChecklistState.week_date == week_date,
            CleaningChecklistState.task_key == task_key,
        )
    )
    item = result.scalar_one_or_none()

    if not item:
        item = CleaningChecklistState(
            week_date=week_date,
            task_key=task_key,
            is_done=True,
            completed_by=user_id,
        )
        session.add(item)
        await session.commit()
        res2 = await session.execute(
            select(CleaningChecklistState)
            .options(selectinload(CleaningChecklistState.completed_by_user))
            .where(CleaningChecklistState.id == item.id)
        )
        item = res2.scalar_one()
        return item, True

    if item.is_done:
        item.is_done = False
        item.completed_by = None
        new_status = False
    else:
        item.is_done = True
        item.completed_by = user_id
        new_status = True

    session.add(item)
    await session.commit()

    res_refreshed = await session.execute(
        select(CleaningChecklistState)
        .options(selectinload(CleaningChecklistState.completed_by_user))
        .where(CleaningChecklistState.id == item.id)
    )
    item = res_refreshed.scalar_one()
    return item, new_status


def render_progress_bar(completed: int, total: int, length: int = 11) -> str:
    """Renders a text progress bar: [██████░░░░░] 6/11 (54%)"""
    if total <= 0:
        return "[░░░░░░░░░░░] 0% (0/0)"
    percent = completed / total
    filled_length = int(length * percent)
    bar = "█" * filled_length + "░" * (length - filled_length)
    return f"[{bar}] {int(percent * 100)}% ({completed}/{total})"
