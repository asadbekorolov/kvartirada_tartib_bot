from datetime import date, datetime, timedelta
from typing import Dict, List, Optional, Tuple
from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from config import settings
from database.models import (
    DailyTaskState,
    DutyHistory,
    DutyStatus,
    DutyType,
    DutyVote,
    PenaltyFund,
    RotationState,
    User,
)
from keyboards.inline import DAILY_5_TASKS, SLOT_NAMES


async def get_active_users(session: AsyncSession) -> List[User]:
    """Return all active users ordered by their order_index."""
    result = await session.execute(
        select(User)
        .where(User.is_active.is_(True))
        .order_by(User.order_index.asc(), User.id.asc())
    )
    return list(result.scalars().all())


async def get_occupied_slots_map(session: AsyncSession) -> Dict[int, User]:
    """Return dictionary mapping assigned_day (0..7) to active User."""
    result = await session.execute(
        select(User)
        .where(User.is_active.is_(True), User.assigned_day.isnot(None))
    )
    users = result.scalars().all()
    return {u.assigned_day: u for u in users}


async def assign_user_slot(
    session: AsyncSession,
    user_id: int,
    day_index: int,
) -> Tuple[bool, Optional[str]]:
    """
    Assign a chosen day slot (0..7) to user with concurrency check.
    Returns (True, None) on success, or (False, owner_name) if already occupied.
    """
    user_res = await session.execute(
        select(User).where((User.telegram_id == user_id) | (User.id == user_id))
    )
    user = user_res.scalar_one_or_none()
    if not user:
        return False, None

    # Check if slot is already occupied by another active user
    result = await session.execute(
        select(User).where(
            User.is_active.is_(True),
            User.assigned_day == day_index,
            User.id != user.id,
        )
    )
    occupied_by = result.scalar_one_or_none()
    if occupied_by:
        return False, occupied_by.full_name

    user.assigned_day = day_index
    user.order_index = day_index
    session.add(user)
    await session.commit()
    return True, None


async def get_or_create_rotation_state(session: AsyncSession) -> RotationState:
    """Get the current rotation anchor checkpoint or initialize it if absent."""
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
    """Fallback Round-Robin index when assigned_day is not set."""
    if total_users <= 0:
        return 0
    delta_days = (target_date - anchor_date).days
    return (anchor_slot + delta_days) % total_users


