from fastapi import APIRouter, Depends, HTTPException, status, Query
from sqlalchemy.orm import Session
from typing import List, Optional
from datetime import datetime, timedelta

from database import get_db, WaitlistEntry, WaitlistLog, User, Venue, Booking
from auth import get_current_user, get_current_admin
from schemas import (
    WaitlistCreate, WaitlistCancel, WaitlistFillRequest,
    WaitlistResponse, WaitlistLogResponse, WaitlistListResponse,
    WaitlistFillResult
)
from conflict_detector import validate_new_booking
from waitlist_service import (
    recompute_queue_positions, detect_blocked_by, is_duplicate_waiting,
    fill_waitlist_entry, expire_stale_waitlists, log_waitlist_action,
    ACTIVE_WAITLIST_STATUSES, WAITLIST_VALID_STATUSES
)

router = APIRouter()


def waitlist_to_response(db: Session, entry: WaitlistEntry) -> WaitlistResponse:
    user_name = entry.user.full_name if entry.user else None
    venue_name = entry.venue.name if entry.venue else None
    cancelled_by_name = entry.canceller.full_name if entry.canceller else None

    return WaitlistResponse(
        id=entry.id,
        venue_id=entry.venue_id,
        venue_name=venue_name,
        title=entry.title,
        production=entry.production,
        user_id=entry.user_id,
        user_name=user_name,
        target_start_time=entry.target_start_time,
        target_end_time=entry.target_end_time,
        float_before_minutes=entry.float_before_minutes,
        float_after_minutes=entry.float_after_minutes,
        notes=entry.notes or "",
        priority=entry.priority,
        status=entry.status,
        queue_position=entry.queue_position,
        blocked_by_type=entry.blocked_by_type or "",
        filled_booking_id=entry.filled_booking_id,
        filled_at=entry.filled_at,
        filled_method=entry.filled_method,
        cancelled_by=entry.cancelled_by,
        cancelled_by_name=cancelled_by_name,
        cancelled_at=entry.cancelled_at,
        cancel_reason=entry.cancel_reason or "",
        expires_at=entry.expires_at,
        created_at=entry.created_at,
        updated_at=entry.updated_at
    )


@router.get("", response_model=WaitlistListResponse)
def list_waitlists(
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
    is_admin = current_user.role == "admin"

    expire_stale_waitlists(db)
    db.commit()

    query = db.query(WaitlistEntry)

    if production:
        query = query.filter(WaitlistEntry.production.like(f"%{production}%"))
    if venue_id:
        query = query.filter(WaitlistEntry.venue_id == venue_id)
    if status:
        status_list = [s.strip() for s in status.split(",") if s.strip()]
        if status_list:
            query = query.filter(WaitlistEntry.status.in_(status_list))
    if user_id:
        query = query.filter(WaitlistEntry.user_id == user_id)

    if not is_admin:
        query = query.filter(WaitlistEntry.user_id == current_user.id)

    if start_date:
        query = query.filter(WaitlistEntry.target_start_time >= datetime.fromisoformat(start_date))
    if end_date:
        query = query.filter(WaitlistEntry.target_start_time <= datetime.fromisoformat(end_date))

    total = query.count()
    items = query.order_by(
        WaitlistEntry.status.asc(),
        WaitlistEntry.venue_id.asc(),
        WaitlistEntry.target_start_time.asc(),
        WaitlistEntry.queue_position.asc(),
        WaitlistEntry.created_at.desc()
    ).offset((page - 1) * page_size).limit(page_size).all()

    return WaitlistListResponse(
        items=[waitlist_to_response(db, e) for e in items],
        total=total,
        page=page,
        page_size=page_size
    )


@router.get("/{waitlist_id}", response_model=WaitlistResponse)
def get_waitlist(
    waitlist_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    entry = db.query(WaitlistEntry).filter(WaitlistEntry.id == waitlist_id).first()
    if not entry:
        raise HTTPException(status_code=404, detail="候补记录不存在")

    is_admin = current_user.role == "admin"
    if not is_admin and entry.user_id != current_user.id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="只能查看自己的候补记录"
        )

    return waitlist_to_response(db, entry)


@router.post("", response_model=WaitlistResponse)
def create_waitlist(
    data: WaitlistCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    if data.target_start_time >= data.target_end_time:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="结束时间必须晚于开始时间"
        )

    if data.float_before_minutes < 0 or data.float_after_minutes < 0:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="浮动时间不能为负数"
        )

    venue = db.query(Venue).filter(Venue.id == data.venue_id, Venue.is_active == True).first()
    if not venue:
        raise HTTPException(status_code=404, detail="场地不存在或未启用")

    expire_stale_waitlists(db)

    if is_duplicate_waiting(
        db, current_user.id, data.venue_id,
        data.target_start_time, data.target_end_time
    ):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="您在同一时段已有排队中的候补记录，请勿重复登记"
        )

    validation = validate_new_booking(db, data.venue_id, data.target_start_time, data.target_end_time)
    if validation["valid"]:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="该时段目前可以直接预约，无需候补"
        )

    blocked_info = detect_blocked_by(db, data.venue_id, data.target_start_time, data.target_end_time)

    expires_at = data.target_end_time + timedelta(hours=24)

    entry = WaitlistEntry(
        user_id=current_user.id,
        venue_id=data.venue_id,
        title=data.title,
        production=data.production,
        target_start_time=data.target_start_time,
        target_end_time=data.target_end_time,
        float_before_minutes=data.float_before_minutes,
        float_after_minutes=data.float_after_minutes,
        notes=data.notes,
        priority=data.priority,
        status="waiting",
        blocked_by_type=blocked_info["blocked_by_type"],
        blocked_by_details=blocked_info["blocked_by_details"],
        expires_at=expires_at
    )
    db.add(entry)
    db.flush()

    target_day_start = data.target_start_time.replace(
        hour=0, minute=0, second=0, microsecond=0
    )
    recompute_queue_positions(db, data.venue_id, target_day_start)

    log_waitlist_action(
        db, entry.id, action="create",
        trigger_reason="user_registered",
        operator_id=current_user.id,
        blocked_snapshot=blocked_info["blocked_by_details"],
        notes=f"登记候补：{data.title}（{data.production}）"
    )

    db.commit()
    db.refresh(entry)

    return waitlist_to_response(db, entry)


