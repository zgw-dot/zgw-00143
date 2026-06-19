from datetime import datetime, timedelta, date, time
from sqlalchemy.orm import Session
from typing import List, Optional, Dict, Any, Tuple
import uuid
import json
import os
import shutil

from database import (
    ScheduleTemplate, ScheduleTemplateVersion,
    DrillSchedule, ScheduleAuditLog, ScheduleMember, SchedulePlaceholder,
    User, Venue, DrillScript, DrillBatch, Booking, ClosedWindow
)
from schemas import (
    ScheduleTemplateCreate, ScheduleTemplateUpdate,
    ScheduleTemplateImportValidateResult,
    DrillScheduleCreate, DrillScheduleUpdate
)

TEMPLATE_TYPES = ["venue", "group", "checklist", "cleanup"]
TEMPLATE_TYPE_NAMES = {
    "venue": "场地模板",
    "group": "成员分组",
    "checklist": "浏览器检查清单",
    "cleanup": "清理规则"
}

SCHEDULE_STATUS = {
    "DRAFT": "draft",
    "PUBLISHED": "published",
    "LOCKED": "locked",
    "CANCELLED": "cancelled",
    "EXECUTING": "executing",
    "COMPLETED": "completed"
}

SCHEDULE_STATUS_NAMES = {
    "draft": "草稿",
    "published": "已发布",
    "locked": "已锁定",
    "cancelled": "已撤销",
    "executing": "执行中",
    "completed": "已完成"
}

AUDIT_ACTION_NAMES = {
    "create": "创建排期",
    "update": "修改排期",
    "publish": "发布排期",
    "lock": "锁定排期",
    "unlock": "解锁排期",
    "cancel": "撤销排期",
    "execute": "开始执行",
    "copy": "复制排期",
    "generate_batch": "生成执行批次",
    "template_create": "创建模板",
    "template_update": "更新模板",
    "template_delete": "删除模板",
    "template_toggle": "启停模板",
    "template_import": "导入模板",
    "cleanup": "清理排期数据"
}

REQUIRED_TEMPLATE_FIELDS = {
    "venue": ["venue_ids", "time_slots"],
    "group": ["groups"],
    "checklist": ["items"],
    "cleanup": ["cleanup_types"]
}

VALID_CLEANUP_TYPES = ["samples", "temp_files", "placeholders", "bookings", "all"]


def _json_loads_safe(text: str, default=None):
    try:
        if not text:
            return default
        return json.loads(text)
    except Exception:
        return default


def _json_dumps_safe(obj) -> str:
    try:
        return json.dumps(obj, ensure_ascii=False)
    except Exception:
        return "{}"


def _create_schedule_no() -> str:
    return f"SCH_{datetime.now().strftime('%Y%m%d%H%M%S')}_{uuid.uuid4().hex[:6].upper()}"


def _template_to_dict(t: ScheduleTemplate) -> Dict[str, Any]:
    return {
        "id": t.id,
        "name": t.name,
        "template_type": t.template_type,
        "description": t.description or "",
        "version": t.version,
        "is_active": bool(t.is_active),
        "config_json": _json_loads_safe(t.config_json, {}),
        "created_by": t.created_by,
        "created_by_name": t.creator.full_name if t.creator else None,
        "created_at": t.created_at,
        "updated_at": t.updated_at
    }


def _template_version_to_dict(v: ScheduleTemplateVersion) -> Dict[str, Any]:
    return {
        "id": v.id,
        "template_id": v.template_id,
        "version": v.version,
        "snapshot_json": _json_loads_safe(v.snapshot_json, {}),
        "change_note": v.change_note or "",
        "created_by": v.created_by,
        "created_by_name": v.creator.full_name if v.creator else None,
        "created_at": v.created_at
    }


def _schedule_to_dict(s: DrillSchedule) -> Dict[str, Any]:
    snapshot = _json_loads_safe(s.template_snapshot, {})
    result = {
        "id": s.id,
        "schedule_no": s.schedule_no,
        "title": s.title,
        "status": s.status,
        "schedule_date": s.schedule_date,
        "start_time": s.start_time,
        "end_time": s.end_time,
        "venue_id": s.venue_id,
        "venue_name": s.venue.name if s.venue else None,
        "venue_template_id": s.venue_template_id,
        "venue_template_name": snapshot.get("venue_template_name") or (s.venue_template.name if s.venue_template else None),
        "group_template_id": s.group_template_id,
        "group_template_name": snapshot.get("group_template_name") or (s.group_template.name if s.group_template else None),
        "checklist_template_id": s.checklist_template_id,
        "checklist_template_name": snapshot.get("checklist_template_name") or (s.checklist_template.name if s.checklist_template else None),
        "cleanup_template_id": s.cleanup_template_id,
        "cleanup_template_name": snapshot.get("cleanup_template_name") or (s.cleanup_template.name if s.cleanup_template else None),
        "template_snapshot": snapshot,
        "batch_id": s.batch_id or "",
        "drill_script_id": s.drill_script_id,
        "drill_script_name": s.drill_script.name if s.drill_script else None,
        "conflict_details": _json_loads_safe(s.conflict_details, []),
        "notes": s.notes or "",
        "created_by": s.created_by,
        "created_by_name": s.creator.full_name if s.creator else None,
        "published_by": s.published_by,
        "published_by_name": s.publisher.full_name if s.publisher else None,
        "cancelled_by": s.cancelled_by,
        "cancelled_by_name": s.canceller.full_name if s.canceller else None,
        "locked_by": s.locked_by,
        "locked_by_name": s.locker.full_name if s.locker else None,
        "created_at": s.created_at,
        "updated_at": s.updated_at,
        "published_at": s.published_at,
        "cancelled_at": s.cancelled_at,
        "locked_at": s.locked_at,
        "executed_at": s.executed_at,
        "conflicts": []
    }
    return result


def _audit_log_to_dict(log: ScheduleAuditLog) -> Dict[str, Any]:
    return {
        "id": log.id,
        "schedule_id": log.schedule_id,
        "schedule_no": log.schedule.schedule_no if log.schedule else "",
        "user_id": log.user_id,
        "user_name": log.user.full_name if log.user else None,
        "action": log.action,
        "action_text": AUDIT_ACTION_NAMES.get(log.action, log.action),
        "old_value": _json_loads_safe(log.old_value, {}),
        "new_value": _json_loads_safe(log.new_value, {}),
        "change_note": log.change_note or "",
        "ip_address": log.ip_address or "",
        "created_at": log.created_at
    }


def _schedule_member_to_dict(sm: ScheduleMember) -> Dict[str, Any]:
    return {
        "id": sm.id,
        "schedule_id": sm.schedule_id,
        "user_id": sm.user_id,
        "user_name": sm.user.username if sm.user else "",
        "full_name": sm.user.full_name if sm.user else "",
        "group_name": sm.group_name or "",
        "role_in_schedule": sm.role_in_schedule or "",
        "result_data": _json_loads_safe(sm.result_data, {}),
        "download_summary": sm.download_summary or "",
        "joined_at": sm.joined_at
    }


