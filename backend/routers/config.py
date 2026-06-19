from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session
from typing import List, Optional
from datetime import datetime

from database import get_db, OpenSlot, ClosedDate, PriorityRule, ClosedWindow, Venue
from auth import get_current_user, get_current_admin
from schemas import (
    OpenSlotCreate, OpenSlotResponse,
    ClosedDateCreate, ClosedDateResponse,
    PriorityRuleCreate, PriorityRuleResponse,
    ClosedWindowCreate, ClosedWindowResponse
)
from conflict_detector import has_overlapping_closed_window

router = APIRouter()


@router.get("/open-slots", response_model=List[OpenSlotResponse])
def list_open_slots(
    venue_id: Optional[int] = None,
    db: Session = Depends(get_db),
    current_user = Depends(get_current_user)
):
    query = db.query(OpenSlot)
    if venue_id:
        query = query.filter(OpenSlot.venue_id == venue_id)
    return query.order_by(OpenSlot.venue_id, OpenSlot.day_of_week).all()


@router.post("/open-slots", response_model=OpenSlotResponse)
def create_open_slot(
    slot: OpenSlotCreate,
    db: Session = Depends(get_db),
    current_user = Depends(get_current_admin)
):
    db_slot = OpenSlot(**slot.model_dump())
    db.add(db_slot)
    db.commit()
    db.refresh(db_slot)
    return db_slot


@router.delete("/open-slots/{slot_id}")
def delete_open_slot(
    slot_id: int,
    db: Session = Depends(get_db),
    current_user = Depends(get_current_admin)
):
    slot = db.query(OpenSlot).filter(OpenSlot.id == slot_id).first()
    if not slot:
        raise HTTPException(status_code=404, detail="开放时段不存在")
    db.delete(slot)
    db.commit()
    return {"message": "删除成功"}


@router.get("/closed-dates", response_model=List[ClosedDateResponse])
def list_closed_dates(
    venue_id: Optional[int] = None,
    db: Session = Depends(get_db),
    current_user = Depends(get_current_user)
):
    query = db.query(ClosedDate)
    if venue_id is not None:
        if venue_id == 0:
            query = query.filter(ClosedDate.venue_id.is_(None))
        else:
            query = query.filter(ClosedDate.venue_id == venue_id)
    return query.order_by(ClosedDate.date.desc()).all()


@router.post("/closed-dates", response_model=ClosedDateResponse)
def create_closed_date(
    closed_date: ClosedDateCreate,
    db: Session = Depends(get_db),
    current_user = Depends(get_current_admin)
):
    existing = db.query(ClosedDate).filter(
        ClosedDate.date == closed_date.date,
        (ClosedDate.venue_id == closed_date.venue_id) | 
        (ClosedDate.venue_id.is_(None) if closed_date.venue_id is None else False)
    ).first()
    if existing:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="该日期已设置封场"
        )

    db_date = ClosedDate(**closed_date.model_dump())
    db.add(db_date)
    db.commit()
    db.refresh(db_date)
    return db_date


@router.delete("/closed-dates/{date_id}")
def delete_closed_date(
    date_id: int,
    db: Session = Depends(get_db),
    current_user = Depends(get_current_admin)
):
    date_item = db.query(ClosedDate).filter(ClosedDate.id == date_id).first()
    if not date_item:
        raise HTTPException(status_code=404, detail="封场日期不存在")
    db.delete(date_item)
    db.commit()
    return {"message": "删除成功"}


@router.get("/priority-rules", response_model=List[PriorityRuleResponse])
def list_priority_rules(
    db: Session = Depends(get_db),
    current_user = Depends(get_current_user)
):
    return db.query(PriorityRule).order_by(PriorityRule.priority_level.desc()).all()


@router.post("/priority-rules", response_model=PriorityRuleResponse)
def create_priority_rule(
    rule: PriorityRuleCreate,
    db: Session = Depends(get_db),
    current_user = Depends(get_current_admin)
):
    existing = db.query(PriorityRule).filter(PriorityRule.name == rule.name).first()
    if existing:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="优先级规则名称已存在"
        )

    db_rule = PriorityRule(**rule.model_dump())
    db.add(db_rule)
    db.commit()
    db.refresh(db_rule)
    return db_rule


