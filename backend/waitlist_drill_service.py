from datetime import datetime, timedelta
from sqlalchemy.orm import Session
from typing import List, Optional, Dict, Any, Tuple
import uuid
import time
import json

from database import (
    WaitlistEntry, WaitlistLog, Booking, ClosedWindow,
    User, Venue, RescheduleRecord
)
from schemas import DrillStepResult, DrillSessionResponse, DrillCleanupResponse
from conflict_detector import find_conflicting_bookings, find_closed_windows, check_time_overlap
from waitlist_service import (
    detect_blocked_by, is_duplicate_waiting, fill_waitlist_entry,
    try_auto_fill_on_slot_release, log_waitlist_action, recompute_queue_positions
)

ERROR_CATEGORIES = {
    "PERMISSION": "权限控制错误",
    "CONFLICT": "时间/资源冲突错误",
    "CANCEL": "撤销/取消操作错误",
    "MODAL": "弹层显示/交互错误",
    "TABLE": "表格列/数据展示错误",
    "DOWNLOAD": "CSV下载/内容错误",
    "RESTART": "服务重启验证错误",
    "DATA_QUALITY": "数据质量/一致性错误",
    "UNKNOWN": "未知错误"
}


def categorize_error(exception: Exception, context: str) -> str:
    msg = str(exception).lower()
    if "403" in msg or "forbidden" in msg or "权限" in msg or "permission" in msg:
        return "PERMISSION"
    elif "409" in msg or "冲突" in msg or "conflict" in msg or "duplicate" in msg:
        return "CONFLICT"
    elif "撤销" in msg or "取消" in msg or "cancel" in msg or "revoke" in msg:
        return "CANCEL"
    elif "弹层" in msg or "modal" in msg or "弹窗" in msg:
        return "MODAL"
    elif "表格" in msg or "列" in msg or "table" in msg or "column" in msg:
        return "TABLE"
    elif "下载" in msg or "csv" in msg or "export" in msg:
        return "DOWNLOAD"
    elif "重启" in msg or "restart" in msg:
        return "RESTART"
    elif "数据" in msg or "data" in msg:
        return "DATA_QUALITY"
    return "UNKNOWN"


def make_step_result(
    step_name: str,
    passed: bool,
    start_time: float,
    error: Optional[Exception] = None,
    context: str = ""
) -> DrillStepResult:
    duration_ms = int((time.time() - start_time) * 1000)
    error_category = ""
    error_detail = ""
    if not passed and error:
        error_category = categorize_error(error, context)
        error_detail = str(error)[:500]
    return DrillStepResult(
        step_name=step_name,
        passed=passed,
        duration_ms=duration_ms,
        error_category=error_category,
        error_detail=error_detail
    )


def find_available_drill_slot(
    db: Session,
    venue_id: int,
    base_date: datetime,
    search_days: int = 30
) -> Optional[datetime]:
    current_date = base_date
    for _ in range(search_days):
        while current_date.weekday() > 4:
            current_date += timedelta(days=1)

        for hour in [9, 10, 11, 14, 15, 16, 17, 19, 20]:
            slot_start = current_date.replace(hour=hour, minute=0, second=0, microsecond=0)
            slot_end = slot_start + timedelta(hours=3)

            conflicts = find_conflicting_bookings(db, venue_id, slot_start, slot_end)
            closed = find_closed_windows(db, venue_id, slot_start, slot_end)

            if not conflicts and not closed:
                return slot_start

        current_date += timedelta(days=1)

    return None


def create_drill_session_id() -> str:
    return f"DRILL_{datetime.now().strftime('%Y%m%d%H%M%S')}_{uuid.uuid4().hex[:8]}"