# ============================================================================
# 模板管理
# ============================================================================

def get_template(db: Session, template_id: int) -> Optional[ScheduleTemplate]:
    return db.query(ScheduleTemplate).filter(ScheduleTemplate.id == template_id).first()


def get_template_by_name(db: Session, name: str) -> Optional[ScheduleTemplate]:
    return db.query(ScheduleTemplate).filter(ScheduleTemplate.name == name).first()


def list_templates(
    db: Session,
    template_type: Optional[str] = None,
    is_active: Optional[bool] = None,
    keyword: str = ""
) -> List[ScheduleTemplate]:
    q = db.query(ScheduleTemplate)
    if template_type:
        q = q.filter(ScheduleTemplate.template_type == template_type)
    if is_active is not None:
        q = q.filter(ScheduleTemplate.is_active == is_active)
    if keyword:
        like = f"%{keyword}%"
        q = q.filter(
            (ScheduleTemplate.name.like(like)) |
            (ScheduleTemplate.description.like(like))
        )
    return q.order_by(ScheduleTemplate.updated_at.desc()).all()


def create_template(
    db: Session,
    data: ScheduleTemplateCreate,
    creator_id: int
) -> ScheduleTemplate:
    t = ScheduleTemplate(
        name=data.name.strip(),
        template_type=data.template_type,
        description=data.description,
        version=data.version,
        is_active=data.is_active,
        config_json=_json_dumps_safe(data.config_json or {}),
        created_by=creator_id
    )
    db.add(t)
    db.flush()

    snap = ScheduleTemplateVersion(
        template_id=t.id,
        version=t.version,
        snapshot_json=_json_dumps_safe(data.config_json or {}),
        change_note="初始版本",
        created_by=creator_id
    )
    db.add(snap)
    db.flush()
    return t


def update_template(
    db: Session,
    t: ScheduleTemplate,
    data: ScheduleTemplateUpdate,
    operator_id: int
) -> ScheduleTemplate:
    old_snapshot = {
        "name": t.name,
        "template_type": t.template_type,
        "description": t.description,
        "version": t.version,
        "is_active": t.is_active,
        "config_json": _json_loads_safe(t.config_json, {})
    }

    if data.name is not None:
        t.name = data.name.strip()
    if data.template_type is not None:
        t.template_type = data.template_type
    if data.description is not None:
        t.description = data.description
    if data.is_active is not None:
        t.is_active = data.is_active

    version_changed = False
    if data.version is not None and data.version != t.version:
        t.version = data.version
        version_changed = True

    config_changed = False
    if data.config_json is not None:
        new_cfg = _json_dumps_safe(data.config_json)
        if new_cfg != t.config_json:
            t.config_json = new_cfg
            config_changed = True

    if version_changed or config_changed:
        snap = ScheduleTemplateVersion(
            template_id=t.id,
            version=t.version,
            snapshot_json=t.config_json,
            change_note=data.change_note or (f"版本更新: {t.version}" if version_changed else "配置更新"),
            created_by=operator_id
        )
        db.add(snap)
        db.flush()

    return t


def delete_template(db: Session, t: ScheduleTemplate) -> None:
    used = db.query(DrillSchedule).filter(
        (DrillSchedule.venue_template_id == t.id) |
        (DrillSchedule.group_template_id == t.id) |
        (DrillSchedule.checklist_template_id == t.id) |
        (DrillSchedule.cleanup_template_id == t.id)
    ).first()
    if used:
        raise ValueError(f"模板正在被排期使用，无法删除")

    db.query(ScheduleTemplateVersion).filter(
        ScheduleTemplateVersion.template_id == t.id
    ).delete(synchronize_session=False)
    db.delete(t)


def toggle_template_active(db: Session, t: ScheduleTemplate, operator_id: int) -> ScheduleTemplate:
    t.is_active = not t.is_active
    snap = ScheduleTemplateVersion(
        template_id=t.id,
        version=t.version,
        snapshot_json=t.config_json,
        change_note=f"{'启用' if t.is_active else '停用'}模板",
        created_by=operator_id
    )
    db.add(snap)
    db.flush()
    return t


def list_template_versions(db: Session, template_id: int) -> List[ScheduleTemplateVersion]:
    return db.query(ScheduleTemplateVersion).filter(
        ScheduleTemplateVersion.template_id == template_id
    ).order_by(ScheduleTemplateVersion.created_at.desc()).all()


def validate_template_import(
    db: Session,
    template_data: Dict[str, Any]
) -> ScheduleTemplateImportValidateResult:
    errors = []
    warnings = []

    name = str(template_data.get("name", "")).strip()
    ttype = str(template_data.get("template_type", "")).strip()
    config = template_data.get("config_json") or template_data.get("config") or {}

    if not name:
        errors.append("模板名称不能为空")
    if not ttype:
        errors.append("模板类型不能为空")
    elif ttype not in TEMPLATE_TYPES:
        errors.append(f"模板类型无效，必须是: {', '.join(TEMPLATE_TYPES)}")

    if name:
        existing = get_template_by_name(db, name)
        if existing:
            errors.append(f"模板名称已存在: {name}")

    if ttype and ttype in REQUIRED_TEMPLATE_FIELDS:
        required = REQUIRED_TEMPLATE_FIELDS[ttype]
        for field in required:
            if field not in config:
                errors.append(f"缺少必填字段: {field} (模板类型: {TEMPLATE_TYPE_NAMES.get(ttype, ttype)})")

    if ttype == "venue":
        venue_ids = config.get("venue_ids", [])
        if not venue_ids:
            errors.append("场地模板必须指定至少一个场地ID")
        else:
            for vid in venue_ids:
                v = db.query(Venue).filter(Venue.id == vid).first()
                if not v:
                    errors.append(f"场地ID {vid} 不存在")
                elif not v.is_active:
                    warnings.append(f"场地 '{v.name}' (ID:{vid}) 未启用")
        time_slots = config.get("time_slots", [])
        if not time_slots:
            errors.append("场地模板必须指定至少一个时间段")

    if ttype == "group":
        groups = config.get("groups", [])
        for idx, grp in enumerate(groups):
            gname = grp.get("name", "")
            members = grp.get("members", [])
            if not gname:
                errors.append(f"第{idx+1}个分组缺少名称")
            if not members:
                warnings.append(f"分组 '{gname}' 没有成员")
            else:
                for mid in members:
                    u = db.query(User).filter(User.id == mid).first()
                    if not u:
                        errors.append(f"分组 '{gname}' 中的用户ID {mid} 不存在")

    if ttype == "checklist":
        items = config.get("items", [])
        if not items:
            warnings.append("检查清单项为空")
        for idx, item in enumerate(items):
            if not item.get("name"):
                errors.append(f"第{idx+1}个检查项缺少名称")

    if ttype == "cleanup":
        cleanup_types = config.get("cleanup_types", [])
        for ct in cleanup_types:
            if ct not in VALID_CLEANUP_TYPES:
                errors.append(f"无效的清理类型: {ct}，有效值: {', '.join(VALID_CLEANUP_TYPES)}")

    return ScheduleTemplateImportValidateResult(
        valid=(len(errors) == 0),
        errors=errors,
        warnings=warnings
    )


