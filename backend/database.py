from sqlalchemy import create_engine, Column, Integer, String, DateTime, Date, Time, Boolean, ForeignKey, Text
from sqlalchemy.orm import declarative_base, sessionmaker, relationship
from datetime import datetime

SQLALCHEMY_DATABASE_URL = "sqlite:///./theater_booking.db"

engine = create_engine(
    SQLALCHEMY_DATABASE_URL, connect_args={"check_same_thread": False}
)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

Base = declarative_base()


class User(Base):
    __tablename__ = "users"

    id = Column(Integer, primary_key=True, index=True)
    username = Column(String(50), unique=True, index=True, nullable=False)
    password_hash = Column(String(255), nullable=False)
    full_name = Column(String(100), nullable=False)
    role = Column(String(20), nullable=False, default="member")  # admin, member
    created_at = Column(DateTime, default=datetime.utcnow)


class Venue(Base):
    __tablename__ = "venues"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(100), nullable=False, unique=True)
    description = Column(Text, default="")
    capacity = Column(Integer, default=0)
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime, default=datetime.utcnow)


class OpenSlot(Base):
    __tablename__ = "open_slots"

    id = Column(Integer, primary_key=True, index=True)
    venue_id = Column(Integer, ForeignKey("venues.id"), nullable=False)
    day_of_week = Column(Integer, nullable=False)  # 0=Monday, 6=Sunday
    start_time = Column(Time, nullable=False)
    end_time = Column(Time, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow)

    venue = relationship("Venue")


class ClosedDate(Base):
    __tablename__ = "closed_dates"

    id = Column(Integer, primary_key=True, index=True)
    venue_id = Column(Integer, ForeignKey("venues.id"), nullable=True)  # null = all venues
    date = Column(Date, nullable=False)
    reason = Column(String(255), default="")
    created_at = Column(DateTime, default=datetime.utcnow)

    venue = relationship("Venue")


class ClosedWindow(Base):
    __tablename__ = "closed_windows"

    id = Column(Integer, primary_key=True, index=True)
    venue_id = Column(Integer, ForeignKey("venues.id"), nullable=True)  # null = all venues
    start_time = Column(DateTime, nullable=False)
    end_time = Column(DateTime, nullable=False)
    reason = Column(String(255), default="")
    is_revoked = Column(Boolean, default=False)
    created_by = Column(Integer, ForeignKey("users.id"), nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow)
    revoked_by = Column(Integer, ForeignKey("users.id"), nullable=True)
    revoked_at = Column(DateTime, nullable=True)

    is_drill = Column(Boolean, default=False)
    drill_session_id = Column(String(100), default="")

    venue = relationship("Venue")
    creator = relationship("User", foreign_keys=[created_by])
    revoker = relationship("User", foreign_keys=[revoked_by])


class PriorityRule(Base):
    __tablename__ = "priority_rules"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(100), nullable=False, unique=True)
    priority_level = Column(Integer, nullable=False, default=10)  # higher = higher priority
    description = Column(Text, default="")
    applies_to = Column(String(50), default="production")  # production, role, user
    target_value = Column(String(100), default="")
    created_at = Column(DateTime, default=datetime.utcnow)


class Booking(Base):
    __tablename__ = "bookings"

    id = Column(Integer, primary_key=True, index=True)
    version = Column(Integer, nullable=False, default=1)
    title = Column(String(200), nullable=False)
    production = Column(String(100), nullable=False)  # 剧目
    venue_id = Column(Integer, ForeignKey("venues.id"), nullable=False)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    status = Column(String(20), nullable=False, default="draft")
    # draft, pending, confirmed, rescheduling, cancelled

    start_time = Column(DateTime, nullable=False)
    end_time = Column(DateTime, nullable=False)

    priority = Column(Integer, default=10)
    notes = Column(Text, default="")
    rejection_reason = Column(Text, default="")

    approver_id = Column(Integer, ForeignKey("users.id"), nullable=True)
    approved_at = Column(DateTime, nullable=True)

    is_drill = Column(Boolean, default=False)
    drill_session_id = Column(String(100), default="")

    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    venue = relationship("Venue", foreign_keys=[venue_id])
    user = relationship("User", foreign_keys=[user_id])
    approver = relationship("User", foreign_keys=[approver_id])


class RescheduleRecord(Base):
    __tablename__ = "reschedule_records"

    id = Column(Integer, primary_key=True, index=True)
    booking_id = Column(Integer, ForeignKey("bookings.id"), nullable=False)
    operator_id = Column(Integer, ForeignKey("users.id"), nullable=False)

    original_start_time = Column(DateTime, nullable=False)
    original_end_time = Column(DateTime, nullable=False)
    new_start_time = Column(DateTime, nullable=False)
    new_end_time = Column(DateTime, nullable=False)

    reason = Column(Text, nullable=False)

    is_drill = Column(Boolean, default=False)
    drill_session_id = Column(String(100), default="")

    created_at = Column(DateTime, default=datetime.utcnow)

    booking = relationship("Booking")
    operator = relationship("User")


