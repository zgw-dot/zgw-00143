from fastapi import APIRouter, Depends, HTTPException, status, Query
from sqlalchemy.orm import Session
from typing import List, Optional
from datetime import datetime, timedelta

from database import get_db, Booking, RescheduleRecord, User
from auth import get_current_user, get_current_admin
from schemas import (
    BookingCreate, BookingUpdate, BookingResponse,
    BookingStatusUpdate, RescheduleRequest,
    RescheduleRecordResponse, ConflictInfo, BookingListResponse
)
from conflict_detector import validate_new_booking, find_conflicting_bookings, find_conflicts_to_info

router = APIRouter()

VALID_STATUSES = ["draft", "pending", "confirmed", "rescheduling", "cancelled"]
FINAL_STATUSES = ["confirmed", "cancelled"]


def raise_validation_error(validation: dict, message: str = "预约校验失败"):
    detail = {"message": message}
    if validation.get("conflicts"):
        detail["conflicts"] = [c.model_dump(mode='json') for c in validation["conflicts"]]
    if validation.get("closed_dates"):
        detail["closed_dates"] = validation["closed_dates"]
    if validation.get("open_slot_violations"):
        detail["open_slot_violations"] = validation["open_slot_violations"]
        reasons = [v["reason"] for v in validation["open_slot_violations"]]
        detail["message"] = "；".join(reasons)
    raise HTTPException(
        status_code=status.HTTP_409_CONFLICT,
        detail=detail
    )


def booking_to_response(db: Session, booking: Booking, include_conflicts: bool = False) -> BookingResponse:
    user_name = booking.user.full_name if booking.user else None
    venue_name = booking.venue.name if booking.venue else None
    approver_name = booking.approver.full_name if booking.approver else None

    conflicts = None
    if include_conflicts and booking.status in ["pending", "confirmed"]:
        conflict_bookings = find_conflicting_bookings(
            db, booking.venue_id, booking.start_time, booking.end_time,
            exclude_booking_id=booking.id
        )
        conflicts = find_conflicts_to_info(db, conflict_bookings)

    return BookingResponse(
        id=booking.id,
        version=booking.version,
        title=booking.title,
        production=booking.production,
        venue_id=booking.venue_id,
        venue_name=venue_name,
        user_id=booking.user_id,
        user_name=user_name,
        status=booking.status,
        start_time=booking.start_time,
        end_time=booking.end_time,
        priority=booking.priority,
        notes=booking.notes,
        rejection_reason=booking.rejection_reason,
        approver_id=booking.approver_id,
        approver_name=approver_name,
        approved_at=booking.approved_at,
        created_at=booking.created_at,
        updated_at=booking.updated_at,
        conflicts=conflicts
    )


@router.get("", response_model=BookingListResponse)
def list_bookings(
    production: Optional[str] = None,
    venue_id: Optional[int] = None,
    status: Optional[str] = None,
    user_id: Optional[int] = None,
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=200),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    query = db.query(Booking)

    if production:
        query = query.filter(Booking.production.like(f"%{production}%"))
    if venue_id:
        query = query.filter(Booking.venue_id == venue_id)
    if status:
        status_list = [s.strip() for s in status.split(",") if s.strip()]
        if status_list:
            query = query.filter(Booking.status.in_(status_list))
    if user_id:
        query = query.filter(Booking.user_id == user_id)
    if start_date:
        query = query.filter(Booking.start_time >= datetime.fromisoformat(start_date))
    if end_date:
        query = query.filter(Booking.start_time <= datetime.fromisoformat(end_date))

    total = query.count()
    items = query.order_by(Booking.start_time.desc()).offset((page - 1) * page_size).limit(page_size).all()

    return BookingListResponse(
        items=[booking_to_response(db, b) for b in items],
        total=total,
        page=page,
        page_size=page_size
    )


@router.get("/{booking_id}", response_model=BookingResponse)
def get_booking(
    booking_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    booking = db.query(Booking).filter(Booking.id == booking_id).first()
    if not booking:
        raise HTTPException(status_code=404, detail="预约不存在")
    return booking_to_response(db, booking, include_conflicts=True)


@router.post("/check-conflicts")
def check_conflicts(
    venue_id: int,
    start_time: datetime,
    end_time: datetime,
    exclude_booking_id: Optional[int] = None,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    result = validate_new_booking(db, venue_id, start_time, end_time, exclude_booking_id)
    return result


@router.post("", response_model=BookingResponse)
def create_booking(
    booking: BookingCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    if booking.status not in ["draft", "pending"]:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="新建预约只能是草稿或待审状态"
        )

    if booking.start_time >= booking.end_time:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="结束时间必须晚于开始时间"
        )

    validation = validate_new_booking(db, booking.venue_id, booking.start_time, booking.end_time)
    if not validation["valid"]:
        raise_validation_error(validation, "预约存在冲突")

    db_booking = Booking(
        **booking.model_dump(exclude={"status"}),
        status=booking.status,
        user_id=current_user.id,
        version=1
    )
    db.add(db_booking)
    db.commit()
    db.refresh(db_booking)

    return booking_to_response(db, db_booking)


@router.put("/{booking_id}", response_model=BookingResponse)
def update_booking(
    booking_id: int,
    booking_update: BookingUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    booking = db.query(Booking).filter(Booking.id == booking_id).first()
    if not booking:
        raise HTTPException(status_code=404, detail="预约不存在")

    if booking.version != booking_update.version:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "message": "版本冲突：预约已被其他人更新",
                "current_version": booking.version,
                "your_version": booking_update.version
            }
        )

    is_admin = current_user.role == "admin"
    is_owner = booking.user_id == current_user.id

    if not is_admin and not is_owner:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="只能修改自己的预约"
        )

    if booking.status == "confirmed" and not is_admin:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="已确认的预约需要管理员才能修改"
        )

    if booking.status == "cancelled":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="已取消的预约不能修改"
        )

    venue_id = booking_update.venue_id if booking_update.venue_id is not None else booking.venue_id
    start_time = booking_update.start_time if booking_update.start_time is not None else booking.start_time
    end_time = booking_update.end_time if booking_update.end_time is not None else booking.end_time

    if start_time >= end_time:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="结束时间必须晚于开始时间"
        )

    validation = validate_new_booking(db, venue_id, start_time, end_time, exclude_booking_id=booking_id)
    if not validation["valid"]:
        raise_validation_error(validation, "预约存在冲突")

    update_data = booking_update.model_dump(exclude_unset=True, exclude={"version"})
    for key, value in update_data.items():
        setattr(booking, key, value)

    booking.version += 1
    db.commit()
    db.refresh(booking)

    return booking_to_response(db, booking)