def import_template(
    db: Session,
    template_data: Dict[str, Any],
    creator_id: int
) -> Tuple[ScheduleTemplate, ScheduleTemplateImportValidateResult]:
    validation = validate_template_import(db, template_data)
    if not validation.valid:
        raise ValueError("; ".join(validation.errors))

    data = ScheduleTemplateCreate(
        name=str(template_data.get("name", "")).strip(),
        template_type=str(template_data.get("template_type", "venue")),
        description=str(template_data.get("description", "")),
        version=str(template_data.get("version", "1.0")),
        is_active=bool(template_data.get("is_active", True)),
        config_json=template_data.get("config_json") or template_data.get("config") or {}
    )
    t = create_template(db, data, creator_id)
    return t, validation


def export_template(t: ScheduleTemplate) -> Dict[str, Any]:
    return {
        "name": t.name,
        "template_type": t.template_type,
        "template_type_name": TEMPLATE_TYPE_NAMES.get(t.template_type, t.template_type),
        "description": t.description or "",
        "version": t.version,
        "is_active": bool(t.is_active),
        "config_json": _json_loads_safe(t.config_json, {}),
        "exported_at": datetime.utcnow().isoformat()
    }


# ============================================================================
# 排期管理 - 冲突检测
# ============================================================================

def _time_to_minutes(t: time) -> int:
    return t.hour * 60 + t.minute


def _times_overlap(
    start1: time, end1: time,
    start2: time, end2: time
) -> bool:
    s1 = _time_to_minutes(start1)
    e1 = _time_to_minutes(end1)
    s2 = _time_to_minutes(start2)
    e2 = _time_to_minutes(end2)
    return s1 < e2 and s2 < e1


def detect_schedule_conflicts(
    db: Session,
    schedule_date: date,
    start_time: time,
    end_time: time,
    venue_id: int,
    exclude_schedule_id: Optional[int] = None
) -> List[Dict[str, Any]]:
    conflicts = []

    existing = db.query(DrillSchedule).filter(
        DrillSchedule.schedule_date == schedule_date,
        DrillSchedule.venue_id == venue_id,
        DrillSchedule.status.in_(["published", "locked", "executing", "draft", "completed"])
    ).all()

    for s in existing:
        if exclude_schedule_id and s.id == exclude_schedule_id:
            continue
        if _times_overlap(start_time, end_time, s.start_time, s.end_time):
            conflicts.append({
                "type": "schedule_overlap",
                "schedule_no": s.schedule_no,
                "title": s.title,
                "venue_name": s.venue.name if s.venue else "",
                "schedule_date": str(s.schedule_date),
                "start_time": str(s.start_time),
                "end_time": str(s.end_time),
                "reason": f"与排期'{s.title}'({s.schedule_no})在{str(s.schedule_date)} {str(s.start_time)}-{str(s.end_time)} 场地双占"
            })

    bookings = db.query(Booking).filter(
        Booking.venue_id == venue_id,
        Booking.status == "confirmed"
    ).all()
    for b in bookings:
        if b.start_time.date() != schedule_date:
            continue
        b_start = b.start_time.time()
        b_end = b.end_time.time()
        if _times_overlap(start_time, end_time, b_start, b_end):
            conflicts.append({
                "type": "booking_overlap",
                "schedule_no": "",
                "title": b.title,
                "venue_name": b.venue.name if b.venue else "",
                "schedule_date": str(b.start_time.date()),
                "start_time": str(b_start),
                "end_time": str(b_end),
                "reason": f"与正式预约'{b.title}'在{str(b.start_time.date())} {str(b_start)}-{str(b_end)} 冲突"
            })

    closed_wins = db.query(ClosedWindow).filter(
        (ClosedWindow.venue_id == venue_id) | (ClosedWindow.venue_id.is_(None)),
        ClosedWindow.is_revoked == False
    ).all()
    for cw in closed_wins:
        if cw.start_time.date() <= schedule_date <= cw.end_time.date():
            cw_start = cw.start_time.time()
            cw_end = cw.end_time.time()
            if _times_overlap(start_time, end_time, cw_start, cw_end):
                conflicts.append({
                    "type": "closed_window",
                    "schedule_no": "",
                    "title": cw.reason or "封场",
                    "venue_name": cw.venue.name if cw.venue else "全场地",
                    "schedule_date": str(cw.start_time.date()),
                    "start_time": str(cw_start),
                    "end_time": str(cw_end),
                    "reason": f"与封场时段冲突: {cw.reason or '未说明原因'}"
                })

    return conflicts


# ============================================================================
# 排期管理 - CRUD
# ============================================================================

def get_schedule(db: Session, schedule_id: int) -> Optional[DrillSchedule]:
    return db.query(DrillSchedule).filter(DrillSchedule.id == schedule_id).first()


def get_schedule_by_no(db: Session, schedule_no: str) -> Optional[DrillSchedule]:
    return db.query(DrillSchedule).filter(DrillSchedule.schedule_no == schedule_no).first()


def list_schedules(
    db: Session,
    start_date: Optional[date] = None,
    end_date: Optional[date] = None,
    venue_id: Optional[int] = None,
    status: Optional[str] = None,
    keyword: str = "",
    page: int = 1,
    page_size: int = 50
) -> Tuple[List[DrillSchedule], int]:
    q = db.query(DrillSchedule)
    if start_date:
        q = q.filter(DrillSchedule.schedule_date >= start_date)
    if end_date:
        q = q.filter(DrillSchedule.schedule_date <= end_date)
    if venue_id:
        q = q.filter(DrillSchedule.venue_id == venue_id)
    if status:
        q = q.filter(DrillSchedule.status == status)
    if keyword:
        like = f"%{keyword}%"
        q = q.filter(
            (DrillSchedule.title.like(like)) |
            (DrillSchedule.schedule_no.like(like)) |
            (DrillSchedule.notes.like(like))
        )

    total = q.count()
    items = q.order_by(
        DrillSchedule.schedule_date.desc(),
        DrillSchedule.start_time.desc()
    ).offset((page - 1) * page_size).limit(page_size).all()
    return items, total


def list_schedules_for_member(
    db: Session,
    user_id: int,
    status: Optional[str] = None
) -> List[DrillSchedule]:
    subq = db.query(ScheduleMember.schedule_id).filter(
        ScheduleMember.user_id == user_id
    ).subquery()
    q = db.query(DrillSchedule).filter(DrillSchedule.id.in_(subq))
    if status:
        q = q.filter(DrillSchedule.status == status)
    return q.order_by(DrillSchedule.schedule_date.desc()).all()