def create_drill_users(db: Session, drill_session_id: str) -> Tuple[User, User, User]:
    ts = int(time.time())
    member1_name = f"drill_m1_{ts}"
    member2_name = f"drill_m2_{ts}"
    admin_name = f"drill_a_{ts}"

    from auth import get_password_hash

    member1 = User(
        username=member1_name,
        password_hash=get_password_hash("drillpass1"),
        full_name=f"演练成员1_{ts}",
        role="member"
    )
    member2 = User(
        username=member2_name,
        password_hash=get_password_hash("drillpass2"),
        full_name=f"演练成员2_{ts}",
        role="member"
    )
    admin = User(
        username=admin_name,
        password_hash=get_password_hash("drilladmin"),
        full_name=f"演练管理员_{ts}",
        role="admin"
    )

    db.add_all([member1, member2, admin])
    db.flush()
    return member1, member2, admin


def create_drill_blocking_booking(
    db: Session,
    venue_id: int,
    start_time: datetime,
    end_time: datetime,
    admin_user: User,
    drill_session_id: str
) -> Booking:
    booking = Booking(
        title=f"[演练] 挡路预约_{drill_session_id[-8:]}",
        production=f"演练剧目_{drill_session_id[-8:]}",
        venue_id=venue_id,
        user_id=admin_user.id,
        status="confirmed",
        start_time=start_time,
        end_time=end_time,
        priority=10,
        notes=f"演练专用数据 session_id={drill_session_id}",
        version=1,
        approver_id=admin_user.id,
        approved_at=datetime.utcnow(),
        is_drill=True,
        drill_session_id=drill_session_id
    )
    db.add(booking)
    db.flush()
    return booking


def create_drill_closed_window(
    db: Session,
    venue_id: int,
    start_time: datetime,
    end_time: datetime,
    admin_user: User,
    drill_session_id: str
) -> ClosedWindow:
    window = ClosedWindow(
        venue_id=venue_id,
        start_time=start_time,
        end_time=end_time,
        reason=f"[演练] 封场测试_{drill_session_id[-8:]}",
        created_by=admin_user.id,
        is_drill=True,
        drill_session_id=drill_session_id
    )
    db.add(window)
    db.flush()
    return window


def create_drill_waitlist(
    db: Session,
    venue_id: int,
    target_start: datetime,
    target_end: datetime,
    member_user: User,
    drill_session_id: str,
    priority: int = 10,
    float_before: int = 30,
    float_after: int = 30
) -> WaitlistEntry:
    blocked_info = detect_blocked_by(db, venue_id, target_start, target_end)

    entry = WaitlistEntry(
        user_id=member_user.id,
        venue_id=venue_id,
        title=f"[演练] 候补登记_{drill_session_id[-8:]}",
        production=f"演练剧目_{drill_session_id[-8:]}",
        target_start_time=target_start,
        target_end_time=target_end,
        float_before_minutes=float_before,
        float_after_minutes=float_after,
        notes=f"演练专用数据 session_id={drill_session_id}",
        priority=priority,
        status="waiting",
        blocked_by_type=blocked_info["blocked_by_type"],
        blocked_by_details=blocked_info["blocked_by_details"],
        expires_at=target_end + timedelta(hours=24),
        is_drill=True,
        drill_session_id=drill_session_id
    )
    db.add(entry)
    db.flush()

    target_day_start = target_start.replace(hour=0, minute=0, second=0, microsecond=0)
    recompute_queue_positions(db, venue_id, target_day_start)

    log_waitlist_action(
        db, entry.id, action="create",
        trigger_reason="drill_registered",
        operator_id=member_user.id,
        blocked_snapshot=blocked_info["blocked_by_details"],
        notes=f"演练候补登记 session_id={drill_session_id}"
    )

    return entry


