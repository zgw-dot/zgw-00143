from datetime import datetime, date
from sqlalchemy.orm import Session
from typing import List, Optional

from database import Booking, ClosedDate, Venue
from schemas import ConflictInfo


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

    from datetime import timedelta
    while current <= end_date:
        for cd in all_closed:
            if cd.date == current:
                closed_dates.append(current)
                break
        current += timedelta(days=1)

    return closed_dates


def validate_booking_version(db: Session, booking: Booking) -> dict:
    result = {
        "valid": True,
        "conflicts": [],
        "closed_dates": []
    }

    conflicts = find_conflicting_bookings(
        db,
        booking.venue_id,
        booking.start_time,
        booking.end_time,
        exclude_booking_id=booking.id if hasattr(booking, 'id') and booking.id else None
    )

    if conflicts:
        result["valid"] = False
        result["conflicts"] = find_conflicts_to_info(db, conflicts)

    closed = is_closed_date(db, booking.venue_id, booking.start_time, booking.end_time)
    if closed:
        result["valid"] = False
        result["closed_dates"] = [d.isoformat() for d in closed]

    return result


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
        "closed_dates": []
    }

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