def list_schedule_calendar(
    db: Session,
    start_date: date,
    end_date: date,
    venue_id: Optional[int] = None,
    user_id: Optional[int] = None
) -> List[Dict[str, Any]]:
    q = db.query(DrillSchedule).filter(
        DrillSchedule.schedule_date >= start_date,
        DrillSchedule.schedule_date <= end_date
    )
    if venue_id:
        q = q.filter(DrillSchedule.venue_id == venue_id)
    if user_id:
        subq = db.query(ScheduleMember.schedule_id).filter(
            ScheduleMember.user_id == user_id
        ).subquery()
        q = q.filter(DrillSchedule.id.in_(subq))

    items = q.order_by(DrillSchedule.schedule_date, DrillSchedule.start_time).all()
    result = []
    for s in items:
        conflicts = _json_loads_safe(s.conflict_details, [])
        result.append({
            "id": s.id,
            "schedule_no": s.schedule_no,
            "title": s.title,
            "status": s.status,
            "schedule_date": s.schedule_date,
            "start_time": s.start_time,
            "end_time": s.end_time,
            "venue_id": s.venue_id,
            "venue_name": s.venue.name if s.venue else "",
            "has_conflict": len(conflicts) > 0
        })
    return result


def _build_template_snapshot(
    db: Session,
    venue_template_id: Optional[int],
    group_template_id: Optional[int],
    checklist_template_id: Optional[int],
    cleanup_template_id: Optional[int]
) -> Dict[str, Any]:
    snap = {}
    if venue_template_id:
        t = get_template(db, venue_template_id)
        if t:
            snap["venue_template_id"] = t.id
            snap["venue_template_name"] = t.name
            snap["venue_template_version"] = t.version
            snap["venue_template_config"] = _json_loads_safe(t.config_json, {})
    if group_template_id:
        t = get_template(db, group_template_id)
        if t:
            snap["group_template_id"] = t.id
            snap["group_template_name"] = t.name
            snap["group_template_version"] = t.version
            snap["group_template_config"] = _json_loads_safe(t.config_json, {})
    if checklist_template_id:
        t = get_template(db, checklist_template_id)
        if t:
            snap["checklist_template_id"] = t.id
            snap["checklist_template_name"] = t.name
            snap["checklist_template_version"] = t.version
            snap["checklist_template_config"] = _json_loads_safe(t.config_json, {})
    if cleanup_template_id:
        t = get_template(db, cleanup_template_id)
        if t:
            snap["cleanup_template_id"] = t.id
            snap["cleanup_template_name"] = t.name
            snap["cleanup_template_version"] = t.version
            snap["cleanup_template_config"] = _json_loads_safe(t.config_json, {})
    return snap


def _populate_members_from_template(
    db: Session,
    schedule_id: int,
    group_template_id: Optional[int]
) -> None:
    if not group_template_id:
        return
    t = get_template(db, group_template_id)
    if not t:
        return
    cfg = _json_loads_safe(t.config_json, {})
    groups = cfg.get("groups", [])
    for grp in groups:
        gname = grp.get("name", "")
        members = grp.get("members", [])
        for mid in members:
            u = db.query(User).filter(User.id == mid).first()
            if not u:
                continue
            exists = db.query(ScheduleMember).filter(
                ScheduleMember.schedule_id == schedule_id,
                ScheduleMember.user_id == mid
            ).first()
            if exists:
                if gname and not exists.group_name:
                    exists.group_name = gname
                continue
            sm = ScheduleMember(
                schedule_id=schedule_id,
                user_id=mid,
                group_name=gname,
                role_in_schedule="participant"
            )
            db.add(sm)
    db.flush()


def _add_audit_log(
    db: Session,
    schedule_id: int,
    user_id: int,
    action: str,
    old_value: Dict = None,
    new_value: Dict = None,
    change_note: str = "",
    ip_address: str = ""
) -> None:
    log = ScheduleAuditLog(
        schedule_id=schedule_id,
        user_id=user_id,
        action=action,
        old_value=_json_dumps_safe(old_value or {}),
        new_value=_json_dumps_safe(new_value or {}),
        change_note=change_note,
        ip_address=ip_address
    )
    db.add(log)
    db.flush()


def create_schedule(
    db: Session,
    data: DrillScheduleCreate,
    creator_id: int,
    ip_address: str = ""
) -> DrillSchedule:
    conflicts = detect_schedule_conflicts(
        db,
        schedule_date=data.schedule_date,
        start_time=data.start_time,
        end_time=data.end_time,
        venue_id=data.venue_id
    )

    v = db.query(Venue).filter(Venue.id == data.venue_id).first()
    if not v:
        raise ValueError(f"场地ID {data.venue_id} 不存在")
    if not v.is_active:
        raise ValueError(f"场地 '{v.name}' 未启用")

    if _time_to_minutes(data.end_time) <= _time_to_minutes(data.start_time):
        raise ValueError("结束时间必须晚于开始时间")

    if data.venue_template_id:
        vt = get_template(db, data.venue_template_id)
        if not vt:
            raise ValueError(f"场地模板ID {data.venue_template_id} 不存在")
        if not vt.is_active:
            raise ValueError(f"场地模板 '{vt.name}' 未启用")
        if vt.template_type != "venue":
            raise ValueError(f"场地模板类型不正确")
    if data.group_template_id:
        gt = get_template(db, data.group_template_id)
        if not gt:
            raise ValueError(f"分组模板ID {data.group_template_id} 不存在")
        if not gt.is_active:
            raise ValueError(f"分组模板 '{gt.name}' 未启用")
        if gt.template_type != "group":
            raise ValueError(f"分组模板类型不正确")
    if data.checklist_template_id:
        ct = get_template(db, data.checklist_template_id)
        if not ct:
            raise ValueError(f"检查清单模板ID {data.checklist_template_id} 不存在")
        if ct.template_type != "checklist":
            raise ValueError(f"检查清单模板类型不正确")
    if data.cleanup_template_id:
        clt = get_template(db, data.cleanup_template_id)
        if not clt:
            raise ValueError(f"清理规则模板ID {data.cleanup_template_id} 不存在")
        if clt.template_type != "cleanup":
            raise ValueError(f"清理规则模板类型不正确")
    if data.drill_script_id:
        ds = db.query(DrillScript).filter(DrillScript.id == data.drill_script_id).first()
        if not ds:
            raise ValueError(f"演练剧本ID {data.drill_script_id} 不存在")

    template_snapshot = _build_template_snapshot(
        db,
        data.venue_template_id,
        data.group_template_id,
        data.checklist_template_id,
        data.cleanup_template_id
    )

    s = DrillSchedule(
        schedule_no=_create_schedule_no(),
        title=data.title.strip(),
        status="draft",
        schedule_date=data.schedule_date,
        start_time=data.start_time,
        end_time=data.end_time,
        venue_id=data.venue_id,
        venue_template_id=data.venue_template_id,
        group_template_id=data.group_template_id,
        checklist_template_id=data.checklist_template_id,
        cleanup_template_id=data.cleanup_template_id,
        template_snapshot=_json_dumps_safe(template_snapshot),
        drill_script_id=data.drill_script_id,
        conflict_details=_json_dumps_safe(conflicts),
        notes=data.notes,
        created_by=creator_id
    )
    db.add(s)
    db.flush()

    if data.auto_generate_members and data.group_template_id:
        _populate_members_from_template(db, s.id, data.group_template_id)

    _add_audit_log(
        db, s.id, creator_id, "create",
        new_value={
            "title": s.title,
            "schedule_date": str(s.schedule_date),
            "start_time": str(s.start_time),
            "end_time": str(s.end_time),
            "venue_id": s.venue_id
        },
        change_note="创建排期",
        ip_address=ip_address
    )

    return s