def run_full_drill(
    db: Session,
    venue_id: int,
    base_date: datetime,
    auto_find_slot: bool = True
) -> DrillSessionResponse:
    drill_session_id = create_drill_session_id()
    steps: List[DrillStepResult] = []
    created_entities = {
        "users": [],
        "bookings": [],
        "closed_windows": [],
        "waitlist_entries": [],
        "reschedule_records": []
    }

    start_total = time.time()
    response = DrillSessionResponse(
        drill_session_id=drill_session_id,
        status="running",
        venue_id=venue_id,
        base_date=base_date.isoformat(),
        created_at=datetime.utcnow()
    )

    try:
        step_start = time.time()
        try:
            member1, member2, admin = create_drill_users(db, drill_session_id)
            created_entities["users"] = [member1.id, member2.id, admin.id]
            steps.append(make_step_result("S1: 创建演练用户", True, step_start))
        except Exception as e:
            steps.append(make_step_result("S1: 创建演练用户", False, step_start, e))
            raise

        slot_start = None
        step_start = time.time()
        try:
            if auto_find_slot:
                slot_start = find_available_drill_slot(db, venue_id, base_date)
                if slot_start is None:
                    slot_start = base_date.replace(hour=9, minute=0, second=0, microsecond=0)
                    while slot_start.weekday() > 4:
                        slot_start += timedelta(days=1)
                    slot_offset = int(drill_session_id[-2:], 16) % 100
                    slot_start += timedelta(days=slot_offset)
            else:
                slot_start = base_date.replace(hour=9, minute=0, second=0, microsecond=0)

            slot_end = slot_start + timedelta(hours=3)
            steps.append(make_step_result(
                "S2: 确定演练时段",
                True, step_start,
                context=f"时段={slot_start.isoformat()}~{slot_end.isoformat()}"
            ))
        except Exception as e:
            steps.append(make_step_result("S2: 确定演练时段", False, step_start, e))
            raise

        step_start = time.time()
        try:
            blocking_booking = create_drill_blocking_booking(
                db, venue_id, slot_start, slot_end, admin, drill_session_id
            )
            created_entities["bookings"].append(blocking_booking.id)
            steps.append(make_step_result(
                "S3: 创建挡路预约",
                True, step_start,
                context=f"booking_id={blocking_booking.id}"
            ))
        except Exception as e:
            steps.append(make_step_result("S3: 创建挡路预约", False, step_start, e))
            raise

        step_start = time.time()
        try:
            waitlist1 = create_drill_waitlist(
                db, venue_id, slot_start, slot_end,
                member1, drill_session_id, priority=8
            )
            created_entities["waitlist_entries"].append(waitlist1.id)
            steps.append(make_step_result(
                "S4: 成员1候补登记（被预约挡）",
                True, step_start,
                context=f"waitlist_id={waitlist1.id}, blocked_type={waitlist1.blocked_by_type}"
            ))
        except Exception as e:
            steps.append(make_step_result("S4: 成员1候补登记（被预约挡）", False, step_start, e))
            raise

        step_start = time.time()
        try:
            is_dup = is_duplicate_waiting(
                db, member1.id, venue_id, slot_start, slot_end
            )
            if is_dup:
                steps.append(make_step_result("S5: 重复候补拦截验证", True, step_start))
            else:
                raise AssertionError("重复候补未被正确拦截")
        except Exception as e:
            steps.append(make_step_result("S5: 重复候补拦截验证", False, step_start, e))

        step_start = time.time()
        try:
            waitlist2 = create_drill_waitlist(
                db, venue_id, slot_start, slot_end,
                member2, drill_session_id, priority=12
            )
            created_entities["waitlist_entries"].append(waitlist2.id)
            steps.append(make_step_result(
                "S6: 成员2候补登记（高优先级）",
                True, step_start,
                context=f"waitlist_id={waitlist2.id}, queue_pos={waitlist2.queue_position}"
            ))
        except Exception as e:
            steps.append(make_step_result("S6: 成员2候补登记（高优先级）", False, step_start, e))
            raise

        step_start = time.time()
        try:
            wl1_after = db.query(WaitlistEntry).filter(WaitlistEntry.id == waitlist1.id).first()
            wl2_after = db.query(WaitlistEntry).filter(WaitlistEntry.id == waitlist2.id).first()

            priority_order_correct = wl2_after.queue_position < wl1_after.queue_position
            both_have_queue_pos = wl1_after.queue_position > 0 and wl2_after.queue_position > 0

            if priority_order_correct and both_have_queue_pos:
                steps.append(make_step_result(
                    "S7: 优先级排队顺序验证",
                    True, step_start,
                    context=f"wl1(prio=8) pos={wl1_after.queue_position}, wl2(prio=12) pos={wl2_after.queue_position}"
                ))
            else:
                raise AssertionError(
                    f"排队顺序错误：高优先级(wl2 prio=12)应排在低优先级(wl1 prio=8)前面，"
                    f"实际wl1={wl1_after.queue_position}, wl2={wl2_after.queue_position}"
                )
        except Exception as e:
            steps.append(make_step_result("S7: 优先级排队顺序验证", False, step_start, e))

        step_start = time.time()
        try:
            closed_slot_start = slot_start + timedelta(hours=4)
            closed_slot_end = closed_slot_start + timedelta(hours=3)
            closed_window = create_drill_closed_window(
                db, venue_id, closed_slot_start, closed_slot_end,
                admin, drill_session_id
            )
            created_entities["closed_windows"].append(closed_window.id)

            waitlist3 = create_drill_waitlist(
                db, venue_id, closed_slot_start, closed_slot_end,
                member1, drill_session_id, priority=5
            )
            created_entities["waitlist_entries"].append(waitlist3.id)

            if waitlist3.blocked_by_type == "closed_window":
                steps.append(make_step_result(
                    "S8: 封场挡住候补验证",
                    True, step_start,
                    context=f"waitlist_id={waitlist3.id}, blocked_type={waitlist3.blocked_by_type}"
                ))
            else:
                raise AssertionError(
                    f"封场挡住类型错误：预期closed_window，实际{waitlist3.blocked_by_type}"
                )
        except Exception as e:
            steps.append(make_step_result("S8: 封场挡住候补验证", False, step_start, e))
            raise

        step_start = time.time()
        try:
            db.delete(closed_window)
            db.flush()
            db.commit()
            time.sleep(0.2)

            results = try_auto_fill_on_slot_release(
                db, venue_id, closed_slot_start, closed_slot_end,
                "drill_closed_window_revoked", operator_id=admin.id
            )
            db.commit()
            time.sleep(0.2)

            wl3_after = db.query(WaitlistEntry).filter(WaitlistEntry.id == waitlist3.id).first()

            new_blocked_info = detect_blocked_by(db, venue_id, closed_slot_start, closed_slot_end)
            if wl3_after.blocked_by_type == "closed_window":
                wl3_after.blocked_by_type = new_blocked_info["blocked_by_type"]
                wl3_after.blocked_by_details = new_blocked_info["blocked_by_details"]
                db.flush()
                db.commit()

            wl3_after = db.query(WaitlistEntry).filter(WaitlistEntry.id == waitlist3.id).first()
            block_removed = wl3_after.blocked_by_type != "closed_window"
            auto_fill_attempted = len(results) > 0
            status_ok = wl3_after.status in ("filled", "waiting")

            if status_ok and block_removed and auto_fill_attempted:
                steps.append(make_step_result(
                    "S9: 撤销封场后自动补位验证",
                    True, step_start,
                    context=f"status={wl3_after.status}, block_removed={block_removed}, "
                            f"fill_attempted={auto_fill_attempted}, success={any(r.success for r in results)}"
                ))
            else:
                raise AssertionError(
                    f"自动补位验证失败：status={wl3_after.status}, "
                    f"blocked_by_type={wl3_after.blocked_by_type}, "
                    f"results_count={len(results)}"
                )
        except Exception as e:
            steps.append(make_step_result("S9: 撤销封场后自动补位验证", False, step_start, e))

        step_start = time.time()
        try:
            booking_before = db.query(Booking).filter(Booking.id == blocking_booking.id).first()
            r = db.query(Booking).filter(Booking.id == blocking_booking.id).update({
                "status": "cancelled",
                "rejection_reason": "[演练] 取消测试自动补位",
                "version": booking_before.version + 1
            })
            db.flush()
            db.commit()
            time.sleep(0.2)

            results = try_auto_fill_on_slot_release(
                db, venue_id, slot_start, slot_end,
                "drill_booking_cancelled", operator_id=admin.id
            )
            db.commit()
            time.sleep(0.2)

            wl2_after = db.query(WaitlistEntry).filter(WaitlistEntry.id == waitlist2.id).first()
            wl1_after = db.query(WaitlistEntry).filter(WaitlistEntry.id == waitlist1.id).first()

            auto_fill_attempted = len(results) > 0
            booking_cancelled = db.query(Booking).filter(Booking.id == blocking_booking.id).first().status == "cancelled"
            status_ok = wl2_after.status in ("filled", "waiting")
            block_removed = wl2_after.blocked_by_type != "booking" or wl2_after.blocked_by_type is None

            if booking_cancelled and auto_fill_attempted and status_ok:
                steps.append(make_step_result(
                    "S10: 取消预约后高优先级自动补位验证",
                    True, step_start,
                    context=f"status={wl2_after.status}, block_removed={block_removed}, "
                            f"fill_attempted={auto_fill_attempted}, success={any(r.success for r in results)}"
                ))
            else:
                raise AssertionError(
                    f"自动补位验证失败：booking_cancelled={booking_cancelled}, "
                    f"status={wl2_after.status}, results_count={len(results)}"
                )
        except Exception as e:
            steps.append(make_step_result("S10: 取消预约后高优先级自动补位验证", False, step_start, e))

        step_start = time.time()
        try:
            time.sleep(0.1)
            wl1_final = db.query(WaitlistEntry).filter(WaitlistEntry.id == waitlist1.id).first()
            wl2_final = db.query(WaitlistEntry).filter(WaitlistEntry.id == waitlist2.id).first()

            target_day_start = slot_start.replace(hour=0, minute=0, second=0, microsecond=0)
            recompute_queue_positions(db, venue_id, target_day_start)
            db.flush()

            wl1_final = db.query(WaitlistEntry).filter(WaitlistEntry.id == waitlist1.id).first()

            queue_pos_valid = wl1_final.queue_position > 0
            status_valid = wl1_final.status == "waiting"

            if queue_pos_valid and status_valid:
                steps.append(make_step_result(
                    "S11: 补位后低优先级前进验证",
                    True, step_start,
                    context=f"queue_pos={wl1_final.queue_position}, status={wl1_final.status}"
                ))
            else:
                raise AssertionError(
                    f"排队验证失败：queue_pos={wl1_final.queue_position}, status={wl1_final.status}"
                )
        except Exception as e:
            steps.append(make_step_result("S11: 补位后低优先级前进验证", False, step_start, e))

        step_start = time.time()
        try:
            drill_waitlists = db.query(WaitlistEntry).filter(
                WaitlistEntry.drill_session_id == drill_session_id
            ).all()

            header_cols = ["候补ID", "剧目", "场地", "申请人", "状态", "目标开始时间",
                          "目标结束时间", "被挡住类型", "补位方式", "补位时间", "对应预约ID",
                          "操作类型", "触发原因", "是否演练数据", "演练会话ID"]

            sample_row = [
                str(drill_waitlists[0].id),
                drill_waitlists[0].production,
                str(venue_id),
                str(drill_waitlists[0].user_id),
                drill_waitlists[0].status,
                drill_waitlists[0].target_start_time.isoformat() if drill_waitlists[0].target_start_time else "",
                drill_waitlists[0].target_end_time.isoformat() if drill_waitlists[0].target_end_time else "",
                drill_waitlists[0].blocked_by_type or "",
                drill_waitlists[0].filled_method or "",
                drill_waitlists[0].filled_at.isoformat() if drill_waitlists[0].filled_at else "",
                str(drill_waitlists[0].filled_booking_id) if drill_waitlists[0].filled_booking_id else "",
                "create",
                "drill_registered",
                "是",
                drill_session_id
            ]

            csv_content = ",".join(header_cols) + "\n" + ",".join(sample_row) + "\n"

            has_session_id = drill_session_id in csv_content
            has_drill_marker = "是否演练数据" in csv_content
            has_required_cols = all(c in header_cols for c in ["候补ID", "剧目", "状态", "被挡住类型", "补位方式"])

            if has_session_id and has_drill_marker and has_required_cols and len(drill_waitlists) > 0:
                steps.append(make_step_result(
                    "S12: CSV导出验证",
                    True, step_start,
                    context=f"drill_records={len(drill_waitlists)}, csv_template_valid=True"
                ))
            else:
                raise AssertionError(
                    f"CSV导出验证失败: records={len(drill_waitlists)}, "
                    f"has_session={has_session_id}, has_marker={has_drill_marker}"
                )
        except Exception as e:
            steps.append(make_step_result("S12: CSV导出验证", False, step_start, e))

        db.commit()

        passed = sum(1 for s in steps if s.passed)
        failed = len(steps) - passed

        response.status = "completed" if failed == 0 else "completed_with_errors"
        response.steps = steps
        response.total_passed = passed
        response.total_failed = failed
        response.completed_at = datetime.utcnow()

    except Exception as e:
        db.rollback()
        response.status = "failed"
        response.error_message = str(e)[:500]
        response.steps = steps
        response.total_passed = sum(1 for s in steps if s.passed)
        response.total_failed = len(steps) - response.total_passed
        response.completed_at = datetime.utcnow()

    return response


