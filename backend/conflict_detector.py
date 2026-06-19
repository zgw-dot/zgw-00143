from datetime import datetime, date, time, timedelta
from sqlalchemy.orm import Session
from typing import List, Optional, Dict, Any

from database import Booking, ClosedDate, Venue, OpenSlot
from schemas import ConflictInfo


DAY_NAMES = ["周一", "周二", "周三", "周四", "周五", "周六", "周日"]


def check_time_overlap(
    start1: datetime,
    end1: datetime,
    start2: datetime,
    end2: datetime
) -> bool:
    return start1 < end2 and start2 < end1


def find_conflicting_bookings(
    db: Session,
    venue_id: int,
    start_time: datetime,
    end_time: datetime,
    exclude_booking_id: Optional[int] = None,
    include_draft: bool = False
) -> List[Booking]:
    query = db.query(Booking).filter(
        Booking.venue_id == venue_id,
        Booking.status != "cancelled"
    )

    if not include_draft:
        query = query.filter(Booking.status != "draft")

    if exclude_booking_id:
        query = query.filter(Booking.id != exclude_booking_id)

    bookings = query.all()
    conflicts = []

    for booking in bookings:
        if check_time_overlap(start_time, end_time, booking.start_time, booking.end_time):
            conflicts.append(booking)

    return conflicts


def find_conflicts_to_info(db: Session, bookings: List[Booking]) -> List[ConflictInfo]:
    result = []
    for b in bookings:
        user_name = b.user.full_name if b.user else "Unknown"
        venue_name = b.venue.name if b.venue else "Unknown"
        result.append(ConflictInfo(
            booking_id=b.id,
            title=b.title,
            production=b.production,
            start_time=b.start_time,
            end_time=b.end_time,
            user_name=user_name,
            venue_name=venue_name
        ))
    return result


def is_closed_date(
    db: Session,
    venue_id: int,
    start_time: datetime,
    end_time: datetime
) -> List[date]:
    closed_dates = []

    all_venue_closed = db.query(ClosedDate).filter(
        ClosedDate.venue_id.is_(None)
    ).all()

    venue_closed = db.query(ClosedDate).filter(
        ClosedDate.venue_id == venue_id
    ).all()

    all_closed = all_venue_closed + venue_closed

    current = start_time.date()
    end_date = end_time.date()

    while current <= end_date:
        for cd in all_closed:
            if cd.date == current:
                closed_dates.append(current)
                break
        current += timedelta(days=1)

    return closed_dates


def check_open_slots(
    db: Session,
    venue_id: int,
    start_time: datetime,
    end_time: datetime
) -> List[Dict[str, Any]]:
    violations = []

    open_slots = db.query(OpenSlot).filter(
        OpenSlot.venue_id == venue_id
    ).all()

    if not open_slots:
        violations.append({
            "date": start_time.date().isoformat(),
            "day_of_week": start_time.weekday(),
            "day_name": DAY_NAMES[start_time.weekday()],
            "requested_range": f"{start_time.strftime('%H:%M')}-{end_time.strftime('%H:%M')}",
            "available_slots": [],
            "reason": f"场地未配置任何开放时段"
        })
        return violations

    current_date = start_time.date()
    end_date = end_time.date()

    while current_date <= end_date:
        day_of_week = current_date.weekday()

        if current_date == start_time.date() and current_date == end_time.date():
            day_start = start_time.time()
            day_end = end_time.time()
        elif current_date == start_time.date():
            day_start = start_time.time()
            day_end = time(23, 59, 59)
        elif current_date == end_time.date():
            day_start = time(0, 0, 0)
            day_end = end_time.time()
        else:
            day_start = time(0, 0, 0)
            day_end = time(23, 59, 59)

        day_slots = [s for s in open_slots if s.day_of_week == day_of_week]

        fully_covered = False
        for slot in day_slots:
            slot_start = slot.start_time
            slot_end = slot.end_time
            if day_start >= slot_start and day_end <= slot_end:
                fully_covered = True
                break

        if not fully_covered:
            available = []
            for s in day_slots:
                available.append(f"{s.start_time.strftime('%H:%M')}-{s.end_time.strftime('%H:%M')}")

            requested_range = f"{day_start.strftime('%H:%M')}-{day_end.strftime('%H:%M')}"
            reason = (
                f"{DAY_NAMES[day_of_week]} {requested_range} "
                f"不在开放时段内"
            )
            if available:
                reason += f"（可预约时段：{', '.join(available)}）"
            else:
                reason += "（该日无开放时段）"

            violations.append({
                "date": current_date.isoformat(),
                "day_of_week": day_of_week,
                "day_name": DAY_NAMES[day_of_week],
                "requested_range": requested_range,
                "available_slots": available,
                "reason": reason
            })

        current_date += timedelta(days=1)

    return violations


def validate_new_booking(
    db: Session,
    venue_id: int,
    start_time: datetime,
    end_time: datetime,
    exclude_booking_id: Optional[int] = None
) -> dict:
    result = {
        "valid": True,
        "conflicts": [],
        "closed_dates": [],
        "open_slot_violations": []
    }

    open_slot_violations = check_open_slots(db, venue_id, start_time, end_time)
    if open_slot_violations:
        result["valid"] = False
        result["open_slot_violations"] = open_slot_violations

    conflicts = find_conflicting_bookings(
        db, venue_id, start_time, end_time,
        exclude_booking_id=exclude_booking_id
    )

    if conflicts:
        result["valid"] = False
        result["conflicts"] = find_conflicts_to_info(db, conflicts)

    closed = is_closed_date(db, venue_id, start_time, end_time)
    if closed:
        result["valid"] = False
        result["closed_dates"] = [d.isoformat() for d in closed]

    return result