def update_schedule(
    db: Session,
    s: DrillSchedule,
    data: DrillScheduleUpdate,
    operator_id: int,
    ip_address: str = ""
) -> DrillSchedule:
    if s.status in ["locked", "executing", "completed"]:
        raise ValueError(f"排期状态为'{SCHEDULE_STATUS_NAMES.get(s.status, s.status)}'，不能修改")
    if s.status == "cancelled":
        raise ValueError("排期已撤销，不能修改")

    if s.status == "published":
        changed_fields = []
        if data.title is not None and data.title != s.title:
            changed_fields.append("title")
        if data.notes is not None and data.notes != s.notes:
            changed_fields.append("notes")
        core_changed = (
            data.schedule_date is not None or
            data.start_time is not None or
            data.end_time is not None or
            data.venue_id is not None
        )
        if core_changed:
            raise ValueError("已发布排期不能修改时间和场地，如需修改请先撤销再编辑")

    old_value = {
        "title": s.title,
        "schedule_date": str(s.schedule_date),
        "start_time": str(s.start_time),
        "end_time": str(s.end_time),
        "venue_id": s.venue_id,
        "venue_template_id": s.venue_template_id,
        "group_template_id": s.group_template_id,
        "checklist_template_id": s.checklist_template_id,
        "cleanup_template_id": s.cleanup_template_id,
        "drill_script_id": s.drill_script_id,
        "notes": s.notes
    }

    if data.title is not None:
        s.title = data.title.strip()
    if data.notes is not None:
        s.notes = data.notes

    need_recheck_conflicts = False
    new_schedule_date = s.schedule_date
    new_start_time = s.start_time
    new_end_time = s.end_time
    new_venue_id = s.venue_id

    if s.status != "published":
        if data.schedule_date is not None:
            new_schedule_date = data.schedule_date
            need_recheck_conflicts = True
        if data.start_time is not None:
            new_start_time = data.start_time
            need_recheck_conflicts = True
        if data.end_time is not None:
            new_end_time = data.end_time
            need_recheck_conflicts = True
        if data.venue_id is not None:
            new_venue_id = data.venue_id
            need_recheck_conflicts = True

    if need_recheck_conflicts:
        if _time_to_minutes(new_end_time) <= _time_to_minutes(new_start_time):
            raise ValueError("结束时间必须晚于开始时间")
        v = db.query(Venue).filter(Venue.id == new_venue_id).first()
        if not v:
            raise ValueError(f"场地不存在")
        conflicts = detect_schedule_conflicts(
            db,
            schedule_date=new_schedule_date,
            start_time=new_start_time,
            end_time=new_end_time,
            venue_id=new_venue_id,
            exclude_schedule_id=s.id
        )
        s.schedule_date = new_schedule_date
        s.start_time = new_start_time
        s.end_time = new_end_time
        s.venue_id = new_venue_id
        s.conflict_details = _json_dumps_safe(conflicts)

    old_snapshot = _json_loads_safe(s.template_snapshot, {})
    tpl_changed = False
    if data.venue_template_id is not None and data.venue_template_id != s.venue_template_id:
        s.venue_template_id = data.venue_template_id
        tpl_changed = True
    if data.group_template_id is not None and data.group_template_id != s.group_template_id:
        s.group_template_id = data.group_template_id
        tpl_changed = True
    if data.checklist_template_id is not None and data.checklist_template_id != s.checklist_template_id:
        s.checklist_template_id = data.checklist_template_id
        tpl_changed = True
    if data.cleanup_template_id is not None and data.cleanup_template_id != s.cleanup_template_id:
        s.cleanup_template_id = data.cleanup_template_id
        tpl_changed = True
    if data.drill_script_id is not None and data.drill_script_id != s.drill_script_id:
        s.drill_script_id = data.drill_script_id

    if tpl_changed and s.status != "published":
        new_snapshot = _build_template_snapshot(
            db,
            s.venue_template_id, s.group_template_id,
            s.checklist_template_id, s.cleanup_template_id
        )
        for k, v in old_snapshot.items():
            if k not in new_snapshot:
                new_snapshot[k] = v
        s.template_snapshot = _json_dumps_safe(new_snapshot)

        if s.group_template_id:
            _populate_members_from_template(db, s.id, s.group_template_id)

    new_value = {
        "title": s.title,
        "schedule_date": str(s.schedule_date),
        "start_time": str(s.start_time),
        "end_time": str(s.end_time),
        "venue_id": s.venue_id,
        "venue_template_id": s.venue_template_id,
        "group_template_id": s.group_template_id,
        "checklist_template_id": s.checklist_template_id,
        "cleanup_template_id": s.cleanup_template_id,
        "drill_script_id": s.drill_script_id,
        "notes": s.notes
    }

    _add_audit_log(
        db, s.id, operator_id, "update",
        old_value=old_value, new_value=new_value,
        change_note="修改排期",
        ip_address=ip_address
    )

    return s


def publish_schedule(
    db: Session,
    s: DrillSchedule,
    operator_id: int,
    ip_address: str = ""
) -> Dict[str, Any]:
    if s.status == "published":
        raise ValueError("排期已发布")
    if s.status == "cancelled":
        raise ValueError("排期已撤销，不能发布")
    if s.status in ["locked", "executing", "completed"]:
        raise ValueError(f"排期状态为'{SCHEDULE_STATUS_NAMES.get(s.status, s.status)}'，不能发布")

    conflicts = detect_schedule_conflicts(
        db, s.schedule_date, s.start_time, s.end_time, s.venue_id,
        exclude_schedule_id=s.id
    )
    if conflicts:
        s.conflict_details = _json_dumps_safe(conflicts)
        db.flush()
        raise ValueError(f"发布失败: 存在 {len(conflicts)} 个冲突，请先解决冲突")

    snapshot = _json_loads_safe(s.template_snapshot, {})
    if not snapshot:
        snapshot = _build_template_snapshot(
            db,
            s.venue_template_id, s.group_template_id,
            s.checklist_template_id, s.cleanup_template_id
        )
        s.template_snapshot = _json_dumps_safe(snapshot)
        if s.group_template_id:
            _populate_members_from_template(db, s.id, s.group_template_id)

    prev_status = s.status
    s.status = "published"
    s.published_by = operator_id
    s.published_at = datetime.utcnow()

    _add_audit_log(
        db, s.id, operator_id, "publish",
        old_value={"status": prev_status},
        new_value={"status": "published"},
        change_note="发布排期",
        ip_address=ip_address
    )

    return {
        "success": True,
        "schedule_no": s.schedule_no,
        "previous_status": prev_status,
        "current_status": "published",
        "message": "排期已发布"
    }