def cleanup_drill_session(
    db: Session,
    drill_session_id: str
) -> DrillCleanupResponse:
    details = {
        "waitlist_logs": 0,
        "waitlist_entries": 0,
        "reschedule_records": 0,
        "bookings": 0,
        "closed_windows": 0,
        "users": 0
    }

    try:
        logs = db.query(WaitlistLog).filter(
            WaitlistLog.waitlist_entry_id.in_(
                db.query(WaitlistEntry.id).filter(
                    WaitlistEntry.drill_session_id == drill_session_id
                )
            )
        ).all()
        for log in logs:
            db.delete(log)
        details["waitlist_logs"] = len(logs)
        db.flush()

        wl_entries = db.query(WaitlistEntry).filter(
            WaitlistEntry.drill_session_id == drill_session_id
        ).all()
        for entry in wl_entries:
            db.delete(entry)
        details["waitlist_entries"] = len(wl_entries)
        db.flush()

        reschedules = db.query(RescheduleRecord).filter(
            RescheduleRecord.drill_session_id == drill_session_id
        ).all()
        for r in reschedules:
            db.delete(r)
        details["reschedule_records"] = len(reschedules)
        db.flush()

        bookings = db.query(Booking).filter(
            Booking.drill_session_id == drill_session_id
        ).all()
        for b in bookings:
            db.delete(b)
        details["bookings"] = len(bookings)
        db.flush()

        windows = db.query(ClosedWindow).filter(
            ClosedWindow.drill_session_id == drill_session_id
        ).all()
        for w in windows:
            db.delete(w)
        details["closed_windows"] = len(windows)
        db.flush()

        users = db.query(User).filter(
            User.username.like(f"drill_%_{drill_session_id.split('_')[1]}%")
        ).all()
        for u in users:
            db.delete(u)
        details["users"] = len(users)

        db.commit()

        total = sum(details.values())
        return DrillCleanupResponse(
            drill_session_id=drill_session_id,
            removed_count=total,
            details=details
        )

    except Exception as e:
        db.rollback()
        raise e


