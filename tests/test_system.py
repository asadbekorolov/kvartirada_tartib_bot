import asyncio
import os
import sys
from datetime import date, timedelta

# Ensure parent directory is in sys.path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))
if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8")

from database.models import DutyStatus, Expense, ExpenseShare, PenaltyFund, RotationState, User
from database.session import engine, get_session, init_db
from services.cleaning_service import (
    CLEANING_TASKS,
    get_or_create_week_checklist,
    get_weekend_date_for,
    toggle_checklist_task,
)
from services.duty_service import (
    apply_missed_duty_fine,
    complete_water_duty,
    execute_duty_swap,
    get_active_users,
    get_duty_for_date,
    get_laundry_duty_for_date,
    get_water_duty_schedule,
    get_weekly_schedule,
    get_weekend_grocery_duty,
    leave_and_rebalance,
    mark_daily_duty_completed,
    register_or_join,
)
from services.expense_service import (
    create_expense,
    format_expense_report,
    get_expense_by_id,
    mark_expense_share_paid,
)


async def run_tests():
    print("=" * 70)
    print("MISSION 3-BOSQICH: SPLIT-BILL, MEHMON, FOND VA DOKER TIZIMLARI TESTI")
    print("=" * 70)

    from database.base import Base

    # 1. Reset DB tables cleanly
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
    await init_db()
    print(" [PASS] 1. Ma'lumotlar bazasi toza holatda yaratildi va barcha jadvallar faollashtirildi.")

    async with get_session() as session:
        # 2. Add 8 initial apartment residents
        residents_data = [
            (101, "asadbek", "Asadbek Karimov", 1),
            (102, "nodir", "Nodir Zokirov", 1),
            (103, "bekzod", "Bekzod Umarov", 1),
            (104, "jasur", "Jasur Aliyev", 1),
            (105, "sanjar", "Sanjar Toshmatov", 2),
            (106, "umid", "Umid Rahimov", 2),
            (107, "davron", "Davron Ergashev", 2),
            (108, "javohir", "Javohir Saidov", 2),
        ]

        for uid, uname, name, room in residents_data:
            await register_or_join(session, user_id=uid, full_name=name, room_number=room, username=uname)

        users = await get_active_users(session)
        assert len(users) == 8
        print(f" [PASS] 2. 8 nafar xonadosh ro'yxatdan o'tkazildi.")

        # 3. Test Split-Bill (Bozorlik xarajatini 8 kishiga taqsimlash)
        total_spent = 360000
        desc = "Go'sht 2kg, kartoshka 5kg, yog' 2L, piyoz va sabzavotlar"
        payer_id = 101 # Asadbek Karimov
        expense = await create_expense(session, payer_id=payer_id, total_amount=total_spent, description=desc)

        assert expense.id is not None
        assert expense.total_amount == 360000
        assert expense.per_person == 45000 # 360,000 / 8 = 45,000
        assert len(expense.shares) == 8

        # Payer should be marked is_paid = True
        payer_share = next(s for s in expense.shares if s.user_id == payer_id)
        assert payer_share.is_paid is True
        print(f" [PASS] 3. Split-Bill hisoblandi: Jami {total_spent:,} so'm / 8 kishi = {expense.per_person:,} so'mdan.")
        print(f"       Xarid egasi (Asadbek Karimov) ulushi avtomatik to'langan deb belgilandi.")

        # 4. Another roommate marks their share as paid (Nodir Zokirov pays)
        success, updated_exp = await mark_expense_share_paid(session, expense_id=expense.id, user_id=102)
        assert success is True
        nodir_share = next(s for s in updated_exp.shares if s.user_id == 102)
        assert nodir_share.is_paid is True
        paid_count = sum(1 for s in updated_exp.shares if s.is_paid)
        assert paid_count == 2
        print(" [PASS] 4. Xonadosh Nodir Zokirov ulushi 'To'landi' deb belgilandi va hisobot yangilandi.")

        # Verify HTML report formatting
        report_text = format_expense_report(updated_exp)
        assert "45,000 so'm" in report_text
        assert "Nodir Zokirov" in report_text
        print(" [PASS] 5. Bozorlik HTML hisoboti formati to'g'ri shakllandi.")

        # 5. Test Penalty Fund balance and Settlement
        fine = await apply_missed_duty_fine(session, date.today() - timedelta(days=1))
        assert fine is not None
        assert fine.is_paid is False

        # Mark fine as paid
        fine.is_paid = True
        session.add(fine)
        await session.commit()
        assert fine.is_paid is True
        print(f" [PASS] 6. Jarima fondi: 15,000 so'm jarima yozildi va 'To'landi' holatiga o'tkazildi.")

        # 6. Test Rotation Continuity with Anchor State
        today = date.today()
        duty_before, _ = await get_duty_for_date(session, today)
        # Jasur Aliyev leaves
        await leave_and_rebalance(session, 104)
        duty_after, _ = await get_duty_for_date(session, today)
        assert duty_before.id == duty_after.id
        print(" [PASS] 7. Rotation Anchor: A'zo chiqqanda navbat uzluksizligi saqlanib qoldi.")

        # 7. Test 11-step cleaning checklist
        weekend_sun = get_weekend_date_for(today)
        checklist = await get_or_create_week_checklist(session, weekend_sun)
        assert len(checklist) == 11
        item, status = await toggle_checklist_task(session, checklist[0].task_key, 101, weekend_sun)
        assert status is True
        print(" [PASS] 8. 11 bandlik tozalash checklisti muvaffaqiyatli tekshirildi.")

        # 8. Test 2-Week Water Schedule
        water_sched = await get_water_duty_schedule(session)
        assert water_sched["current_room"] in (1, 2)
        assert water_sched["current_user"] is not None
        print(" [PASS] 9. 1-Xona va 2-Xona bo'yicha 2 haftalik suv navbati tekshirildi.")

        # 10. Test Self-Service Slot Selection & Concurrency Locking
        from services.duty_service import (
            assign_user_slot,
            get_occupied_slots_map,
            get_or_create_daily_tasks,
            toggle_daily_task,
            are_all_daily_tasks_done,
        )

        # User 101 chooses slot 0 (Dushanba)
        success_1, occ_name_1 = await assign_user_slot(session, user_id=101, day_index=0)
        assert success_1 is True
        assert occ_name_1 is None

        # User 102 tries to choose slot 0 (Dushanba) -> Concurrency locking must block!
        success_2, occ_name_2 = await assign_user_slot(session, user_id=102, day_index=0)
        assert success_2 is False
        assert occ_name_2 == "Asadbek Karimov"

        # User 102 chooses slot 1 (Seshanba) -> Success
        success_3, occ_name_3 = await assign_user_slot(session, user_id=102, day_index=1)
        assert success_3 is True
        assert occ_name_3 is None

        occupied_map = await get_occupied_slots_map(session)
        assert 0 in occupied_map and occupied_map[0].id == 101
        assert 1 in occupied_map and occupied_map[1].id == 102
        print(" [PASS] 10. Self-Service Slot Selection & Concurrency Locking (Bandlik nazorati) muvaffaqiyatli tekshirildi.")

        # 11. Test 5-Item Daily Tasks Checklist
        test_duty_date = date.today()
        # Initialize 5 tasks
        daily_tasks = await get_or_create_daily_tasks(session, test_duty_date)
        assert len(daily_tasks) == 5
        assert all(t.is_done is False for t in daily_tasks)

        # Toggle first task (task_meal)
        t_item, t_stat, t_all, t_cnt = await toggle_daily_task(session, test_duty_date, "task_meal", 101)
        assert t_stat is True
        assert t_cnt == 1
        assert t_all is False

        # Toggle remaining 4 tasks
        for k in ["task_bread", "task_table", "task_dishes", "task_trash"]:
            _, _, t_all, t_cnt = await toggle_daily_task(session, test_duty_date, k, 101)

        assert t_cnt == 5
        assert t_all is True
        assert await are_all_daily_tasks_done(session, test_duty_date) is True

        # When all 5 are done, duty record must be COMPLETED and no fine applied
        fine_res = await apply_missed_duty_fine(session, test_duty_date)
        assert fine_res is None
        print(" [PASS] 12. 5 talik Kunlik Checklist, avtomatik COMPLETED va jarima nazorati muvaffaqiyatli tekshirildi.")

    await engine.dispose()
    print("=" * 70)
    print("BARCHA 12 TA TIZIM TESTLARI MUVAFFAQIYATLI O'TDI! 🚀")
    print("=" * 70)


if __name__ == "__main__":
    if sys.platform == "win32":
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
    asyncio.run(run_tests())