@router.patch("/{booking_id}/status", response_model=BookingResponse)
def update_booking_status(
    booking_id: int,
    status_update: BookingStatusUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    booking = db.query(Booking).filter(Booking.id == booking_id).first()
    if not booking:
        raise HTTPException(status_code=404, detail="预约不存在")

    if booking.version != status_update.version:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "message": "版本冲突：预约已被其他人更新",
                "current_version": booking.version,
                "your_version": status_update.version
            }
        )

    new_status = status_update.status
    if new_status not in VALID_STATUSES:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"无效的状态：{new_status}"
        )

    is_admin = current_user.role == "admin"
    is_owner = booking.user_id == current_user.id

    if not is_admin and not is_owner:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="无权修改此预约状态"
        )

    if new_status == "confirmed" and not is_admin:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="只有管理员可以确认预约"
        )

    if new_status == "cancelled":
        if not is_admin and not is_owner:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="只能取消自己的预约"
            )

    if new_status == "pending" and not is_admin and booking.user_id != current_user.id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="不能替别人提交审批"
        )

    if new_status == "pending":
        validation = validate_new_booking(
            db, booking.venue_id, booking.start_time, booking.end_time,
            exclude_booking_id=booking_id
        )
        if not validation["valid"]:
            raise_validation_error(validation, "提交前检测到冲突")

    if new_status == "confirmed":
        validation = validate_new_booking(
            db, booking.venue_id, booking.start_time, booking.end_time,
            exclude_booking_id=booking_id
        )
        if not validation["valid"]:
            raise_validation_error(validation, "确认前检测到冲突")
        booking.approver_id = current_user.id
        booking.approved_at = datetime.utcnow()

    if new_status == "cancelled":
        if status_update.rejection_reason:
            booking.rejection_reason = status_update.rejection_reason

    booking.status = new_status
    booking.version += 1
    db.commit()
    db.refresh(booking)

    return booking_to_response(db, booking)


@router.post("/{booking_id}/reschedule", response_model=BookingResponse)
def reschedule_booking(
    booking_id: int,
    reschedule: RescheduleRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    booking = db.query(Booking).filter(Booking.id == booking_id).first()
    if not booking:
        raise HTTPException(status_code=404, detail="预约不存在")

    if booking.version != reschedule.version:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "message": "版本冲突：预约已被其他人更新",
                "current_version": booking.version,
                "your_version": reschedule.version
            }
        )

    is_admin = current_user.role == "admin"
    is_owner = booking.user_id == current_user.id

    if not is_admin and not is_owner:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="无权改期此预约"
        )

    if booking.status == "cancelled":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="已取消的预约不能改期"
        )

    if reschedule.new_start_time >= reschedule.new_end_time:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="新结束时间必须晚于新开始时间"
        )

    validation = validate_new_booking(
        db, booking.venue_id,
        reschedule.new_start_time, reschedule.new_end_time,
        exclude_booking_id=booking_id
    )
    if not validation["valid"]:
        raise_validation_error(validation, "新时段存在冲突")

    record = RescheduleRecord(
        booking_id=booking.id,
        operator_id=current_user.id,
        original_start_time=booking.start_time,
        original_end_time=booking.end_time,
        new_start_time=reschedule.new_start_time,
        new_end_time=reschedule.new_end_time,
        reason=reschedule.reason
    )
    db.add(record)

    original_start = booking.start_time
    original_end = booking.end_time
    booking.start_time = reschedule.new_start_time
    booking.end_time = reschedule.new_end_time
    booking.status = "rescheduling"
    booking.rejection_reason = ""
    booking.approver_id = None
    booking.approved_at = None
    booking.version += 1

    db.commit()
    db.refresh(booking)

    return booking_to_response(db, booking)


@router.get("/{booking_id}/reschedule-history", response_model=List[RescheduleRecordResponse])
def get_reschedule_history(
    booking_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    booking = db.query(Booking).filter(Booking.id == booking_id).first()
    if not booking:
        raise HTTPException(status_code=404, detail="预约不存在")

    records = db.query(RescheduleRecord).filter(
        RescheduleRecord.booking_id == booking_id
    ).order_by(RescheduleRecord.created_at.desc()).all()

    result = []
    for r in records:
        operator_name = r.operator.full_name if r.operator else None
        result.append(RescheduleRecordResponse(
            id=r.id,
            booking_id=r.booking_id,
            operator_id=r.operator_id,
            operator_name=operator_name,
            original_start_time=r.original_start_time,
            original_end_time=r.original_end_time,
            new_start_time=r.new_start_time,
            new_end_time=r.new_end_time,
            reason=r.reason,
            created_at=r.created_at
        ))

    return result


@router.get("/productions/list")
def list_productions(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    productions = db.query(Booking.production).distinct().all()
    return [p[0] for p in productions if p[0]]
