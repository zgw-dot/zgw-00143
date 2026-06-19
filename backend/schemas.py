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


class ScheduleTemplateBase(BaseModel):
    name: str
    template_type: str = "venue"
    description: str = ""
    version: str = "1.0"
    is_active: bool = True
    config_json: Dict = {}


class ScheduleTemplateCreate(ScheduleTemplateBase):
    pass


class ScheduleTemplateUpdate(BaseModel):
    name: Optional[str] = None
    template_type: Optional[str] = None
    description: Optional[str] = None
    version: Optional[str] = None
    is_active: Optional[bool] = None
    config_json: Optional[Dict] = None
    change_note: str = ""


class ScheduleTemplateResponse(BaseModel):
    id: int
    name: str
    template_type: str
    description: str
    version: str
    is_active: bool
    config_json: Dict = {}
    created_by: int
    created_by_name: Optional[str] = None
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True


class ScheduleTemplateVersionResponse(BaseModel):
    id: int
    template_id: int
    version: str
    snapshot_json: Dict = {}
    change_note: str = ""
    created_by: int
    created_by_name: Optional[str] = None
    created_at: datetime

    class Config:
        from_attributes = True


class ScheduleTemplateImportValidateResult(BaseModel):
    valid: bool
    errors: List[str] = []
    blocking_errors: List[str] = []
    warnings: List[str] = []


class ScheduleTemplateImportResult(BaseModel):
    success: bool
    template_id: Optional[int] = None
    errors: List[str] = []
    blocking_errors: List[str] = []
    warnings: List[str] = []


class ScheduleCancelBody(BaseModel):
    reason: str = ""


class ScheduleCopyBody(BaseModel):
    new_date: Optional[date] = None
    new_start_time: Optional[str] = None
    new_end_time: Optional[str] = None


class ScheduleBatchGenerateBody(BaseModel):
    start_date: date
    end_date: date
    venue_template_id: Optional[int] = None
    venue_id: Optional[int] = None
    daily_start_time: str = "09:00:00"
    daily_end_time: str = "11:00:00"
    base_title: str = "演练"
    exclude_weekends: bool = True
    group_template_id: Optional[int] = None
    checklist_template_id: Optional[int] = None
    cleanup_template_id: Optional[int] = None
    drill_script_id: Optional[int] = None


class DrillScheduleBase(BaseModel):
    title: str
    schedule_date: date
    start_time: time
    end_time: time
    venue_id: int
    venue_template_id: Optional[int] = None
    group_template_id: Optional[int] = None
    checklist_template_id: Optional[int] = None
    cleanup_template_id: Optional[int] = None
    drill_script_id: Optional[int] = None
    notes: str = ""


class DrillScheduleCreate(DrillScheduleBase):
    auto_generate_members: bool = True


class DrillScheduleUpdate(BaseModel):
    title: Optional[str] = None
    schedule_date: Optional[date] = None
    start_time: Optional[time] = None
    end_time: Optional[time] = None
    venue_id: Optional[int] = None
    venue_template_id: Optional[int] = None
    group_template_id: Optional[int] = None
    checklist_template_id: Optional[int] = None
    cleanup_template_id: Optional[int] = None
    drill_script_id: Optional[int] = None
    notes: Optional[str] = None


class DrillScheduleConflict(BaseModel):
    type: str
    schedule_no: str = ""
    title: str = ""
    venue_name: str = ""
    schedule_date: str = ""
    start_time: str = ""
    end_time: str = ""
    reason: str = ""


class DrillScheduleResponse(BaseModel):
    id: int
    schedule_no: str
    title: str
    status: str
    schedule_date: date
    start_time: time
    end_time: time
    venue_id: int
    venue_name: Optional[str] = None
    venue_template_id: Optional[int] = None
    venue_template_name: Optional[str] = None
    group_template_id: Optional[int] = None
    group_template_name: Optional[str] = None
    checklist_template_id: Optional[int] = None
    checklist_template_name: Optional[str] = None
    cleanup_template_id: Optional[int] = None
    cleanup_template_name: Optional[str] = None
    template_snapshot: Dict = {}
    batch_id: str = ""
    drill_script_id: Optional[int] = None
    drill_script_name: Optional[str] = None
    conflict_details: List = []
    notes: str = ""
    created_by: int
    created_by_name: Optional[str] = None
    published_by: Optional[int] = None
    published_by_name: Optional[str] = None
    cancelled_by: Optional[int] = None
    cancelled_by_name: Optional[str] = None
    locked_by: Optional[int] = None
    locked_by_name: Optional[str] = None
    created_at: datetime
    updated_at: datetime
    published_at: Optional[datetime] = None
    cancelled_at: Optional[datetime] = None
    locked_at: Optional[datetime] = None
    executed_at: Optional[datetime] = None
    conflicts: List[DrillScheduleConflict] = []

    class Config:
        from_attributes = True


class DrillScheduleListResponse(BaseModel):
    items: List[DrillScheduleResponse]
    total: int
    page: int
    page_size: int


class ScheduleAuditLogResponse(BaseModel):
    id: int
    schedule_id: int
    schedule_no: str = ""
    user_id: int
    user_name: Optional[str] = None
    action: str
    action_text: str = ""
    old_value: Dict = {}
    new_value: Dict = {}
    change_note: str = ""
    ip_address: str = ""
    created_at: datetime

    class Config:
        from_attributes = True


class ScheduleMemberResponse(BaseModel):
    id: int
    schedule_id: int
    user_id: int
    user_name: str = ""
    full_name: str = ""
    group_name: str = ""
    role_in_schedule: str = ""
    result_data: Dict = {}
    download_summary: str = ""
    joined_at: datetime

    class Config:
        from_attributes = True


class ScheduleMemberPersonalView(BaseModel):
    schedule_id: int
    schedule_no: str
    title: str
    status: str
    schedule_date: date
    start_time: time
    end_time: time
    venue_name: str = ""
    group_name: str = ""
    role_in_schedule: str = ""
    my_result: Dict = {}
    my_download_summary: str = ""
    checklist_items: List = []
    execution_entries: List = []


class ScheduleActionResponse(BaseModel):
    success: bool
    schedule_no: str
    previous_status: str = ""
    current_status: str = ""
    message: str = ""
    batch_id: str = ""


class ScheduleCopyResult(BaseModel):
    success: bool
    original_schedule_no: str
    new_schedule_no: str
    new_schedule_id: Optional[int] = None
    message: str = ""


class ScheduleBatchGenerateResult(BaseModel):
    success: bool
    schedule_no: str
    batch_id: str
    message: str = ""


class ScheduleCleanupResult(BaseModel):
    success: bool
    schedule_no: str
    removed_samples: int = 0
    removed_temp_files: int = 0
    removed_placeholders: int = 0
    message: str = ""


class ScheduleRecoverResult(BaseModel):
    schedule_no: str
    recovered: bool
    previous_status: str = ""
    current_status: str = ""
    message: str = ""


class ScheduleCalendarItem(BaseModel):
    id: int
    schedule_no: str
    title: str
    status: str
    schedule_date: date
    start_time: time
    end_time: time
    venue_id: int
    venue_name: str = ""
    has_conflict: bool = False


class ScheduleRecoverSummary(BaseModel):
    recovered_count: int = 0
    items: List[ScheduleRecoverResult] = []
    message: str = ""


class AuditLogListResponse(BaseModel):
    items: List[ScheduleAuditLogResponse] = []
    total: int = 0
    page: int = 1
    page_size: int = 100