async def rebalance_users(
    session: AsyncSession,
    reference_user_for_anchor: Optional[User] = None,
) -> List[User]:
    """
    Rebalance the queue for all active users so order_index is contiguous.
    Preserves assigned_day if set.
    """
    today = date.today()
    users = await get_active_users(session)
    n = len(users)

    for idx, user in enumerate(users):
        if user.assigned_day is not None:
            user.order_index = user.assigned_day
        else:
            user.order_index = idx
        session.add(user)
    await session.commit()

    if n > 0:
        rot_state = await get_or_create_rotation_state(session)
        if reference_user_for_anchor and reference_user_for_anchor.is_active:
            new_anchor_slot = reference_user_for_anchor.order_index
        else:
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
    Add or reactivate user in the database without assigning slot yet.
    Slot selection happens in the next step via inline day buttons.
    """
    result = await session.execute(
        select(User).where((User.telegram_id == user_id) | (User.id == user_id))
    )
    user = result.scalar_one_or_none()

    if user is None:
        user = User(
            id=user_id,
            telegram_id=user_id,
            username=username,
            full_name=full_name,
            room_number=room_number,
            order_index=0,
            assigned_day=None,
            is_active=True,
        )
        session.add(user)
        await session.commit()
        return user, True
    else:
        user.username = username
        user.full_name = full_name
        user.room_number = room_number
        user.is_active = True
        session.add(user)
        await session.commit()
        return user, False


add_or_update_user = register_or_join


async def leave_and_rebalance(session: AsyncSession, user_id: int) -> bool:
    """Pause duty / leave duty rotation, clear their slot, and rebalance remaining members."""
    result = await session.execute(
        select(User).where((User.telegram_id == user_id) | (User.id == user_id))
    )
    user = result.scalar_one_or_none()
    if not user or not user.is_active:
        return False

    today = date.today()
    duty_user_today, _ = await get_duty_for_date(session, today)

    # User remains active in apartment, but pauses duty rotation (assigned_day = None)
    user.assigned_day = None
    session.add(user)
    await session.commit()

    ref_user = duty_user_today if (duty_user_today and duty_user_today.id != user.id) else None
    await rebalance_users(session, reference_user_for_anchor=ref_user)
    return True


deactivate_user = leave_and_rebalance


async def get_duty_for_date(
    session: AsyncSession,
    target_date: date,
) -> Tuple[Optional[User], Optional[DutyHistory]]:
    """
    Berilgan sana uchun kunlik mas'ul navbatchini aniqlash.
    1. DutyHistory jadvalidan (agar swap/almashtirish bo'lgan bo'lsa) tekshiradi.
    2. Shu haftaning kuni (0=Dushanba, ..., 6=Yakshanba) ga biriktirilgan (assigned_day) xonadoshni oladi.
    3. Agar topilmasa, fallback rotatsiyadan foydalanadi.
    """
    active_users = await get_active_users(session)
    if not active_users:
        return None, None

    # 1. Check explicit DutyHistory
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

    # 2. Check assigned_day matching the target date's weekday
    target_weekday = target_date.weekday()
    user_by_day = next((u for u in active_users if u.assigned_day == target_weekday), None)
    if user_by_day:
        return user_by_day, None

    # 3. Fallback to rotation state
    duty_pool = [u for u in active_users if u.assigned_day is not None] or active_users
    rot_state = await get_or_create_rotation_state(session)
    slot_index = calculate_rotation_index(
        target_date=target_date,
        total_users=len(duty_pool),
        anchor_date=rot_state.anchor_date,
        anchor_slot=rot_state.anchor_slot,
    )
    assigned_user = duty_pool[slot_index]
    return assigned_user, None


get_daily_duty = get_duty_for_date


# =====================================================================
# Kunlik 5 talik Vazifalar Boshqaruvi
# =====================================================================

async def get_or_create_daily_tasks(
    session: AsyncSession,
    duty_date: date,
) -> List[DailyTaskState]:
    """Retrieve or initialize the 5 daily tasks for given date."""
    result = await session.execute(
        select(DailyTaskState)
        .options(selectinload(DailyTaskState.completed_by_user))
        .where(DailyTaskState.duty_date == duty_date)
        .order_by(DailyTaskState.id.asc())
    )
    existing_tasks = list(result.scalars().all())
    existing_keys = {t.task_key for t in existing_tasks}

    created_any = False
    for task_key in DAILY_5_TASKS.keys():
        if task_key not in existing_keys:
            new_task = DailyTaskState(
                duty_date=duty_date,
                task_key=task_key,
                is_done=False,
                completed_by=None,
            )
            session.add(new_task)
            created_any = True

    if created_any:
        await session.commit()
        result = await session.execute(
            select(DailyTaskState)
            .options(selectinload(DailyTaskState.completed_by_user))
            .where(DailyTaskState.duty_date == duty_date)
            .order_by(DailyTaskState.id.asc())
        )
        existing_tasks = list(result.scalars().all())

    task_order = list(DAILY_5_TASKS.keys())
    existing_tasks.sort(key=lambda item: task_order.index(item.task_key) if item.task_key in task_order else 999)
    return existing_tasks


async def toggle_daily_task(
    session: AsyncSession,
    duty_date: date,
    task_key: str,
    user_id: int,
) -> Tuple[Optional[DailyTaskState], bool, bool, int]:
    """
    Toggle one of the 5 daily tasks.
    If all 5 tasks become done, marks DutyHistory as COMPLETED.
    Returns (task_item, new_status, is_all_completed, completed_count).
    """
    tasks = await get_or_create_daily_tasks(session, duty_date)
    task_item = next((t for t in tasks if t.task_key == task_key), None)

    if not task_item:
        return None, False, False, 0

    if task_item.is_done:
        task_item.is_done = False
        task_item.completed_by = None
        new_status = False
    else:
        task_item.is_done = True
        task_item.completed_by = user_id
        new_status = True

    session.add(task_item)
    await session.commit()

    # Re-check all 5 tasks
    tasks = await get_or_create_daily_tasks(session, duty_date)
    completed_count = sum(1 for t in tasks if t.is_done)
    is_all_completed = (completed_count == len(DAILY_5_TASKS))

    # Update DutyHistory accordingly
    res = await session.execute(
        select(DutyHistory).where(
            DutyHistory.duty_date == duty_date,
            DutyHistory.duty_type == DutyType.DAILY,
        )
    )
    duty_record = res.scalar_one_or_none()

    if is_all_completed:
        if duty_record:
            duty_record.status = DutyStatus.COMPLETED
            duty_record.user_id = user_id
        else:
            duty_record = DutyHistory(
                user_id=user_id,
                duty_type=DutyType.DAILY,
                duty_date=duty_date,
                status=DutyStatus.COMPLETED,
            )
            session.add(duty_record)
        await session.commit()
    else:
        if duty_record and duty_record.status == DutyStatus.COMPLETED:
            duty_record.status = DutyStatus.PENDING
            session.add(duty_record)
            await session.commit()

    return task_item, new_status, is_all_completed, completed_count


async def are_all_daily_tasks_done(session: AsyncSession, duty_date: date) -> bool:
    """Check if all 5 daily tasks are completed."""
    tasks = await get_or_create_daily_tasks(session, duty_date)
    return all(t.is_done for t in tasks) and len(tasks) == len(DAILY_5_TASKS)


async def get_laundry_duty_for_date(
    session: AsyncSession,
    target_date: date,
) -> Optional[User]:
    """Bugungi kir yuvish mashinasidan foydalanish huquqiga ega xonadosh."""
    active_users = await get_active_users(session)
    if not active_users:
        return None

    duty_user, _ = await get_duty_for_date(session, target_date)
    # Fair offset: len // 2 to separate laundry from kitchen duty
    if duty_user and len(active_users) > 1:
        duty_idx = active_users.index(duty_user) if duty_user in active_users else 0
        laundry_idx = (duty_idx + max(1, len(active_users) // 2)) % len(active_users)
        return active_users[laundry_idx]

    return active_users[0]


async def get_weekly_schedule(
    session: AsyncSession,
    start_date: Optional[date] = None,
) -> List[dict]:
    """Get 7-day schedule with duty holders and laundry turns."""
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
    """Weekend grocery shopping pair."""
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
    """1-xona va 2-xona bo'yicha 2 haftalik suv olib kelish navbatini hisoblash."""
    active_users = await get_active_users(session)
    room1_users = [u for u in active_users if u.room_number == 1]
    room2_users = [u for u in active_users if u.room_number == 2]

    result = await session.execute(
        select(func.count(DutyHistory.id)).where(
            DutyHistory.duty_type == DutyType.WATER,
            DutyHistory.status == DutyStatus.COMPLETED,
        )
    )
    total_completed = result.scalar_one() or 0

    current_room = 1 if (total_completed % 2 == 0) else 2
    next_room = 2 if current_room == 1 else 1

    current_user = None
    if current_room == 1 and room1_users:
        current_user = room1_users[(total_completed // 2) % len(room1_users)]
    elif current_room == 2 and room2_users:
        current_user = room2_users[(total_completed // 2) % len(room2_users)]
    elif active_users:
        current_user = active_users[total_completed % len(active_users)]

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
    """Record that 10L drinking water was brought by user."""
    today = date.today()
    user_res = await session.execute(
        select(User).where((User.telegram_id == user_id) | (User.id == user_id))
    )
    user = user_res.scalar_one()

    record = DutyHistory(
        user_id=user.id,
        duty_type=DutyType.WATER,
        duty_date=today,
        status=DutyStatus.COMPLETED,
    )
    session.add(record)
    await session.commit()
    return user


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
    """Swap duties between User A and User B on their respective dates."""
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
    """
    Check if all 5 daily tasks were completed.
    If not, record 15,000 UZS penalty in PenaltyFund.
    """
    user, duty_record = await get_duty_for_date(session, duty_date)
    if not user:
        return None

    # Check 5 tasks completion
    all_done = await are_all_daily_tasks_done(session, duty_date)
    if all_done:
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
        reason=f"Kunlik 5 ta vazifa to'liq bajarilmadi ({duty_date})",
        is_paid=False,
    )
    session.add(fine)
    await session.commit()
    return fine


async def get_duty_votes_count(
    session: AsyncSession,
    duty_date: date,
    reason: str,
) -> Tuple[int, int]:
    """Return (fine_count, forgive_count) for given date and reason."""
    res_fine = await session.execute(
        select(func.count(DutyVote.id)).where(
            DutyVote.duty_date == duty_date,
            DutyVote.reason == reason,
            DutyVote.vote_type == "FINE",
        )
    )
    fine_count = res_fine.scalar_one() or 0

    res_forgive = await session.execute(
        select(func.count(DutyVote.id)).where(
            DutyVote.duty_date == duty_date,
            DutyVote.reason == reason,
            DutyVote.vote_type == "FORGIVE",
        )
    )
    forgive_count = res_forgive.scalar_one() or 0

    return fine_count, forgive_count


async def cast_duty_vote(
    session: AsyncSession,
    duty_date: date,
    voter_id: int,
    target_user_id: int,
    vote_type: str,
    reason: str,
    threshold: int = 3,
) -> Tuple[bool, str, int, int, bool]:
    """
    Record or update a vote on duty penalty/forgive.
    Returns: (success, status_code, fine_count, forgive_count, is_concluded)
    status_codes:
      - 'SELF_VOTE': Target user cannot vote for themselves.
      - 'ALREADY_CONCLUDED': Vote concluded and penalty already applied.
      - 'FINE_APPLIED': Threshold reached and 15,000 UZS penalty recorded.
      - 'FORGIVEN': Threshold reached to forgive.
      - 'VOTE_CAST': Vote registered, waiting for more votes.
    """
    if voter_id == target_user_id:
        f_cnt, fg_cnt = await get_duty_votes_count(session, duty_date, reason)
        return False, "SELF_VOTE", f_cnt, fg_cnt, False

    # Check if penalty was already applied for this reason & date
    existing_fine = await session.execute(
        select(PenaltyFund).where(
            PenaltyFund.user_id == target_user_id,
            PenaltyFund.reason.like(f"%{reason}%{duty_date}%"),
        )
    )
    if existing_fine.scalar_one_or_none():
        f_cnt, fg_cnt = await get_duty_votes_count(session, duty_date, reason)
        return False, "ALREADY_CONCLUDED", f_cnt, fg_cnt, True

    # Record or update vote
    res = await session.execute(
        select(DutyVote).where(
            DutyVote.duty_date == duty_date,
            DutyVote.voter_id == voter_id,
            DutyVote.reason == reason,
        )
    )
    existing_vote = res.scalar_one_or_none()

    if existing_vote:
        existing_vote.vote_type = vote_type
    else:
        new_vote = DutyVote(
            duty_date=duty_date,
            voter_id=voter_id,
            target_user_id=target_user_id,
            vote_type=vote_type,
            reason=reason,
        )
        session.add(new_vote)

    await session.commit()

    fine_count, forgive_count = await get_duty_votes_count(session, duty_date, reason)

    # Check conclusion by threshold
    if fine_count >= threshold:
        # Apply penalty
        fine_record = PenaltyFund(
            user_id=target_user_id,
            amount=settings.DAILY_FINE_AMOUNT,
            reason=f"Ovoz berish natijasida jarima ({reason}: {duty_date})",
            is_paid=False,
        )
        session.add(fine_record)

        hist_res = await session.execute(
            select(DutyHistory).where(
                DutyHistory.duty_date == duty_date,
                DutyHistory.duty_type == DutyType.DAILY,
            )
        )
        hist = hist_res.scalar_one_or_none()
        if hist:
            hist.status = DutyStatus.FINED
        await session.commit()
        return True, "FINE_APPLIED", fine_count, forgive_count, True

    elif forgive_count >= threshold:
        return True, "FORGIVEN", fine_count, forgive_count, True

    return True, "VOTE_CAST", fine_count, forgive_count, False

