from datetime import datetime, timedelta
from sqlalchemy.orm import Session
from typing import List, Optional, Dict, Any
import json

from database import WaitlistEntry, WaitlistLog, Booking, User, Venue
from conflict_detector import (
    validate_new_booking, find_conflicting_bookings, find_closed_windows,
    find_conflicts_to_info, closed_windows_to_info, check_time_overlap
)
from schemas import WaitlistFillResult


WAITLIST_VALID_STATUSES = ["waiting", "filled", "cancelled", "expired"]
ACTIVE_WAITLIST_STATUSES = ["waiting"]


def recompute_queue_positions(
    db: Session,
    venue_id: int,
    target_date_start: datetime,
    exclude_entry_id: Optional[int] = None
) -> None:
    date_end = target_date_start + timedelta(days=1)
    query = db.query(WaitlistEntry).filter(
        WaitlistEntry.venue_id == venue_id,
        WaitlistEntry.target_start_time >= target_date_start,
        WaitlistEntry.target_start_time < date_end,
        WaitlistEntry.status.in_(ACTIVE_WAITLIST_STATUSES)
    )
    if exclude_entry_id:
        query = query.filter(WaitlistEntry.id != exclude_entry_id)

    entries = query.order_by(
        WaitlistEntry.priority.desc(),
        WaitlistEntry.created_at.asc(),
        WaitlistEntry.id.asc()
    ).all()

    for idx, entry in enumerate(entries, 1):
        entry.queue_position = idx
    db.flush()


def detect_blocked_by(
    db: Session,
    venue_id: int,
    start_time: datetime,
    end_time: datetime
) -> Dict[str, Any]:
    conflicts = find_conflicting_bookings(db, venue_id, start_time, end_time)
    closed_windows = find_closed_windows(db, venue_id, start_time, end_time)

    blocked_type = ""
    if conflicts and closed_windows:
        blocked_type = "both"
    elif conflicts:
        blocked_type = "booking"
    elif closed_windows:
        blocked_type = "closed_window"

    details = {
        "conflicts": [
            {
                "booking_id": b.id,
                "title": b.title,
                "user_name": b.user.full_name if b.user else "",
                "start_time": b.start_time.isoformat(),
                "end_time": b.end_time.isoformat()
            }
            for b in conflicts
        ],
        "closed_windows": [
            {
                "window_id": w.id,
                "reason": w.reason or "封场",
                "start_time": w.start_time.isoformat(),
                "end_time": w.end_time.isoformat()
            }
            for w in closed_windows
        ]
    }

    return {
        "blocked_by_type": blocked_type,
        "blocked_by_details": json.dumps(details, ensure_ascii=False)
    }


def is_duplicate_waiting(
    db: Session,
    user_id: int,
    venue_id: int,
    target_start_time: datetime,
    target_end_time: datetime,
    exclude_entry_id: Optional[int] = None
) -> bool:
    query = db.query(WaitlistEntry).filter(
        WaitlistEntry.user_id == user_id,
        WaitlistEntry.venue_id == venue_id,
        WaitlistEntry.status.in_(ACTIVE_WAITLIST_STATUSES)
    )
    if exclude_entry_id:
        query = query.filter(WaitlistEntry.id != exclude_entry_id)

    entries = query.all()
    for entry in entries:
        if check_time_overlap(
            target_start_time, target_end_time,
            entry.target_start_time, entry.target_end_time
        ):
            return True
    return False


def find_matching_waitlist_entries(
    db: Session,
    venue_id: int,
    available_start: datetime,
    available_end: datetime
) -> List[WaitlistEntry]:
    query = db.query(WaitlistEntry).filter(
        WaitlistEntry.venue_id == venue_id,
        WaitlistEntry.status == "waiting"
    )
    candidates = query.all()

    matches = []
    for entry in candidates:
        if entry.expires_at and entry.expires_at < datetime.utcnow():
            continue

        flex_start = entry.target_start_time - timedelta(minutes=entry.float_before_minutes)
        flex_end = entry.target_end_time + timedelta(minutes=entry.float_after_minutes)

        window_start = max(flex_start, available_start)
        window_end = min(flex_end, available_end)

        needed_duration = entry.target_end_time - entry.target_start_time
        available_duration = window_end - window_start

        if available_duration >= needed_duration:
            matches.append(entry)

    matches.sort(key=lambda e: (-e.priority, e.created_at, e.id))
    return matches


def build_booking_times_for_fill(
    entry: WaitlistEntry,
    available_start: datetime,
    available_end: datetime
) -> tuple[datetime, datetime]:
    flex_start = entry.target_start_time - timedelta(minutes=entry.float_before_minutes)
    flex_end = entry.target_end_time + timedelta(minutes=entry.float_after_minutes)

    candidate_start = max(flex_start, available_start)
    candidate_end = min(
        candidate_start + (entry.target_end_time - entry.target_start_time),
        available_end, flex_end
    )
    return candidate_start, candidate_end


