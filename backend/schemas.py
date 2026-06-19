from pydantic import BaseModel, Field
from datetime import datetime, date, time
from typing import Optional, List


class UserBase(BaseModel):
    username: str
    full_name: str


class UserCreate(UserBase):
    password: str
    role: str = "member"


class UserLogin(BaseModel):
    username: str
    password: str


class UserResponse(UserBase):
    id: int
    role: str
    created_at: datetime

    class Config:
        from_attributes = True


class Token(BaseModel):
    access_token: str
    token_type: str = "bearer"
    user: UserResponse


class VenueBase(BaseModel):
    name: str
    description: str = ""
    capacity: int = 0
    is_active: bool = True


class VenueCreate(VenueBase):
    pass


class VenueUpdate(VenueBase):
    pass


class VenueResponse(VenueBase):
    id: int
    created_at: datetime

    class Config:
        from_attributes = True


class OpenSlotBase(BaseModel):
    venue_id: int
    day_of_week: int = Field(ge=0, le=6)
    start_time: time
    end_time: time


class OpenSlotCreate(OpenSlotBase):
    pass


class OpenSlotResponse(OpenSlotBase):
    id: int
    venue: Optional[VenueResponse] = None

    class Config:
        from_attributes = True


class ClosedDateBase(BaseModel):
    venue_id: Optional[int] = None
    date: date
    reason: str = ""


class ClosedDateCreate(ClosedDateBase):
    pass


class ClosedDateResponse(ClosedDateBase):
    id: int
    venue: Optional[VenueResponse] = None

    class Config:
        from_attributes = True


class ClosedWindowBase(BaseModel):
    venue_id: Optional[int] = None
    start_time: datetime
    end_time: datetime
    reason: str = ""


class ClosedWindowCreate(ClosedWindowBase):
    apply_all_venues: bool = False


class ClosedWindowResponse(ClosedWindowBase):
    id: int
    is_revoked: bool = False
    created_by: int
    created_by_name: Optional[str] = None
    created_at: datetime
    revoked_by: Optional[int] = None
    revoked_by_name: Optional[str] = None
    revoked_at: Optional[datetime] = None
    venue: Optional[VenueResponse] = None

    class Config:
        from_attributes = True


class ClosedWindowInfo(BaseModel):
    id: int
    venue_id: Optional[int] = None
    venue_name: Optional[str] = None
    start_time: datetime
    end_time: datetime
    reason: str = ""


class PriorityRuleBase(BaseModel):
    name: str
    priority_level: int = 10
    description: str = ""
    applies_to: str = "production"
    target_value: str = ""


class PriorityRuleCreate(PriorityRuleBase):
    pass


class PriorityRuleResponse(PriorityRuleBase):
    id: int
    created_at: datetime

    class Config:
        from_attributes = True


class BookingBase(BaseModel):
    title: str
    production: str
    venue_id: int
    start_time: datetime
    end_time: datetime
    priority: int = 10
    notes: str = ""


class BookingCreate(BookingBase):
    status: str = "draft"


class BookingUpdate(BaseModel):
    title: Optional[str] = None
    production: Optional[str] = None
    venue_id: Optional[int] = None
    start_time: Optional[datetime] = None
    end_time: Optional[datetime] = None
    priority: Optional[int] = None
    notes: Optional[str] = None
    version: int


class BookingStatusUpdate(BaseModel):
    status: str
    rejection_reason: Optional[str] = None
    version: int


class RescheduleRequest(BaseModel):
    new_start_time: datetime
    new_end_time: datetime
    reason: str
    version: int


class ConflictInfo(BaseModel):
    booking_id: int
    title: str
    production: str
    start_time: datetime
    end_time: datetime
    user_name: str
    venue_name: str


class BookingResponse(BookingBase):
    id: int
    version: int
    status: str
    user_id: int
    user_name: Optional[str] = None
    venue_name: Optional[str] = None
    rejection_reason: str = ""
    approver_id: Optional[int] = None
    approver_name: Optional[str] = None
    approved_at: Optional[datetime] = None
    created_at: datetime
    updated_at: datetime
    conflicts: Optional[List[ConflictInfo]] = None
    closed_windows: Optional[List[ClosedWindowInfo]] = None

    class Config:
        from_attributes = True


class RescheduleRecordResponse(BaseModel):
    id: int
    booking_id: int
    operator_id: int
    operator_name: Optional[str] = None
    original_start_time: datetime
    original_end_time: datetime
    new_start_time: datetime
    new_end_time: datetime
    reason: str
    created_at: datetime

    class Config:
        from_attributes = True


class BookingListResponse(BaseModel):
    items: List[BookingResponse]
    total: int
    page: int
    page_size: int


class WaitlistBase(BaseModel):
    venue_id: int
    title: str
    production: str
    target_start_time: datetime
    target_end_time: datetime
    float_before_minutes: int = 0
    float_after_minutes: int = 0
    notes: str = ""
    priority: int = 10


class WaitlistCreate(WaitlistBase):
    pass


class WaitlistCancel(BaseModel):
    cancel_reason: str = ""


class WaitlistFillRequest(BaseModel):
    method: str = "manual"
    notes: str = ""
    use_target_time: bool = True


class WaitlistResponse(WaitlistBase):
    id: int
    user_id: int
    user_name: Optional[str] = None
    venue_name: Optional[str] = None
    status: str
    queue_position: int
    blocked_by_type: str = ""
    filled_booking_id: Optional[int] = None
    filled_at: Optional[datetime] = None
    filled_method: Optional[str] = None
    cancelled_by: Optional[int] = None
    cancelled_by_name: Optional[str] = None
    cancelled_at: Optional[datetime] = None
    cancel_reason: str = ""
    expires_at: Optional[datetime] = None
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True


class WaitlistLogResponse(BaseModel):
    id: int
    waitlist_entry_id: int
    operator_id: Optional[int] = None
    operator_name: Optional[str] = None
    action: str
    trigger_reason: str = ""
    result_booking_id: Optional[int] = None
    notes: str = ""
    created_at: datetime

    class Config:
        from_attributes = True


class WaitlistListResponse(BaseModel):
    items: List[WaitlistResponse]
    total: int
    page: int
    page_size: int


class WaitlistFillResult(BaseModel):
    success: bool
    waitlist_id: int
    booking_id: Optional[int] = None
    status: str
    message: str = ""