def lock_schedule(
    db: Session,
    s: DrillSchedule,
    operator_id: int,
    ip_address: str = ""
) -> Dict[str, Any]:
    if s.status != "published":
        raise ValueError("只能锁定已发布的排期")
    prev_status = s.status
    s.status = "locked"
    s.locked_by = operator_id
    s.locked_at = datetime.utcnow()

    _add_audit_log(
        db, s.id, operator_id, "lock",
        old_value={"status": prev_status},
        new_value={"status": "locked"},
        change_note="锁定排期",
        ip_address=ip_address
    )
    return {
        "success": True,
        "schedule_no": s.schedule_no,
        "previous_status": prev_status,
        "current_status": "locked",
        "message": "排期已锁定"
    }


def unlock_schedule(
    db: Session,
    s: DrillSchedule,
    operator_id: int,
    ip_address: str = ""
) -> Dict[str, Any]:
    if s.status != "locked":
        raise ValueError("只能解锁已锁定的排期")
    prev_status = s.status
    s.status = "published"
    s.locked_by = None
    s.locked_at = None

    _add_audit_log(
        db, s.id, operator_id, "unlock",
        old_value={"status": prev_status},
        new_value={"status": "published"},
        change_note="解锁排期",
        ip_address=ip_address
    )
    return {
        "success": True,
        "schedule_no": s.schedule_no,
        "previous_status": prev_status,
        "current_status": "published",
        "message": "排期已解锁"
    }


def cancel_schedule(
    db: Session,
    s: DrillSchedule,
    operator_id: int,
    reason: str = "",
    ip_address: str = ""
) -> Dict[str, Any]:
    if s.status == "cancelled":
        raise ValueError("排期已撤销")
    if s.status == "executing":
        raise ValueError("排期正在执行中，请等执行结束后再撤销")

    prev_status = s.status
    s.status = "cancelled"
    s.cancelled_by = operator_id
    s.cancelled_at = datetime.utcnow()
    if reason:
        s.notes = (s.notes or "") + (f"\n[撤销原因] {reason}" if s.notes else f"[撤销原因] {reason}")

    cleanup_result = _cleanup_schedule_resources(db, s)

    _add_audit_log(
        db, s.id, operator_id, "cancel",
        old_value={"status": prev_status},
        new_value={"status": "cancelled", "cleanup": cleanup_result},
        change_note=f"撤销排期: {reason}" if reason else "撤销排期",
        ip_address=ip_address
    )
    return {
        "success": True,
        "schedule_no": s.schedule_no,
        "previous_status": prev_status,
        "current_status": "cancelled",
        "message": f"排期已撤销，清理数据: 样本{cleanup_result['samples']}条, 临时文件{cleanup_result['temp_files']}个, 占位记录{cleanup_result['placeholders']}条"
    }


def copy_schedule(
    db: Session,
    s: DrillSchedule,
    operator_id: int,
    new_date: Optional[date] = None,
    ip_address: str = "",
    new_start_time: Optional[time] = None,
    new_end_time: Optional[time] = None
) -> Dict[str, Any]:
    target_date = new_date or s.schedule_date
    target_start_time = new_start_time or s.start_time
    target_end_time = new_end_time or s.end_time
    conflicts = detect_schedule_conflicts(
        db, target_date, target_start_time, target_end_time, s.venue_id
    )

    new_s = DrillSchedule(
        schedule_no=_create_schedule_no(),
        title=f"{s.title} (副本)",
        status="draft",
        schedule_date=target_date,
        start_time=target_start_time,
        end_time=target_end_time,
        venue_id=s.venue_id,
        venue_template_id=s.venue_template_id,
        group_template_id=s.group_template_id,
        checklist_template_id=s.checklist_template_id,
        cleanup_template_id=s.cleanup_template_id,
        template_snapshot=s.template_snapshot,
        drill_script_id=s.drill_script_id,
        conflict_details=_json_dumps_safe(conflicts),
        notes=(s.notes or "") + (f"\n[复制来源] {s.schedule_no}" if s.notes else f"[复制来源] {s.schedule_no}"),
        created_by=operator_id
    )
    db.add(new_s)
    db.flush()

    members = db.query(ScheduleMember).filter(
        ScheduleMember.schedule_id == s.id
    ).all()
    for sm in members:
        db.add(ScheduleMember(
            schedule_id=new_s.id,
            user_id=sm.user_id,
            group_name=sm.group_name,
            role_in_schedule=sm.role_in_schedule
        ))

    _add_audit_log(
        db, new_s.id, operator_id, "copy",
        old_value={"source_schedule_no": s.schedule_no},
        new_value={"schedule_no": new_s.schedule_no},
        change_note=f"从排期 {s.schedule_no} 复制",
        ip_address=ip_address
    )

    return {
        "success": True,
        "original_schedule_no": s.schedule_no,
        "new_schedule_no": new_s.schedule_no,
        "new_schedule_id": new_s.id,
        "message": f"已复制为新排期 {new_s.schedule_no}" + (f"，检测到{len(conflicts)}个冲突" if conflicts else "")
    }


# ============================================================================
# 执行批次生成 & 成员视图 & 审计日志
# ============================================================================