@router.put("/priority-rules/{rule_id}", response_model=PriorityRuleResponse)
def update_priority_rule(
    rule_id: int,
    rule: PriorityRuleCreate,
    db: Session = Depends(get_db),
    current_user = Depends(get_current_admin)
):
    db_rule = db.query(PriorityRule).filter(PriorityRule.id == rule_id).first()
    if not db_rule:
        raise HTTPException(status_code=404, detail="优先级规则不存在")

    for key, value in rule.model_dump().items():
        setattr(db_rule, key, value)

    db.commit()
    db.refresh(db_rule)
    return db_rule


@router.delete("/priority-rules/{rule_id}")
def delete_priority_rule(
    rule_id: int,
    db: Session = Depends(get_db),
    current_user = Depends(get_current_admin)
):
    rule = db.query(PriorityRule).filter(PriorityRule.id == rule_id).first()
    if not rule:
        raise HTTPException(status_code=404, detail="优先级规则不存在")
    db.delete(rule)
    db.commit()
    return {"message": "删除成功"}


def closed_window_to_response(db: Session, window: ClosedWindow) -> ClosedWindowResponse:
    created_by_name = window.creator.full_name if window.creator else None
    revoked_by_name = window.revoker.full_name if window.revoker else None
    return ClosedWindowResponse(
        id=window.id,
        venue_id=window.venue_id,
        start_time=window.start_time,
        end_time=window.end_time,
        reason=window.reason or "",
        is_revoked=window.is_revoked,
        created_by=window.created_by,
        created_by_name=created_by_name,
        created_at=window.created_at,
        revoked_by=window.revoked_by,
        revoked_by_name=revoked_by_name,
        revoked_at=window.revoked_at,
        venue=window.venue
    )


@router.get("/closed-windows", response_model=List[ClosedWindowResponse])
def list_closed_windows(
    venue_id: Optional[int] = None,
    include_revoked: bool = False,
    db: Session = Depends(get_db),
    current_user = Depends(get_current_user)
):
    query = db.query(ClosedWindow)
    if venue_id is not None:
        if venue_id == 0:
            query = query.filter(ClosedWindow.venue_id.is_(None))
        else:
            query = query.filter(
                (ClosedWindow.venue_id == venue_id) | (ClosedWindow.venue_id.is_(None))
            )
    if not include_revoked:
        query = query.filter(ClosedWindow.is_revoked == False)
    windows = query.order_by(ClosedWindow.start_time.desc()).all()
    return [closed_window_to_response(db, w) for w in windows]


@router.post("/closed-windows", response_model=ClosedWindowResponse)
def create_closed_window(
    window_data: ClosedWindowCreate,
    db: Session = Depends(get_db),
    current_user = Depends(get_current_admin)
):
    if window_data.start_time >= window_data.end_time:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="结束时间必须晚于开始时间"
        )

    target_venue_id = None if window_data.apply_all_venues else window_data.venue_id

    if target_venue_id is not None:
        venue = db.query(Venue).filter(Venue.id == target_venue_id).first()
        if not venue:
            raise HTTPException(status_code=404, detail="场地不存在")

    if has_overlapping_closed_window(db, target_venue_id, window_data.start_time, window_data.end_time):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="该时段已存在重叠的封场窗口"
        )

    db_window = ClosedWindow(
        venue_id=target_venue_id,
        start_time=window_data.start_time,
        end_time=window_data.end_time,
        reason=window_data.reason,
        is_revoked=False,
        created_by=current_user.id
    )
    db.add(db_window)
    db.commit()
    db.refresh(db_window)
    return closed_window_to_response(db, db_window)


@router.delete("/closed-windows/{window_id}", response_model=ClosedWindowResponse)
def revoke_closed_window(
    window_id: int,
    db: Session = Depends(get_db),
    current_user = Depends(get_current_admin)
):
    window = db.query(ClosedWindow).filter(ClosedWindow.id == window_id).first()
    if not window:
        raise HTTPException(status_code=404, detail="封场窗口不存在")
    if window.is_revoked:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="该封场窗口已被撤销"
        )

    window.is_revoked = True
    window.revoked_by = current_user.id
    window.revoked_at = datetime.utcnow()
    db.commit()
    db.refresh(window)
    return closed_window_to_response(db, window)
