from pydantic import BaseModel, Field
from datetime import datetime, date, time
from typing import Optional, List, Dict


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
    blocked_by_details: str = ""
    filled_booking_id: Optional[int] = None
    filled_at: Optional[datetime] = None
    filled_method: Optional[str] = None
    cancelled_by: Optional[int] = None
    cancelled_by_name: Optional[str] = None
    cancelled_at: Optional[datetime] = None
    cancel_reason: str = ""
    expires_at: Optional[datetime] = None
    is_drill: bool = False
    drill_session_id: str = ""
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


class DrillStepResult(BaseModel):
    step_name: str
    passed: bool
    duration_ms: int = 0
    error_category: str = ""
    error_detail: str = ""


class DrillSessionCreate(BaseModel):
    venue_id: Optional[int] = None
    auto_find_slot: bool = True
    target_date_offset_days: int = 90


class DrillSessionResponse(BaseModel):
    drill_session_id: str
    status: str
    venue_id: int
    base_date: str
    steps: List[DrillStepResult] = []
    total_passed: int = 0
    total_failed: int = 0
    cleanup_completed: bool = False
    error_message: str = ""
    created_at: datetime
    completed_at: Optional[datetime] = None


class DrillCleanupResponse(BaseModel):
    drill_session_id: str
    removed_count: int
    details: Dict[str, int] = {}


class DrillRestartVerifyRequest(BaseModel):
    drill_session_id: str
    server_pid: int
    server_port: int = 8002


class DrillScriptVenueRules(BaseModel):
    venue_ids: List[int] = []
    auto_find_slot: bool = True
    search_days: int = 30
    preferred_hours: List[int] = [9, 10, 11, 14, 15, 16, 17, 19, 20]


class DrillScriptSample(BaseModel):
    name: str
    type: str
    priority: int = 10
    float_before_minutes: int = 30
    float_after_minutes: int = 30


class DrillScriptMember(BaseModel):
    username: str
    password: str
    full_name: str
    role: str = "member"


class DrillScriptCheckpoint(BaseModel):
    name: str
    description: str = ""
    expected: str = "passed"


class DrillScriptCleanupStrategy(BaseModel):
    auto_cleanup_on_success: bool = True
    keep_screenshots: bool = True
    keep_logs: bool = True
    keep_fill_results: bool = True


class DrillScriptBase(BaseModel):
    name: str
    description: str = ""
    version: str = "1.0"
    venue_rules: Dict = {}
    drill_samples: List = []
    member_accounts: List = []
    checkpoints: List = []
    cleanup_strategy: Dict = {}


class DrillScriptCreate(DrillScriptBase):
    pass


class DrillScriptUpdate(BaseModel):
    name: Optional[str] = None
    description: Optional[str] = None
    version: Optional[str] = None
    venue_rules: Optional[Dict] = None
    drill_samples: Optional[List] = None
    member_accounts: Optional[List] = None
    checkpoints: Optional[List] = None
    cleanup_strategy: Optional[Dict] = None
    is_active: Optional[bool] = None


class DrillScriptResponse(BaseModel):
    id: int
    name: str
    description: str
    version: str
    venue_rules: Dict = {}
    drill_samples: List = []
    member_accounts: List = []
    checkpoints: List = []
    cleanup_strategy: Dict = {}
    created_by: int
    created_by_name: Optional[str] = None
    is_active: bool
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True


class DrillScriptImportValidateResult(BaseModel):
    valid: bool
    errors: List[str] = []
    warnings: List[str] = []


class DrillBatchCreate(BaseModel):
    script_id: int
    venue_id: Optional[int] = None


class DrillBatchResponse(BaseModel):
    id: int
    batch_id: str
    script_id: int
    script_name: str
    status: str
    venue_id: Optional[int] = None
    venue_name: Optional[str] = None
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None
    rolled_back_at: Optional[datetime] = None
    created_by: int
    created_by_name: Optional[str] = None
    participant_user_ids: List = []
    total_steps: int = 0
    passed_steps: int = 0
    failed_steps: int = 0
    error_message: str = ""
    drill_session_ids: List = []
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True


class DrillBatchDetailResponse(DrillBatchResponse):
    artifacts: List = []


class DrillArtifactResponse(BaseModel):
    id: int
    batch_id: str
    artifact_type: str
    title: str
    content: str
    file_path: str
    metadata: Dict = {}
    user_id: Optional[int] = None
    user_name: Optional[str] = None
    created_at: datetime

    class Config:
        from_attributes = True


class DrillMemberBatchView(BaseModel):
    batch_id: str
    script_name: str
    status: str
    my_entries: List = []
    my_blocked_reasons: List = []
    my_fill_results: List = []


class DrillRollbackResponse(BaseModel):
    batch_id: str
    success: bool
    removed_count: int = 0
    details: Dict = {}
    message: str = ""


class DrillRecoverResponse(BaseModel):
    batch_id: str
    success: bool
    previous_status: str = ""
    current_status: str = ""
    message: str = ""