def generate_execution_batch(
    db: Session,
    s: DrillSchedule,
    operator_id: int,
    ip_address: str = ""
) -> Dict[str, Any]:
    if s.status not in ["published", "locked"]:
        raise ValueError(f"排期状态为'{SCHEDULE_STATUS_NAMES.get(s.status, s.status)}'，不能生成执行批次")
    if s.batch_id:
        raise ValueError(f"排期已关联批次: {s.batch_id}，请勿重复生成")
    if not s.drill_script_id:
        raise ValueError("排期未关联演练剧本，无法生成执行批次")

    script = db.query(DrillScript).filter(DrillScript.id == s.drill_script_id).first()
    if not script:
        raise ValueError("关联的演练剧本不存在")
    if not script.is_active:
        raise ValueError("关联的演练剧本未启用")

    member_ids = []
    sms = db.query(ScheduleMember).filter(ScheduleMember.schedule_id == s.id).all()
    for sm in sms:
        member_ids.append(sm.user_id)

    try:
        from drill_script_center import _create_batch_id, _load_script_data
        batch_id = _create_batch_id()

        snapshot = _load_script_data(script)
        snapshot["schedule_info"] = {
            "schedule_no": s.schedule_no,
            "schedule_date": str(s.schedule_date),
            "start_time": str(s.start_time),
            "end_time": str(s.end_time),
            "venue_name": s.venue.name if s.venue else "",
            "venue_id": s.venue_id,
            "template_snapshot": _json_loads_safe(s.template_snapshot, {})
        }

        batch = DrillBatch(
            batch_id=batch_id,
            script_id=script.id,
            script_name=script.name,
            script_snapshot=_json_dumps_safe(snapshot),
            status="pending",
            venue_id=s.venue_id,
            created_by=operator_id,
            participant_user_ids=_json_dumps_safe(member_ids)
        )
        db.add(batch)
        db.flush()

        s.batch_id = batch_id
        s.status = "executing"
        s.executed_at = datetime.utcnow()

        ph = SchedulePlaceholder(
            schedule_id=s.id,
            placeholder_type="sample_data",
            reference_key=f"batch_{batch_id}",
            data_json=_json_dumps_safe({"batch_id": batch_id, "script_id": script.id}),
            file_path=""
        )
        db.add(ph)
        db.flush()

        _add_audit_log(
            db, s.id, operator_id, "generate_batch",
            old_value={"batch_id": None, "status": s.status},
            new_value={"batch_id": batch_id, "status": "executing"},
            change_note=f"生成执行批次 {batch_id}",
            ip_address=ip_address
        )

        return {
            "success": True,
            "schedule_no": s.schedule_no,
            "batch_id": batch_id,
            "message": f"已生成执行批次 {batch_id}"
        }
    except ImportError as e:
        raise ValueError(f"生成批次失败: 缺少依赖模块 {e}")
    except Exception as e:
        raise ValueError(f"生成批次失败: {e}")


def get_schedule_members(db: Session, schedule_id: int) -> List[Dict[str, Any]]:
    items = db.query(ScheduleMember).filter(
        ScheduleMember.schedule_id == schedule_id
    ).order_by(ScheduleMember.group_name, ScheduleMember.joined_at).all()
    return [_schedule_member_to_dict(x) for x in items]


def get_member_personal_view(
    db: Session,
    s: DrillSchedule,
    user_id: int
) -> Dict[str, Any]:
    sm = db.query(ScheduleMember).filter(
        ScheduleMember.schedule_id == s.id,
        ScheduleMember.user_id == user_id
    ).first()
    if not sm:
        raise ValueError("您不是此排期的成员")

    checklist_items = []
    snapshot = _json_loads_safe(s.template_snapshot, {})
    if snapshot.get("checklist_template_config"):
        items = snapshot["checklist_template_config"].get("items", [])
        result_map = _json_loads_safe(sm.result_data, {}).get("checklist", {})
        for item in items:
            checklist_items.append({
                "name": item.get("name", ""),
                "description": item.get("description", ""),
                "required": item.get("required", True),
                "checked": result_map.get(item.get("name", ""), False)
            })

    execution_entries = []
    if s.batch_id:
        try:
            from database import DrillArtifact
            arts = db.query(DrillArtifact).filter(
                DrillArtifact.batch_id == s.batch_id,
                (DrillArtifact.user_id == user_id) | (DrillArtifact.user_id.is_(None))
            ).all()
            for a in arts:
                execution_entries.append({
                    "type": a.artifact_type,
                    "title": a.title,
                    "content": a.content[:500] if a.content else "",
                    "created_at": a.created_at.isoformat() if a.created_at else None
                })
        except Exception:
            pass

    return {
        "schedule_id": s.id,
        "schedule_no": s.schedule_no,
        "title": s.title,
        "status": s.status,
        "schedule_date": s.schedule_date,
        "start_time": s.start_time,
        "end_time": s.end_time,
        "venue_name": s.venue.name if s.venue else "",
        "group_name": sm.group_name or "",
        "role_in_schedule": sm.role_in_schedule or "",
        "my_result": _json_loads_safe(sm.result_data, {}),
        "my_download_summary": sm.download_summary or "",
        "checklist_items": checklist_items,
        "execution_entries": execution_entries
    }


def list_schedule_audit_logs(
    db: Session,
    schedule_id: Optional[int] = None,
    action: Optional[str] = None,
    user_id: Optional[int] = None,
    page: int = 1,
    page_size: int = 100
) -> Tuple[List[Dict[str, Any]], int]:
    q = db.query(ScheduleAuditLog)
    if schedule_id:
        q = q.filter(ScheduleAuditLog.schedule_id == schedule_id)
    if action:
        q = q.filter(ScheduleAuditLog.action == action)
    if user_id:
        q = q.filter(ScheduleAuditLog.user_id == user_id)
    total = q.count()
    items = q.order_by(ScheduleAuditLog.created_at.desc()).offset(
        (page - 1) * page_size
    ).limit(page_size).all()
    return [_audit_log_to_dict(x) for x in items], total


# ============================================================================
# 清理 & 重启恢复
# ============================================================================

def _cleanup_schedule_resources(db: Session, s: DrillSchedule) -> Dict[str, int]:
    result = {"samples": 0, "temp_files": 0, "placeholders": 0}

    phs = db.query(SchedulePlaceholder).filter(
        SchedulePlaceholder.schedule_id == s.id
    ).all()
    for ph in phs:
        if ph.file_path and os.path.exists(ph.file_path):
            try:
                if os.path.isdir(ph.file_path):
                    shutil.rmtree(ph.file_path, ignore_errors=True)
                else:
                    os.remove(ph.file_path)
                result["temp_files"] += 1
            except Exception:
                pass
        if ph.placeholder_type in ("sample_data", "booking_placeholder", "waitlist_placeholder"):
            result["samples"] += 1
        db.delete(ph)
        result["placeholders"] += 1

    if s.batch_id:
        try:
            from database import DrillArtifact
            arts = db.query(DrillArtifact).filter(
                DrillArtifact.batch_id == s.batch_id
            ).all()
            for a in arts:
                if a.file_path and os.path.exists(a.file_path):
                    try:
                        os.remove(a.file_path)
                        result["temp_files"] += 1
                    except Exception:
                        pass
        except Exception:
            pass

    db.flush()
    return result


def manual_cleanup_schedule(
    db: Session,
    s: DrillSchedule,
    operator_id: int,
    ip_address: str = ""
) -> Dict[str, Any]:
    if s.status not in ["cancelled", "completed", "draft"]:
        raise ValueError("只能清理已撤销、已完成或草稿状态的排期")

    result = _cleanup_schedule_resources(db, s)

    _add_audit_log(
        db, s.id, operator_id, "cleanup",
        new_value=result,
        change_note="手动清理排期资源",
        ip_address=ip_address
    )

    return {
        "success": True,
        "schedule_no": s.schedule_no,
        "removed_samples": result["samples"],
        "removed_temp_files": result["temp_files"],
        "removed_placeholders": result["placeholders"],
        "message": f"清理完成: 样本{result['samples']}, 文件{result['temp_files']}, 占位{result['placeholders']}"
    }