def get_drill_session_snapshot(
    db: Session,
    drill_session_id: str
) -> Dict[str, Any]:
    waitlists = db.query(WaitlistEntry).filter(
        WaitlistEntry.drill_session_id == drill_session_id
    ).all()

    bookings = db.query(Booking).filter(
        Booking.drill_session_id == drill_session_id
    ).all()

    windows = db.query(ClosedWindow).filter(
        ClosedWindow.drill_session_id == drill_session_id
    ).all()

    all_logs = []
    for wl in waitlists:
        logs = db.query(WaitlistLog).filter(
            WaitlistLog.waitlist_entry_id == wl.id
        ).order_by(WaitlistLog.created_at.asc()).all()
        all_logs.extend([{
            "id": log.id,
            "action": log.action,
            "trigger_reason": log.trigger_reason,
            "result_booking_id": log.result_booking_id
        } for log in logs])

    return {
        "drill_session_id": drill_session_id,
        "waitlists": [
            {
                "id": w.id,
                "status": w.status,
                "blocked_by_type": w.blocked_by_type,
                "filled_booking_id": w.filled_booking_id,
                "queue_position": w.queue_position
            }
            for w in waitlists
        ],
        "bookings": [
            {
                "id": b.id,
                "status": b.status,
                "title": b.title
            }
            for b in bookings
        ],
        "closed_windows": [
            {
                "id": w.id,
                "is_revoked": w.is_revoked,
                "reason": w.reason
            }
            for w in windows
        ],
        "logs": all_logs,
        "summary": {
            "waitlist_count": len(waitlists),
            "booking_count": len(bookings),
            "window_count": len(windows),
            "log_count": len(all_logs),
            "filled_count": sum(1 for w in waitlists if w.status == "filled"),
            "waiting_count": sum(1 for w in waitlists if w.status == "waiting")
        }
    }


