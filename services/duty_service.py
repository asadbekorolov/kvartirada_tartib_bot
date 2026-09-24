from datetime import date, timedelta
from typing import Dict, List, Optional, Tuple
from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from config import settings
from database.models import (
    DutyHistory,
    DutyStatus,
    DutyType,
    PenaltyFund,
    RotationState,
    User,
)


async def get_active_users(session: AsyncSession) -> List[User]:
    """Return all active users ordered by their order_index."""
    result = await session.execute(
        select(User)
        .where(User.is_active.is_(True))
        .order_by(User.order_index.asc(), User.id.asc())
    )
    return list(result.scalars().all())


async def get_or_create_rotation_state(session: AsyncSession) -> RotationState:
    """
    Get the current rotation anchor checkpoint or initialize it if absent.
    Ensures mathematical continuity when active user count changes.
    """
    result = await session.execute(select(RotationState).order_by(RotationState.id.asc()))
    state = result.scalar_one_or_none()
    if state is None:
        state = RotationState(
            anchor_date=settings.parsed_base_date,
            anchor_slot=0,
        )
        session.add(state)
        await session.commit()
    return state


def calculate_rotation_index(
    target_date: date,
    total_users: int,
    anchor_date: date,
    anchor_slot: int,
) -> int:
    """
    Dinamik xavfsiz rotatsiya indeksi.
    Anchor sana va anchor slotdan hisoblab, a'zolar soni o'zgarganda
    navbat sakrab ketishining oldini oladi.
    Formula: (anchor_slot + (target_date - anchor_date).days) % total_users
    """
    if total_users <= 0:
        return 0
    delta_days = (target_date - anchor_date).days
    return (anchor_slot + delta_days) % total_users


async def rebalance_users(
    session: AsyncSession,
    reference_user_for_anchor: Optional[User] = None,
) -> List[User]:
    """
    Rebalance the queue for all active users so order_index is contiguous from 0 to N-1.
    Updates RotationState anchor to date.today() to prevent queue jumps.
    """
    today = date.today()
    users = await get_active_users(session)
    n = len(users)

    for idx, user in enumerate(users):
        if user.order_index != idx:
            user.order_index = idx
            session.add(user)
    await session.commit()

    if n > 0:
        rot_state = await get_or_create_rotation_state(session)
        # Determine anchor slot for today
        if reference_user_for_anchor and reference_user_for_anchor.is_active:
            new_anchor_slot = reference_user_for_anchor.order_index
        else:
            # If no reference or user left, keep slot within range
            new_anchor_slot = min(rot_state.anchor_slot, n - 1)

        rot_state.anchor_date = today
        rot_state.anchor_slot = new_anchor_slot
        session.add(rot_state)
        await session.commit()

    return users


async def register_or_join(
    session: AsyncSession,
    user_id: int,
    full_name: str,
    room_number: int,
    username: Optional[str] = None,
) -> Tuple[User, bool]:
    """
    Yangi foydalanuvchini slotga qo'shish yoki avval chiqqan foydalanuvchini qayta faollashtirish.
    Yangi a'zo navbatning oxirgi slotiga joylashtiriladi va tartib qayta muvozanatlanadi.
    """
    result = await session.execute(select(User).where(User.id == user_id))
    user = result.scalar_one_or_none()

    today = date.today()
    duty_user_today, _ = await get_duty_for_date(session, today)

    if user is None:
        active_users = await get_active_users(session)
        new_index = len(active_users)
        user = User(
            id=user_id,
            username=username,
            full_name=full_name,
            room_number=room_number,
            order_index=new_index,
            is_active=True,
        )
        session.add(user)
        await session.commit()
        await rebalance_users(session, reference_user_for_anchor=duty_user_today)
        return user, True
    else:
        user.username = username
        user.full_name = full_name
        user.room_number = room_number
        if not user.is_active:
            user.is_active = True
            active_users = await get_active_users(session)
            user.order_index = len(active_users)
        session.add(user)
        await session.commit()
        await rebalance_users(session, reference_user_for_anchor=duty_user_today)
        return user, False