@router.delete("/{waitlist_id}", response_model=WaitlistResponse)
def cancel_waitlist(
    waitlist_id: int,
    cancel_data: Optional[WaitlistCancel] = None,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    entry = db.query(WaitlistEntry).filter(WaitlistEntry.id == waitlist_id).first()
    if not entry:
        raise HTTPException(status_code=404, detail="候补记录不存在")

    is_admin = current_user.role == "admin"
    is_owner = entry.user_id == current_user.id

    if not is_admin and not is_owner:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="只能取消自己的候补记录"
        )

    if entry.status != "waiting":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"当前状态为 {entry.status}，不能取消"
        )

    entry.status = "cancelled"
    entry.cancelled_by = current_user.id
    entry.cancelled_at = datetime.utcnow()
    entry.cancel_reason = (cancel_data.cancel_reason if cancel_data else "") or ""

    log_waitlist_action(
        db, entry.id, action="cancel",
        trigger_reason="manual_cancel",
        operator_id=current_user.id,
        notes=entry.cancel_reason or "用户主动取消候补"
    )

    target_day_start = entry.target_start_time.replace(
        hour=0, minute=0, second=0, microsecond=0
    )
    recompute_queue_positions(db, entry.venue_id, target_day_start, exclude_entry_id=entry.id)

    db.commit()
    db.refresh(entry)

    return waitlist_to_response(db, entry)


@router.post("/{waitlist_id}/fill", response_model=WaitlistFillResult)
def admin_fill_waitlist(
    waitlist_id: int,
    fill_req: WaitlistFillRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_admin)
):
    entry = db.query(WaitlistEntry).filter(WaitlistEntry.id == waitlist_id).first()
    if not entry:
        raise HTTPException(status_code=404, detail="候补记录不存在")

    result = fill_waitlist_entry(
        db,
        entry,
        fill_method="manual",
        trigger_reason="manual_fill",
        operator_id=current_user.id,
        use_target_time=fill_req.use_target_time,
        notes=fill_req.notes
    )

    db.commit()
    return result


@router.get("/{waitlist_id}/logs", response_model=List[WaitlistLogResponse])
def get_waitlist_logs(
    waitlist_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    entry = db.query(WaitlistEntry).filter(WaitlistEntry.id == waitlist_id).first()
    if not entry:
        raise HTTPException(status_code=404, detail="候补记录不存在")

    is_admin = current_user.role == "admin"
    if not is_admin and entry.user_id != current_user.id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="只能查看自己候补记录的日志"
        )

    logs = db.query(WaitlistLog).filter(
        WaitlistLog.waitlist_entry_id == waitlist_id
    ).order_by(WaitlistLog.created_at.desc()).all()

    result = []
    for log in logs:
        operator_name = log.operator.full_name if log.operator else None
        result.append(WaitlistLogResponse(
            id=log.id,
            waitlist_entry_id=log.waitlist_entry_id,
            operator_id=log.operator_id,
            operator_name=operator_name,
            action=log.action,
            trigger_reason=log.trigger_reason or "",
            result_booking_id=log.result_booking_id,
            notes=log.notes or "",
            created_at=log.created_at
        ))
    return result


@router.post("/cleanup-expired")
def admin_cleanup_expired(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_admin)
):
    count = expire_stale_waitlists(db)
    db.commit()
    return {"expired_count": count, "message": f"已清理 {count} 条过期候补"}