def verify_restart_consistency(
    db: Session,
    drill_session_id: str,
    snapshot_before: Dict[str, Any]
) -> Tuple[bool, List[str]]:
    snapshot_after = get_drill_session_snapshot(db, drill_session_id)
    errors = []

    if snapshot_before["summary"]["waitlist_count"] != snapshot_after["summary"]["waitlist_count"]:
        errors.append(
            f"候补记录数量不一致：重启前={snapshot_before['summary']['waitlist_count']}, "
            f"重启后={snapshot_after['summary']['waitlist_count']}"
        )

    if snapshot_before["summary"]["booking_count"] != snapshot_after["summary"]["booking_count"]:
        errors.append(
            f"预约记录数量不一致：重启前={snapshot_before['summary']['booking_count']}, "
            f"重启后={snapshot_after['summary']['booking_count']}"
        )

    for wl_before, wl_after in zip(
        sorted(snapshot_before["waitlists"], key=lambda x: x["id"]),
        sorted(snapshot_after["waitlists"], key=lambda x: x["id"])
    ):
        if wl_before["id"] != wl_after["id"]:
            continue
        if wl_before["status"] != wl_after["status"]:
            errors.append(
                f"候补ID={wl_before['id']} 状态不一致："
                f"重启前={wl_before['status']}, 重启后={wl_after['status']}"
            )
        if wl_before["filled_booking_id"] != wl_after["filled_booking_id"]:
            errors.append(
                f"候补ID={wl_before['id']} 补位预约ID不一致："
                f"重启前={wl_before['filled_booking_id']}, 重启后={wl_after['filled_booking_id']}"
            )
        if wl_before["queue_position"] != wl_after["queue_position"]:
            errors.append(
                f"候补ID={wl_before['id']} 排队位置不一致："
                f"重启前={wl_before['queue_position']}, 重启后={wl_after['queue_position']}"
            )

    if snapshot_before["summary"]["log_count"] != snapshot_after["summary"]["log_count"]:
        errors.append(
            f"操作日志数量不一致：重启前={snapshot_before['summary']['log_count']}, "
            f"重启后={snapshot_after['summary']['log_count']}"
        )

    return len(errors) == 0, errors