class WaitlistEntry(Base):
    __tablename__ = "waitlist_entries"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    venue_id = Column(Integer, ForeignKey("venues.id"), nullable=False)
    title = Column(String(200), nullable=False)
    production = Column(String(100), nullable=False)

    target_start_time = Column(DateTime, nullable=False)
    target_end_time = Column(DateTime, nullable=False)
    float_before_minutes = Column(Integer, default=0)
    float_after_minutes = Column(Integer, default=0)

    notes = Column(Text, default="")
    priority = Column(Integer, default=10)

    status = Column(String(20), nullable=False, default="waiting")
    # waiting: 排队中, filled: 已补位, cancelled: 已取消, expired: 已过期

    queue_position = Column(Integer, nullable=False, default=0)
    # 排队序号（同场地+同目标日期的顺序）

    blocked_by_type = Column(String(50), default="")
    # booking: 被已有预约挡住, closed_window: 被封场挡住, both: 两者都有

    blocked_by_details = Column(Text, default="")
    # 阻塞详情（JSON 字符串）

    filled_booking_id = Column(Integer, ForeignKey("bookings.id"), nullable=True)
    filled_at = Column(DateTime, nullable=True)
    filled_method = Column(String(20), nullable=True)
    # auto: 自动补位, manual: 手动补位

    cancelled_by = Column(Integer, ForeignKey("users.id"), nullable=True)
    cancelled_at = Column(DateTime, nullable=True)
    cancel_reason = Column(Text, default="")

    expires_at = Column(DateTime, nullable=True)

    is_drill = Column(Boolean, default=False)
    drill_session_id = Column(String(100), default="")

    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    user = relationship("User", foreign_keys=[user_id])
    venue = relationship("Venue", foreign_keys=[venue_id])
    filled_booking = relationship("Booking", foreign_keys=[filled_booking_id])
    canceller = relationship("User", foreign_keys=[cancelled_by])


class WaitlistLog(Base):
    __tablename__ = "waitlist_logs"

    id = Column(Integer, primary_key=True, index=True)
    waitlist_entry_id = Column(Integer, ForeignKey("waitlist_entries.id"), nullable=False)
    operator_id = Column(Integer, ForeignKey("users.id"), nullable=True)

    action = Column(String(50), nullable=False)
    # create: 登记候补, fill: 补位, cancel: 取消候补, expire: 过期, auto_trigger: 自动触发

    trigger_reason = Column(String(100), default="")
    # booking_cancelled: 预约取消触发, booking_rescheduled: 预约改期触发
    # closed_window_revoked: 封场撤销触发, manual_fill: 管理员手动补位
    # manual_cancel: 手动取消, auto_expire: 自动过期

    blocked_by_snapshot = Column(Text, default="")
    # 触发补位时原先被什么挡住的快照

    result_booking_id = Column(Integer, ForeignKey("bookings.id"), nullable=True)
    notes = Column(Text, default="")
    created_at = Column(DateTime, default=datetime.utcnow)

    waitlist_entry = relationship("WaitlistEntry")
    operator = relationship("User")
    result_booking = relationship("Booking")


class DrillScript(Base):
    __tablename__ = "drill_scripts"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(200), nullable=False, unique=True, index=True)
    description = Column(Text, default="")
    version = Column(String(50), default="1.0")

    venue_rules = Column(Text, default="{}")
    drill_samples = Column(Text, default="[]")
    member_accounts = Column(Text, default="[]")
    checkpoints = Column(Text, default="[]")
    cleanup_strategy = Column(Text, default="{}")

    created_by = Column(Integer, ForeignKey("users.id"), nullable=False)
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    creator = relationship("User", foreign_keys=[created_by])


class DrillBatch(Base):
    __tablename__ = "drill_batches"

    id = Column(Integer, primary_key=True, index=True)
    batch_id = Column(String(100), unique=True, nullable=False, index=True)
    script_id = Column(Integer, ForeignKey("drill_scripts.id"), nullable=False)
    script_name = Column(String(200), default="")
    script_snapshot = Column(Text, default="{}")

    status = Column(String(30), default="pending")
    # pending: 待执行, running: 执行中, completed: 已完成,
    # failed: 失败, rolled_back: 已回滚, recovering: 恢复中

    venue_id = Column(Integer, ForeignKey("venues.id"), nullable=True)
    started_at = Column(DateTime, nullable=True)
    completed_at = Column(DateTime, nullable=True)
    rolled_back_at = Column(DateTime, nullable=True)

    created_by = Column(Integer, ForeignKey("users.id"), nullable=False)
    participant_user_ids = Column(Text, default="[]")

    total_steps = Column(Integer, default=0)
    passed_steps = Column(Integer, default=0)
    failed_steps = Column(Integer, default=0)
    error_message = Column(Text, default="")

    drill_session_ids = Column(Text, default="[]")

    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    script = relationship("DrillScript", foreign_keys=[script_id])
    creator = relationship("User", foreign_keys=[created_by])
    venue = relationship("Venue", foreign_keys=[venue_id])


class DrillArtifact(Base):
    __tablename__ = "drill_artifacts"

    id = Column(Integer, primary_key=True, index=True)
    batch_id = Column(String(100), nullable=False, index=True)

    artifact_type = Column(String(50), nullable=False)
    # screenshot: 失败截图, fill_result: 补位结果,
    # download_summary: 下载文件摘要, op_log: 操作日志
    # step_result: 步骤执行结果

    title = Column(String(500), default="")
    content = Column(Text, default="")
    file_path = Column(String(500), default="")
    metadata_json = Column(Text, default="{}")

    user_id = Column(Integer, ForeignKey("users.id"), nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)

    owner = relationship("User", foreign_keys=[user_id])


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
