from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session
from typing import List, Optional

from database import get_db, OpenSlot, ClosedDate, PriorityRule
from auth import get_current_user, get_current_admin
from schemas import (
    OpenSlotCreate, OpenSlotResponse,
    ClosedDateCreate, ClosedDateResponse,
    PriorityRuleCreate, PriorityRuleResponse
)

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