def fill_waitlist_entry(
    db: Session,
    entry: WaitlistEntry,
    fill_method: str,
    trigger_reason: str,
    operator_id: Optional[int],
    available_start: Optional[datetime] = None,
    available_end: Optional[datetime] = None,
    use_target_time: bool = False,
    notes: str = ""
) -> WaitlistFillResult:
    if entry.status != "waiting":
        return WaitlistFillResult(
            success=False,
            waitlist_id=entry.id,
            status=entry.status,
            message=f"候补状态为{entry.status}，不能补位"
        )

    if use_target_time or (available_start is None or available_end is None):
        booking_start = entry.target_start_time
        booking_end = entry.target_end_time
    else:
        booking_start, booking_end = build_booking_times_for_fill(
            entry, available_start, available_end
        )

    validation = validate_new_booking(db, entry.venue_id, booking_start, booking_end)
    if not validation["valid"]:
        conflict_parts = []
        if validation.get("conflicts"):
            conflict_parts.append("存在预约冲突")
        if validation.get("closed_windows"):
            conflict_parts.append("存在封场")
        if validation.get("closed_dates"):
            conflict_parts.append("落在封场日")
        if validation.get("open_slot_violations"):
            conflict_parts.append("不在开放时段")
        return WaitlistFillResult(
            success=False,
            waitlist_id=entry.id,
            status=entry.status,
            message=f"补位失败：{'；'.join(conflict_parts)}"
        )

    blocked_snapshot = entry.blocked_by_details or "{}"

    db_booking = Booking(
        title=entry.title,
        production=entry.production,
        venue_id=entry.venue_id,
        user_id=entry.user_id,
        status="draft",
        start_time=booking_start,
        end_time=booking_end,
        priority=entry.priority,
        notes=(entry.notes or "") + (
            f"\n\n[候补补位] 触发：{trigger_reason}；方式：{fill_method}"
            + (f"；备注：{notes}" if notes else "")
        ),
        version=1
    )
    db.add(db_booking)
    db.flush()

    entry.status = "filled"
    entry.filled_booking_id = db_booking.id
    entry.filled_at = datetime.utcnow()
    entry.filled_method = fill_method

    log = WaitlistLog(
        waitlist_entry_id=entry.id,
        operator_id=operator_id,
        action="fill",
        trigger_reason=trigger_reason,
        blocked_by_snapshot=blocked_snapshot,
        result_booking_id=db_booking.id,
        notes=notes
    )
    db.add(log)

    target_day_start = entry.target_start_time.replace(
        hour=0, minute=0, second=0, microsecond=0
    )
    recompute_queue_positions(db, entry.venue_id, target_day_start, exclude_entry_id=entry.id)

    return WaitlistFillResult(
        success=True,
        waitlist_id=entry.id,
        booking_id=db_booking.id,
        status="filled",
        message=f"已生成草稿预约（ID: {db_booking.id}）"
    )


def try_auto_fill_on_slot_release(
    db: Session,
    venue_id: int,
    available_start: datetime,
    available_end: datetime,
    trigger_reason: str,
    operator_id: Optional[int] = None
) -> List[WaitlistFillResult]:
    results = []

    remaining_start = available_start
    remaining_end = available_end

    while True:
        matches = find_matching_waitlist_entries(db, venue_id, remaining_start, remaining_end)
        if not matches:
            break

        filled_one = False
        for entry in matches:
            result = fill_waitlist_entry(
                db,
                entry,
                fill_method="auto",
                trigger_reason=trigger_reason,
                operator_id=operator_id,
                available_start=remaining_start,
                available_end=remaining_end
            )
            if result.success and result.booking_id:
                booking = db.query(Booking).filter(Booking.id == result.booking_id).first()
                if booking:
                    if booking.start_time <= remaining_start:
                        remaining_start = max(remaining_start, booking.end_time)
                    elif booking.end_time >= remaining_end:
                        remaining_end = min(remaining_end, booking.start_time)
                    else:
                        remaining_start = booking.end_time
                filled_one = True
                results.append(result)
                break
            else:
                results.append(result)

        if not filled_one:
            break

        if remaining_start >= remaining_end:
            break

    return results


def expire_stale_waitlists(db: Session) -> int:
    now = datetime.utcnow()
    expired_entries = db.query(WaitlistEntry).filter(
        WaitlistEntry.status == "waiting",
        WaitlistEntry.target_end_time < now - timedelta(hours=24)
    ).all()

    count = 0
    for entry in expired_entries:
        entry.status = "expired"
        log = WaitlistLog(
            waitlist_entry_id=entry.id,
            operator_id=None,
            action="expire",
            trigger_reason="auto_expire",
            notes="目标时段已过，候补自动过期"
        )
        db.add(log)
        count += 1

    if count > 0:
        db.flush()
    return count


def log_waitlist_action(
    db: Session,
    waitlist_entry_id: int,
    action: str,
    trigger_reason: str = "",
    operator_id: Optional[int] = None,
    result_booking_id: Optional[int] = None,
    blocked_snapshot: str = "",
    notes: str = ""
) -> WaitlistLog:
    log = WaitlistLog(
        waitlist_entry_id=waitlist_entry_id,
        operator_id=operator_id,
        action=action,
        trigger_reason=trigger_reason,
        blocked_by_snapshot=blocked_snapshot,
        result_booking_id=result_booking_id,
        notes=notes
    )
    db.add(log)
    db.flush()
    return log