add_or_update_user = register_or_join


async def leave_and_rebalance(session: AsyncSession, user_id: int) -> bool:
    """
    Foydalanuvchi kvartiradan chiqqanda uni nofaol (is_active=False) qilish va
    qolgan a'zolar navbat slotlarini uzluksiz (0 dan N-1 gacha) qayta indekslash.
    Uzluksizlikni saqlash uchun bugungi navbatchi hisobga olinadi.
    """
    result = await session.execute(select(User).where(User.id == user_id))
    user = result.scalar_one_or_none()
    if not user or not user.is_active:
        return False

    today = date.today()
    duty_user_today, _ = await get_duty_for_date(session, today)

    user.is_active = False
    session.add(user)
    await session.commit()

    ref_user = duty_user_today if (duty_user_today and duty_user_today.id != user_id) else None
    await rebalance_users(session, reference_user_for_anchor=ref_user)
    return True


deactivate_user = leave_and_rebalance


async def get_duty_for_date(
    session: AsyncSession,
    target_date: date,
) -> Tuple[Optional[User], Optional[DutyHistory]]:
    """
    Berilgan sana uchun kunlik mas'ul navbatchini dinamik hisoblab berish.
    Avval DutyHistory jadvalidan tekshiradi, keyin uzluksiz Round-Robin anchoridan hisoblaydi.
    """
    active_users = await get_active_users(session)
    if not active_users:
        return None, None

    result = await session.execute(
        select(DutyHistory)
        .where(
            DutyHistory.duty_date == target_date,
            DutyHistory.duty_type == DutyType.DAILY,
        )
    )
    duty_record = result.scalar_one_or_none()

    if duty_record:
        assigned_user = next((u for u in active_users if u.id == duty_record.user_id), None)
        if not assigned_user:
            user_result = await session.execute(select(User).where(User.id == duty_record.user_id))
            assigned_user = user_result.scalar_one_or_none()
        return assigned_user, duty_record

    rot_state = await get_or_create_rotation_state(session)
    slot_index = calculate_rotation_index(
        target_date=target_date,
        total_users=len(active_users),
        anchor_date=rot_state.anchor_date,
        anchor_slot=rot_state.anchor_slot,
    )
    assigned_user = active_users[slot_index]
    return assigned_user, None


get_daily_duty = get_duty_for_date


