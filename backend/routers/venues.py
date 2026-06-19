from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session
from typing import List

from database import get_db, Venue
from auth import get_current_user, get_current_admin
from schemas import VenueCreate, VenueUpdate, VenueResponse

router = APIRouter()


@router.get("", response_model=List[VenueResponse])
def list_venues(
    include_inactive: bool = False,
    db: Session = Depends(get_db),
    current_user = Depends(get_current_user)
):
    query = db.query(Venue)
    if not include_inactive:
        query = query.filter(Venue.is_active == True)
    return query.order_by(Venue.id).all()


@router.get("/{venue_id}", response_model=VenueResponse)
def get_venue(
    venue_id: int,
    db: Session = Depends(get_db),
    current_user = Depends(get_current_user)
):
    venue = db.query(Venue).filter(Venue.id == venue_id).first()
    if not venue:
        raise HTTPException(status_code=404, detail="场地不存在")
    return venue


@router.post("", response_model=VenueResponse)
def create_venue(
    venue: VenueCreate,
    db: Session = Depends(get_db),
    current_user = Depends(get_current_admin)
):
    existing = db.query(Venue).filter(Venue.name == venue.name).first()
    if existing:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="场地名称已存在"
        )

    db_venue = Venue(**venue.model_dump())
    db.add(db_venue)
    db.commit()
    db.refresh(db_venue)
    return db_venue


@router.put("/{venue_id}", response_model=VenueResponse)
def update_venue(
    venue_id: int,
    venue: VenueUpdate,
    db: Session = Depends(get_db),
    current_user = Depends(get_current_admin)
):
    db_venue = db.query(Venue).filter(Venue.id == venue_id).first()
    if not db_venue:
        raise HTTPException(status_code=404, detail="场地不存在")

    existing = db.query(Venue).filter(
        Venue.name == venue.name,
        Venue.id != venue_id
    ).first()
    if existing:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="场地名称已存在"
        )

    for key, value in venue.model_dump().items():
        setattr(db_venue, key, value)

    db.commit()
    db.refresh(db_venue)
    return db_venue


@router.delete("/{venue_id}")
def delete_venue(
    venue_id: int,
    db: Session = Depends(get_db),
    current_user = Depends(get_current_admin)
):
    db_venue = db.query(Venue).filter(Venue.id == venue_id).first()
    if not db_venue:
        raise HTTPException(status_code=404, detail="场地不存在")

    db.delete(db_venue)
    db.commit()
    return {"message": "删除成功"}