def recover_pending_schedules_on_startup(db: Session) -> List[Dict[str, Any]]:
    results = []

    executing = db.query(DrillSchedule).filter(
        DrillSchedule.status == "executing"
    ).all()
    for s in executing:
        if not s.batch_id:
            s.status = "published"
            s.executed_at = None
            results.append({
                "schedule_no": s.schedule_no,
                "recovered": True,
                "previous_status": "executing",
                "current_status": "published",
                "message": "检测到未生成批次的执行中排期，已恢复为已发布状态"
            })
            continue
        try:
            batch = db.query(DrillBatch).filter(
                DrillBatch.batch_id == s.batch_id
            ).first()
            if batch and batch.status in ("pending", "recovering", "running"):
                try:
                    from drill_script_center import recover_batch
                    r = recover_batch(db, batch)
                    results.append({
                        "schedule_no": s.schedule_no,
                        "recovered": True,
                        "previous_status": "executing",
                        "current_status": "executing",
                        "message": f"关联批次 {s.batch_id}: {r.get('message', '已标记恢复')}"
                    })
                except Exception as e:
                    results.append({
                        "schedule_no": s.schedule_no,
                        "recovered": False,
                        "previous_status": "executing",
                        "current_status": "executing",
                        "message": f"恢复批次 {s.batch_id} 失败: {e}"
                    })
            elif batch and batch.status in ("completed", "failed"):
                s.status = "completed"
                results.append({
                    "schedule_no": s.schedule_no,
                    "recovered": True,
                    "previous_status": "executing",
                    "current_status": "completed",
                    "message": f"关联批次 {s.batch_id} 已执行完毕，排期标记为完成"
                })
            elif batch and batch.status == "rolled_back":
                s.status = "cancelled"
                s.cancelled_at = datetime.utcnow()
                results.append({
                    "schedule_no": s.schedule_no,
                    "recovered": True,
                    "previous_status": "executing",
                    "current_status": "cancelled",
                    "message": f"关联批次 {s.batch_id} 已回滚，排期标记为撤销"
                })
            else:
                results.append({
                    "schedule_no": s.schedule_no,
                    "recovered": False,
                    "previous_status": "executing",
                    "current_status": "executing",
                    "message": f"关联批次 {s.batch_id} 状态不明，需人工处理"
                })
        except Exception as e:
            results.append({
                "schedule_no": s.schedule_no,
                "recovered": False,
                "previous_status": "executing",
                "current_status": "executing",
                "message": f"恢复异常: {e}"
            })

    db.flush()
    return results


# ============================================================================
# 按模板批量生成日历
# ============================================================================

def generate_schedules_from_template(
    db: Session,
    venue_template_id: Optional[int] = None,
    start_date: date = None,
    end_date: date = None,
    creator_id: int = 0,
    title_prefix: str = "演练",
    drill_script_id: Optional[int] = None,
    group_template_id: Optional[int] = None,
    checklist_template_id: Optional[int] = None,
    cleanup_template_id: Optional[int] = None,
    ip_address: str = "",
    venue_id: Optional[int] = None,
    daily_start_time: str = "09:00:00",
    daily_end_time: str = "11:00:00",
    exclude_weekends: bool = True
) -> List[Any]:
    cfg = {}
    venue_ids = []
    time_slots = []

    if venue_template_id:
        vt = get_template(db, venue_template_id)
        if vt and vt.template_type == "venue":
            cfg = _json_loads_safe(vt.config_json, {})
            venue_ids = cfg.get("venue_ids", [])
            time_slots = cfg.get("time_slots", [])

    if venue_id and venue_id not in venue_ids:
        venue_ids = [venue_id] + venue_ids

    if not venue_ids:
        raise ValueError("未指定任何场地，请传 venue_id 或使用有效的场地模板")

    if not time_slots:
        sh, sm = 0, 0
        eh, em = 0, 0
        try:
            sh, sm = map(int, daily_start_time.split(":")[:2])
            eh, em = map(int, daily_end_time.split(":")[:2])
        except Exception:
            sh, sm = 9, 0
            eh, em = 11, 0
        time_slots = [
            {"start": f"{sh:02d}:{sm:02d}", "end": f"{eh:02d}:{em:02d}"}
        ]

    created = []
    skipped = []

    d = start_date
    while d <= end_date:
        if exclude_weekends and d.weekday() >= 5:
            d += timedelta(days=1)
            continue
        for vid in venue_ids:
            for slot in time_slots:
                try:
                    start_str = slot.get("start", "09:00")
                    end_str = slot.get("end", "12:00")
                    sh, sm = map(int, start_str.split(":"))
                    eh, em = map(int, end_str.split(":"))
                    st = time(hour=sh, minute=sm)
                    et = time(hour=eh, minute=em)

                    conflicts = detect_schedule_conflicts(db, d, st, et, vid)
                    if conflicts:
                        skipped.append({
                            "date": str(d),
                            "venue_id": vid,
                            "slot": f"{start_str}-{end_str}",
                            "reason": f"{len(conflicts)}个冲突"
                        })
                        continue

                    data = DrillScheduleCreate(
                        title=f"{title_prefix} {d.strftime('%m-%d')} {start_str}-{end_str}",
                        schedule_date=d,
                        start_time=st,
                        end_time=et,
                        venue_id=vid,
                        venue_template_id=venue_template_id,
                        group_template_id=group_template_id,
                        checklist_template_id=checklist_template_id,
                        cleanup_template_id=cleanup_template_id,
                        drill_script_id=drill_script_id,
                        notes="",
                        auto_generate_members=True
                    )
                    s = create_schedule(db, data, creator_id, ip_address)
                    created.append(s)
                except Exception as e:
                    skipped.append({
                        "date": str(d),
                        "venue_id": vid,
                        "slot": slot,
                        "reason": str(e)
                    })
        d += timedelta(days=1)

    return created


# ============================================================================
# 删除排期（带审计和清理）
# ============================================================================

def delete_schedule(
    db: Session,
    s: DrillSchedule,
    operator_id: int,
    ip_address: str = ""
) -> Dict[str, Any]:
    # 先清理关联资源
    try:
        manual_cleanup_schedule(db, s, operator_id, ip_address)
    except Exception:
        pass

    # 删除成员关联
    db.query(ScheduleMember).filter(ScheduleMember.schedule_id == s.id).delete(synchronize_session=False)

    # 保留审计日志（合规需要），但标记为 deleted
    _add_audit_log(
        db, s.id, operator_id, "delete",
        old_value={
            "schedule_no": s.schedule_no,
            "title": s.title,
            "status": s.status,
            "schedule_date": str(s.schedule_date)
        },
        new_value={"deleted": True},
        change_note="管理员删除排期",
        ip_address=ip_address
    )

    # 删除排期主记录
    db.delete(s)
    return {"success": True, "schedule_no": s.schedule_no}