async def get_laundry_duty_for_date(
    session: AsyncSession,
    target_date: date,
) -> Optional[User]:
    """
    Bugungi kir yuvish mashinasidan foydalanish huquqiga ega a'zoni hisoblash.
    Kunlik navbatchi bir vaqtda kir yuvishga zo'riqmasligi uchun offset qo'llanadi.
    """
    active_users = await get_active_users(session)
    if not active_users:
        return None

    # Check if there is an explicit DutyHistory entry for LAUNDRY
    res = await session.execute(
        select(DutyHistory).where(
            DutyHistory.duty_date == target_date,
            DutyHistory.duty_type == DutyType.LAUNDRY,
        )
    )
    rec = res.scalar_one_or_none()
    if rec:
        user = next((u for u in active_users if u.id == rec.user_id), None)
        if user:
            return user

    rot_state = await get_or_create_rotation_state(session)
    duty_slot = calculate_rotation_index(
        target_date=target_date,
        total_users=len(active_users),
        anchor_date=rot_state.anchor_date,
        anchor_slot=rot_state.anchor_slot,
    )
    # Fair offset: len // 2 to separate laundry from daily kitchen chore
    laundry_slot = (duty_slot + max(1, len(active_users) // 2)) % len(active_users)
    return active_users[laundry_slot]


async def get_weekly_schedule(
    session: AsyncSession,
    start_date: Optional[date] = None,
) -> List[dict]:
    """
    Get 7-day schedule starting from start_date (defaults to current week's Monday).
    Includes both daily kitchen duty and laundry turn.
    """
    if start_date is None:
        today = date.today()
        start_date = today - timedelta(days=today.weekday())

    uz_day_names = [
        "Dushanba",
        "Seshanba",
        "Chorshanba",
        "Payshanba",
        "Juma",
        "Shanba",
        "Yakshanba",
    ]

    schedule = []
    for day_offset in range(7):
        current_date = start_date + timedelta(days=day_offset)
        assigned_user, duty_record = await get_duty_for_date(session, current_date)
        laundry_user = await get_laundry_duty_for_date(session, current_date)
        status = duty_record.status if duty_record else DutyStatus.PENDING

        schedule.append({
            "date": current_date,
            "day_name": uz_day_names[current_date.weekday()],
            "user": assigned_user,
            "laundry_user": laundry_user,
            "status": status,
            "is_weekend": current_date.weekday() >= 5,
        })

    return schedule


async def get_weekend_grocery_duty(
    session: AsyncSession,
    target_date: date,
) -> Tuple[Optional[User], Optional[User]]:
    """
    Calculate shopping pair (bozorlik juftligi) for the weekend.
    Pairs rotate cyclically based on the week number.
    """
    active_users = await get_active_users(session)
    n = len(active_users)
    if n == 0:
        return None, None
    if n == 1:
        return active_users[0], None

    rot_state = await get_or_create_rotation_state(session)
    delta_days = (target_date - rot_state.anchor_date).days
    week_number = delta_days // 7

    pair_index = (rot_state.anchor_slot + week_number * 2) % n
    first_user = active_users[pair_index]
    second_user = active_users[(pair_index + 1) % n]
    return first_user, second_user


async def get_water_duty_schedule(session: AsyncSession) -> Dict:
    """
    1-xona va 2-xona bo'yicha 2 haftalik suv olib kelish navbatini aniq hisoblash.
    - Qaysi xona navbatdaligi
    - Xona ichidagi mas'ul a'zo
    - 2 haftalik reja (joriy hafta va keyingi hafta)
    """
    active_users = await get_active_users(session)
    room1_users = [u for u in active_users if u.room_number == 1]
    room2_users = [u for u in active_users if u.room_number == 2]

    # Count completed water duties to determine alternating round
    result = await session.execute(
        select(func.count(DutyHistory.id)).where(
            DutyHistory.duty_type == DutyType.WATER,
            DutyHistory.status == DutyStatus.COMPLETED,
        )
    )
    total_completed = result.scalar_one() or 0

    # Determine current room (alternate between Room 1 and Room 2)
    # Even count -> Room 1, Odd count -> Room 2 (or based on initial priority)
    current_room = 1 if (total_completed % 2 == 0) else 2
    next_room = 2 if current_room == 1 else 1

    # Responsible member within current room
    r1_count = total_completed // 2 + (1 if total_completed % 2 == 1 and current_room == 2 else 0)
    r2_count = total_completed // 2

    current_user = None
    if current_room == 1 and room1_users:
        current_user = room1_users[(total_completed // 2) % len(room1_users)]
    elif current_room == 2 and room2_users:
        current_user = room2_users[(total_completed // 2) % len(room2_users)]
    elif active_users:
        current_user = active_users[total_completed % len(active_users)]

    # Next week user
    next_user = None
    if next_room == 1 and room1_users:
        next_user = room1_users[((total_completed + 1) // 2) % len(room1_users)]
    elif next_room == 2 and room2_users:
        next_user = room2_users[((total_completed + 1) // 2) % len(room2_users)]
    elif active_users:
        next_user = active_users[(total_completed + 1) % len(active_users)]

    today = date.today()
    current_week_start = today - timedelta(days=today.weekday())
    next_week_start = current_week_start + timedelta(days=7)

    return {
        "current_room": current_room,
        "current_user": current_user,
        "next_room": next_room,
        "next_user": next_user,
        "current_week_dates": (current_week_start, current_week_start + timedelta(days=6)),
        "next_week_dates": (next_week_start, next_week_start + timedelta(days=6)),
        "total_deliveries": total_completed,
    }


async def complete_water_duty(session: AsyncSession, user_id: int) -> User:
    """Record that 19L drinking water bottle was brought by user."""
    today = date.today()
    record = DutyHistory(
        user_id=user_id,
        duty_type=DutyType.WATER,
        duty_date=today,
        status=DutyStatus.COMPLETED,
    )
    session.add(record)
    await session.commit()

    result = await session.execute(select(User).where(User.id == user_id))
    return result.scalar_one()


async def mark_daily_duty_completed(
    session: AsyncSession,
    user_id: int,
    duty_date: date,
) -> DutyHistory:
    """Mark daily duty as completed for given user and date."""
    result = await session.execute(
        select(DutyHistory)
        .where(
            DutyHistory.duty_date == duty_date,
            DutyHistory.duty_type == DutyType.DAILY,
        )
    )
    record = result.scalar_one_or_none()

    if record:
        record.status = DutyStatus.COMPLETED
        record.user_id = user_id
    else:
        record = DutyHistory(
            user_id=user_id,
            duty_type=DutyType.DAILY,
            duty_date=duty_date,
            status=DutyStatus.COMPLETED,
        )
        session.add(record)

    await session.commit()
    return record


async def execute_duty_swap(
    session: AsyncSession,
    user_a_id: int,
    date_a: date,
    user_b_id: int,
    date_b: date,
) -> bool:
    """
    Swap duties between User A (on date_a) and User B (on date_b).
    Creates or updates DutyHistory records for both dates.
    """
    res_a = await session.execute(
        select(DutyHistory).where(
            DutyHistory.duty_date == date_a,
            DutyHistory.duty_type == DutyType.DAILY,
        )
    )
    rec_a = res_a.scalar_one_or_none()
    if rec_a:
        rec_a.user_id = user_b_id
        rec_a.status = DutyStatus.SWAPPED
    else:
        rec_a = DutyHistory(
            user_id=user_b_id,
            duty_type=DutyType.DAILY,
            duty_date=date_a,
            status=DutyStatus.SWAPPED,
        )
        session.add(rec_a)

    res_b = await session.execute(
        select(DutyHistory).where(
            DutyHistory.duty_date == date_b,
            DutyHistory.duty_type == DutyType.DAILY,
        )
    )
    rec_b = res_b.scalar_one_or_none()
    if rec_b:
        rec_b.user_id = user_a_id
        rec_b.status = DutyStatus.SWAPPED
    else:
        rec_b = DutyHistory(
            user_id=user_a_id,
            duty_type=DutyType.DAILY,
            duty_date=date_b,
            status=DutyStatus.SWAPPED,
        )
        session.add(rec_b)

    await session.commit()
    return True


async def apply_missed_duty_fine(
    session: AsyncSession,
    duty_date: date,
) -> Optional[PenaltyFund]:
    """If today's duty is not marked COMPLETED at end of day, record fine in PenaltyFund."""
    user, duty_record = await get_duty_for_date(session, duty_date)
    if not user:
        return None

    if duty_record and duty_record.status == DutyStatus.COMPLETED:
        return None

    existing_fine = await session.execute(
        select(PenaltyFund).where(
            PenaltyFund.user_id == user.id,
            PenaltyFund.reason.like(f"%{duty_date}%"),
        )
    )
    if existing_fine.scalar_one_or_none():
        return None

    if duty_record:
        duty_record.status = DutyStatus.FINED
    else:
        duty_record = DutyHistory(
            user_id=user.id,
            duty_type=DutyType.DAILY,
            duty_date=duty_date,
            status=DutyStatus.FINED,
        )
        session.add(duty_record)

    fine = PenaltyFund(
        user_id=user.id,
        amount=settings.DAILY_FINE_AMOUNT,
        reason=f"Kunlik navbatchilik bajarilmadi ({duty_date})",
        is_paid=False,
    )
    session.add(fine)
    await session.commit()
    return fine
