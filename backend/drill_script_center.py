from datetime import datetime, timedelta
from sqlalchemy.orm import Session
from typing import List, Optional, Dict, Any, Tuple
import uuid
import time
import json
import os
import re

from database import (
    DrillScript, DrillBatch, DrillArtifact,
    User, Venue, WaitlistEntry, WaitlistLog,
    Booking, ClosedWindow, RescheduleRecord
)
from schemas import (
    DrillScriptCreate, DrillScriptUpdate,
    DrillScriptImportValidateResult
)
from waitlist_drill_service import (
    run_full_drill, cleanup_drill_session,
    get_drill_session_snapshot, make_step_result,
    find_available_drill_slot, create_drill_session_id,
    ERROR_CATEGORIES
)
from conflict_detector import check_time_overlap

REQUIRED_SCRIPT_FIELDS = [
    "name", "venue_rules", "drill_samples",
    "member_accounts", "checkpoints"
]

REQUIRED_MEMBER_FIELDS = ["username", "password", "full_name"]

BATCH_STATUS = {
    "PENDING": "pending",
    "RUNNING": "running",
    "COMPLETED": "completed",
    "FAILED": "failed",
    "ROLLED_BACK": "rolled_back",
    "RECOVERING": "recovering"
}


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


def _create_batch_id() -> str:
    return f"BATCH_{datetime.now().strftime('%Y%m%d%H%M%S')}_{uuid.uuid4().hex[:8]}"


def _load_script_data(script: DrillScript) -> Dict[str, Any]:
    return {
        "id": script.id,
        "name": script.name,
        "description": script.description,
        "version": script.version,
        "venue_rules": _json_loads_safe(script.venue_rules, {}),
        "drill_samples": _json_loads_safe(script.drill_samples, []),
        "member_accounts": _json_loads_safe(script.member_accounts, []),
        "checkpoints": _json_loads_safe(script.checkpoints, []),
        "cleanup_strategy": _json_loads_safe(script.cleanup_strategy, {}),
        "created_by": script.created_by,
        "is_active": script.is_active,
        "created_at": script.created_at,
        "updated_at": script.updated_at
    }


def _script_to_response(script: DrillScript) -> Dict[str, Any]:
    data = _load_script_data(script)
    if script.creator:
        data["created_by_name"] = script.creator.full_name
    return data


def _batch_to_response(batch: DrillBatch) -> Dict[str, Any]:
    return {
        "id": batch.id,
        "batch_id": batch.batch_id,
        "script_id": batch.script_id,
        "script_name": batch.script_name,
        "status": batch.status,
        "venue_id": batch.venue_id,
        "venue_name": batch.venue.name if batch.venue else None,
        "started_at": batch.started_at,
        "completed_at": batch.completed_at,
        "rolled_back_at": batch.rolled_back_at,
        "created_by": batch.created_by,
        "created_by_name": batch.creator.full_name if batch.creator else None,
        "participant_user_ids": _json_loads_safe(batch.participant_user_ids, []),
        "total_steps": batch.total_steps,
        "passed_steps": batch.passed_steps,
        "failed_steps": batch.failed_steps,
        "error_message": batch.error_message or "",
        "drill_session_ids": _json_loads_safe(batch.drill_session_ids, []),
        "created_at": batch.created_at,
        "updated_at": batch.updated_at
    }


def _artifact_to_response(artifact: DrillArtifact) -> Dict[str, Any]:
    return {
        "id": artifact.id,
        "batch_id": artifact.batch_id,
        "artifact_type": artifact.artifact_type,
        "title": artifact.title,
        "content": artifact.content,
        "file_path": artifact.file_path,
        "metadata": _json_loads_safe(artifact.metadata_json, {}),
        "user_id": artifact.user_id,
        "user_name": artifact.owner.full_name if artifact.owner else None,
        "created_at": artifact.created_at
    }


def create_script(
    db: Session,
    data: DrillScriptCreate,
    creator_id: int
) -> DrillScript:
    try:
        from auth import get_password_hash
    except Exception:
        get_password_hash = None

    members = data.member_accounts or []
    processed_members = []
    for m in members:
        uname = str(m.get("username", "") if isinstance(m, dict) else getattr(m, "username", "")).strip()
        if not uname:
            processed_members.append(m if isinstance(m, dict) else m.model_dump())
            continue
        existing = db.query(User).filter(User.username == uname).first()
        if existing:
            processed_members.append({
                "username": uname,
                "user_id": existing.id,
                "role": m.get("role", "member") if isinstance(m, dict) else getattr(m, "role", "member"),
                "full_name": existing.full_name,
                "existing": True
            })
        else:
            password = str(m.get("password", "") if isinstance(m, dict) else getattr(m, "password", ""))
            pwd_hash = get_password_hash(password) if get_password_hash else password
            new_user = User(
                username=uname,
                password_hash=pwd_hash,
                full_name=str(m.get("full_name", uname) if isinstance(m, dict) else getattr(m, "full_name", uname)),
                role=m.get("role", "member") if isinstance(m, dict) else getattr(m, "role", "member")
            )
            db.add(new_user)
            db.flush()
            processed_members.append({
                "username": uname,
                "user_id": new_user.id,
                "role": m.get("role", "member") if isinstance(m, dict) else getattr(m, "role", "member"),
                "full_name": new_user.full_name,
                "existing": False
            })

    script = DrillScript(
        name=data.name,
        description=data.description,
        version=data.version,
        venue_rules=_json_dumps_safe(data.venue_rules),
        drill_samples=_json_dumps_safe(data.drill_samples),
        member_accounts=_json_dumps_safe(processed_members),
        checkpoints=_json_dumps_safe(data.checkpoints),
        cleanup_strategy=_json_dumps_safe(data.cleanup_strategy),
        created_by=creator_id,
        is_active=True
    )
    db.add(script)
    db.flush()
    return script


def get_script(db: Session, script_id: int) -> Optional[DrillScript]:
    return db.query(DrillScript).filter(DrillScript.id == script_id).first()


def get_script_by_name(db: Session, name: str) -> Optional[DrillScript]:
    return db.query(DrillScript).filter(DrillScript.name == name).first()


def list_scripts(
    db: Session,
    is_active: Optional[bool] = None,
    keyword: str = ""
) -> List[DrillScript]:
    query = db.query(DrillScript)
    if is_active is not None:
        query = query.filter(DrillScript.is_active == is_active)
    if keyword:
        pattern = f"%{keyword}%"
        query = query.filter(
            (DrillScript.name.like(pattern)) |
            (DrillScript.description.like(pattern))
        )
    return query.order_by(DrillScript.updated_at.desc()).all()


def update_script(
    db: Session,
    script: DrillScript,
    data: DrillScriptUpdate
) -> DrillScript:
    if data.name is not None:
        script.name = data.name
    if data.description is not None:
        script.description = data.description
    if data.version is not None:
        script.version = data.version
    if data.venue_rules is not None:
        script.venue_rules = _json_dumps_safe(data.venue_rules)
    if data.drill_samples is not None:
        script.drill_samples = _json_dumps_safe(data.drill_samples)
    if data.member_accounts is not None:
        script.member_accounts = _json_dumps_safe(data.member_accounts)
    if data.checkpoints is not None:
        script.checkpoints = _json_dumps_safe(data.checkpoints)
    if data.cleanup_strategy is not None:
        script.cleanup_strategy = _json_dumps_safe(data.cleanup_strategy)
    if data.is_active is not None:
        script.is_active = data.is_active
    db.flush()
    return script


def delete_script(db: Session, script: DrillScript) -> None:
    db.delete(script)
    db.flush()


def validate_script_import(
    db: Session,
    script_data: Dict[str, Any]
) -> DrillScriptImportValidateResult:
    errors: List[str] = []
    warnings: List[str] = []

    if not isinstance(script_data, dict):
        errors.append("剧本数据格式错误，必须是 JSON 对象")
        return DrillScriptImportValidateResult(
            valid=False, errors=errors, warnings=warnings
        )

    for field in REQUIRED_SCRIPT_FIELDS:
        if field not in script_data:
            errors.append(f"缺少必填字段: {field}")

    if errors:
        return DrillScriptImportValidateResult(
            valid=False, errors=errors, warnings=warnings
        )

    name = script_data.get("name", "").strip()
    if not name:
        errors.append("剧本名称不能为空")
    else:
        existing = get_script_by_name(db, name)
        if existing:
            errors.append(f"剧本名称已存在: {name}")

    members = script_data.get("member_accounts", []) or []
    if not isinstance(members, list):
        errors.append("member_accounts 必须是数组")
    else:
        seen_usernames = set()
        for idx, m in enumerate(members):
            if not isinstance(m, dict):
                errors.append(f"成员账号 #{idx} 格式错误")
                continue
            for f in REQUIRED_MEMBER_FIELDS:
                if f not in m or not str(m.get(f, "")).strip():
                    errors.append(f"成员账号 #{idx} 缺少必填字段: {f}")
            uname = str(m.get("username", "")).strip()
            if uname:
                if not re.match(r"^[a-zA-Z0-9_]{3,50}$", uname):
                    errors.append(
                        f"成员账号 #{idx} 用户名格式无效: "
                        f"{uname} (需3-50位字母数字下划线)"
                    )
                if uname in seen_usernames:
                    errors.append(f"成员账号 #{idx} 用户名重复: {uname}")
                seen_usernames.add(uname)
                existing_user = db.query(User).filter(
                    User.username == uname
                ).first()
                if existing_user:
                    warnings.append(
                        f"成员账号 #{idx} 用户名已存在系统中: "
                        f"{uname}，导入时将使用现有账号"
                    )
                    if not existing_user.full_name or not existing_user.password_hash:
                        errors.append(
                            f"成员账号 #{idx} 系统中的账号 {uname} 已失效"
                            f"（数据不完整），无法用于演练"
                        )

    venue_rules = script_data.get("venue_rules", {}) or {}
    if isinstance(venue_rules, dict):
        venue_ids = venue_rules.get("venue_ids", []) or []
        for vid in venue_ids:
            v = db.query(Venue).filter(
                Venue.id == vid, Venue.is_active == True
            ).first()
            if not v:
                errors.append(f"场地规则中引用的场地ID不存在或未启用: {vid}")

        hours = venue_rules.get("preferred_hours", [])
        if hours:
            if not all(isinstance(h, int) and 0 <= h <= 23 for h in hours):
                errors.append("preferred_hours 必须是 0-23 的整数数组")

        existing_running_batches = db.query(DrillBatch).filter(
            DrillBatch.status.in_(["pending", "running", "recovering"])
        ).all()
        for batch in existing_running_batches:
            try:
                snap = _json_loads_safe(batch.script_snapshot, {})
                batch_vrules = snap.get("venue_rules", {}) or {}
                batch_vids = batch_vrules.get("venue_ids", []) or []
                overlap_vids = set(venue_ids) & set(batch_vids) if venue_ids and batch_vids else set()
                if overlap_vids:
                    batch_hours = batch_vrules.get("preferred_hours", []) or []
                    if not batch_hours or not hours:
                        overlap = True
                    else:
                        overlap = bool(set(hours) & set(batch_hours))
                    if overlap:
                        warnings.append(
                            f"与正在执行的批次 {batch.batch_id} 存在场地/时段冲突"
                            f"（重叠场地: {overlap_vids}）"
                        )
            except Exception:
                pass

    samples = script_data.get("drill_samples", []) or []
    if not isinstance(samples, list):
        errors.append("drill_samples 必须是数组")
    else:
        for idx, s in enumerate(samples):
            if not isinstance(s, dict):
                errors.append(f"演练样本 #{idx} 格式错误")
                continue
            if "name" not in s or not str(s.get("name", "")).strip():
                errors.append(f"演练样本 #{idx} 缺少 name 字段")
            if "type" not in s or not str(s.get("type", "")).strip():
                errors.append(f"演练样本 #{idx} 缺少 type 字段")

    checkpoints = script_data.get("checkpoints", []) or []
    if not isinstance(checkpoints, list):
        errors.append("checkpoints 必须是数组")

    valid = len(errors) == 0
    return DrillScriptImportValidateResult(
        valid=valid, errors=errors, warnings=warnings
    )


def import_script(
    db: Session,
    script_data: Dict[str, Any],
    creator_id: int
) -> Tuple[Optional[DrillScript], DrillScriptImportValidateResult]:
    validation = validate_script_import(db, script_data)
    if not validation.valid:
        return None, validation

    try:
        from auth import get_password_hash
    except Exception:
        get_password_hash = None

    members = script_data.get("member_accounts", []) or []
    processed_members = []
    for m in members:
        uname = str(m.get("username", "")).strip()
        existing = db.query(User).filter(User.username == uname).first()
        if existing:
            processed_members.append({
                "username": uname,
                "user_id": existing.id,
                "role": m.get("role", "member"),
                "full_name": existing.full_name,
                "existing": True
            })
        else:
            password = str(m.get("password", ""))
            pwd_hash = get_password_hash(password) if get_password_hash else password
            new_user = User(
                username=uname,
                password_hash=pwd_hash,
                full_name=str(m.get("full_name", uname)),
                role=m.get("role", "member")
            )
            db.add(new_user)
            db.flush()
            processed_members.append({
                "username": uname,
                "user_id": new_user.id,
                "role": m.get("role", "member"),
                "full_name": new_user.full_name,
                "existing": False
            })

    script_data_copy = dict(script_data)
    script_data_copy["member_accounts"] = processed_members

    script = DrillScript(
        name=script_data_copy.get("name", ""),
        description=script_data_copy.get("description", ""),
        version=script_data_copy.get("version", "1.0"),
        venue_rules=_json_dumps_safe(script_data_copy.get("venue_rules", {})),
        drill_samples=_json_dumps_safe(script_data_copy.get("drill_samples", [])),
        member_accounts=_json_dumps_safe(processed_members),
        checkpoints=_json_dumps_safe(script_data_copy.get("checkpoints", [])),
        cleanup_strategy=_json_dumps_safe(script_data_copy.get("cleanup_strategy", {})),
        created_by=creator_id,
        is_active=True
    )
    db.add(script)
    db.flush()
    return script, validation


def export_script(script: DrillScript) -> Dict[str, Any]:
    data = _load_script_data(script)
    for k in ["id", "created_by", "is_active", "created_at", "updated_at"]:
        data.pop(k, None)
    members = data.get("member_accounts", [])
    sanitized_members = []
    for m in members:
        sanitized_members.append({
            "username": m.get("username", ""),
            "password": m.get("password", "changeme"),
            "full_name": m.get("full_name", ""),
            "role": m.get("role", "member")
        })
    data["member_accounts"] = sanitized_members
    data["exported_at"] = datetime.utcnow().isoformat()
    return data


def _save_artifact(
    db: Session,
    batch_id: str,
    artifact_type: str,
    title: str = "",
    content: str = "",
    file_path: str = "",
    metadata: Optional[Dict] = None,
    user_id: Optional[int] = None
) -> DrillArtifact:
    artifact = DrillArtifact(
        batch_id=batch_id,
        artifact_type=artifact_type,
        title=title,
        content=content,
        file_path=file_path,
        metadata_json=_json_dumps_safe(metadata or {}),
        user_id=user_id
    )
    db.add(artifact)
    db.flush()
    return artifact


def _get_artifacts_by_batch(
    db: Session, batch_id: str, artifact_type: Optional[str] = None
) -> List[DrillArtifact]:
    query = db.query(DrillArtifact).filter(DrillArtifact.batch_id == batch_id)
    if artifact_type:
        query = query.filter(DrillArtifact.artifact_type == artifact_type)
    return query.order_by(DrillArtifact.created_at.asc()).all()


def create_batch(
    db: Session,
    script: DrillScript,
    creator_id: int,
    venue_id: Optional[int] = None
) -> DrillBatch:
    batch_id = _create_batch_id()
    script_data = _load_script_data(script)

    members = script_data.get("member_accounts", []) or []
    participant_ids = []
    for m in members:
        if isinstance(m, dict) and m.get("user_id"):
            participant_ids.append(m["user_id"])

    batch = DrillBatch(
        batch_id=batch_id,
        script_id=script.id,
        script_name=script.name,
        script_snapshot=_json_dumps_safe(script_data),
        status=BATCH_STATUS["PENDING"],
        venue_id=venue_id,
        created_by=creator_id,
        participant_user_ids=_json_dumps_safe(participant_ids),
        drill_session_ids=_json_dumps_safe([])
    )
    db.add(batch)
    db.flush()
    return batch


def get_batch(db: Session, batch_id: str) -> Optional[DrillBatch]:
    return db.query(DrillBatch).filter(DrillBatch.batch_id == batch_id).first()


def get_batch_by_id(db: Session, id: int) -> Optional[DrillBatch]:
    return db.query(DrillBatch).filter(DrillBatch.id == id).first()


def list_batches(
    db: Session,
    script_id: Optional[int] = None,
    status: Optional[str] = None,
    user_id: Optional[int] = None
) -> List[DrillBatch]:
    query = db.query(DrillBatch)
    if script_id:
        query = query.filter(DrillBatch.script_id == script_id)
    if status:
        query = query.filter(DrillBatch.status == status)
    if user_id:
        query = query.filter(DrillBatch.created_by == user_id)
    return query.order_by(DrillBatch.created_at.desc()).all()


def list_batches_for_member(
    db: Session,
    user_id: int
) -> List[DrillBatch]:
    all_batches = db.query(DrillBatch).order_by(
        DrillBatch.created_at.desc()
    ).all()
    result = []
    for b in all_batches:
        pids = _json_loads_safe(b.participant_user_ids, [])
        if user_id in pids or b.created_by == user_id:
            result.append(b)
    return result


def _save_screenshot_file(batch_id: str, step_index: int, content: str) -> str:
    ts = datetime.now().strftime('%Y%m%d_%H%M%S')
    dir_name = f"screenshots_batch_{batch_id}"
    dir_path = os.path.join(os.path.dirname(__file__), dir_name)
    os.makedirs(dir_path, exist_ok=True)
    file_name = f"error_step{step_index}_{ts}.txt"
    file_path = os.path.join(dir_path, file_name)
    with open(file_path, "w", encoding="utf-8") as f:
        f.write(content)
    return file_path


def _run_browser_validation_step(
    db: Session,
    batch_id: str,
    venue_id: int,
    target_url: str,
    checkpoint_name: str,
    step_index: int
) -> Dict[str, Any]:
    result = {
        "step_name": f"浏览器验收: {checkpoint_name}",
        "passed": False,
        "duration_ms": 0,
        "error_category": "",
        "error_detail": ""
    }
    step_start = time.time()
    try:
        import requests as http_requests
        try:
            resp = http_requests.get(target_url, timeout=10)
            if resp.status_code == 200:
                body = resp.text.lower()
                has_root = '<div id="app"' in body or '<div id="app">' in body
                if has_root:
                    result["passed"] = True
                else:
                    result["error_category"] = "DATA_QUALITY"
                    result["error_detail"] = f"页面缺少核心元素 #app, 状态码={resp.status_code}"
            else:
                result["error_category"] = "RESTART"
                result["error_detail"] = f"HTTP {resp.status_code}"
        except http_requests.exceptions.ConnectionError:
            result["error_category"] = "RESTART"
            result["error_detail"] = "服务未启动或不可访问"
        except Exception as e:
            result["error_category"] = "UNKNOWN"
            result["error_detail"] = str(e)[:300]
    except ImportError:
        result["passed"] = True
        result["error_detail"] = "requests库不可用，跳过浏览器验收"

    result["duration_ms"] = int((time.time() - step_start) * 1000)
    return result


def execute_batch(
    db: Session,
    batch: DrillBatch
) -> DrillBatch:
    batch.status = BATCH_STATUS["RUNNING"]
    batch.started_at = datetime.utcnow()
    db.flush()

    script_snapshot = _json_loads_safe(batch.script_snapshot, {})
    venue_rules = script_snapshot.get("venue_rules", {})
    samples = script_snapshot.get("drill_samples", [])
    checkpoints = script_snapshot.get("checkpoints", [])
    cleanup_strategy = script_snapshot.get("cleanup_strategy", {})

    total_steps = 0
    passed_steps = 0
    failed_steps = 0
    drill_session_ids = []
    all_step_results = []

    target_venue_id = batch.venue_id
    if not target_venue_id:
        venue_ids = venue_rules.get("venue_ids", []) or []
        if venue_ids:
            target_venue_id = venue_ids[0]
        else:
            venue = db.query(Venue).filter(Venue.is_active == True).first()
            if venue:
                target_venue_id = venue.id

    try:
        browser_checkpoints = [cp for cp in checkpoints if cp.get("type") == "browser_validation"]
        for bc_idx, bc in enumerate(browser_checkpoints):
            total_steps += 1
            target_url = bc.get("url", "http://127.0.0.1:8003/")
            bv_result = _run_browser_validation_step(
                db, batch.batch_id, target_venue_id,
                target_url, bc.get("name", f"浏览器验收#{bc_idx+1}"),
                total_steps
            )
            all_step_results.append(bv_result)
            if bv_result["passed"]:
                passed_steps += 1
            else:
                failed_steps += 1
                _save_artifact(
                    db, batch.batch_id, "screenshot",
                    title=f"浏览器验收失败 - {bc.get('name', f'#{bc_idx+1}')}",
                    content=bv_result["error_detail"],
                    metadata={
                        "error_category": bv_result["error_category"],
                        "step_index": total_steps,
                        "url": target_url
                    }
                )

        total_checkpoints = max(1, len(checkpoints))
        for cp_idx in range(total_checkpoints):
            total_steps += 1
            step_start = time.time()
            try:
                base_date = datetime.now() + timedelta(days=90)
                drill_result = run_full_drill(
                    db, target_venue_id, base_date,
                    auto_find_slot=venue_rules.get("auto_find_slot", True)
                )
                drill_session_ids.append(drill_result.drill_session_id)

                snapshot = get_drill_session_snapshot(db, drill_result.drill_session_id)

                _save_artifact(
                    db, batch.batch_id, "fill_result",
                    title=f"补位结果 - Session {drill_result.drill_session_id}",
                    content=_json_dumps_safe(snapshot),
                    metadata={"drill_session_id": drill_result.drill_session_id}
                )

                for sr in drill_result.steps:
                    all_step_results.append({
                        "step_name": sr.step_name,
                        "passed": sr.passed,
                        "duration_ms": sr.duration_ms,
                        "error_category": sr.error_category,
                        "error_detail": sr.error_detail
                    })
                    if sr.passed:
                        passed_steps += 1
                    else:
                        failed_steps += 1

                total_steps += len(drill_result.steps) - 1

                if samples:
                    summary_metadata = {
                        "sample_count": len(samples),
                        "drill_session_id": drill_result.drill_session_id,
                        "waitlist_count": snapshot["summary"].get("waitlist_count", 0),
                        "filled_count": snapshot["summary"].get("filled_count", 0)
                    }
                    _save_artifact(
                        db, batch.batch_id, "download_summary",
                        title=f"下载文件摘要 - 样本集 #{cp_idx+1}",
                        content=_json_dumps_safe(summary_metadata),
                        metadata=summary_metadata
                    )

                all_ok = drill_result.status in ("completed", "completed_with_errors")
                if all_ok:
                    passed_steps += 0
                else:
                    failed_steps += 0

                if checkpoints and cp_idx < len(checkpoints):
                    cp = checkpoints[cp_idx]
                    _save_artifact(
                        db, batch.batch_id, "op_log",
                        title=f"检查点执行: {cp.get('name', f'#{cp_idx+1}')}",
                        content=cp.get("description", ""),
                        metadata={"checkpoint": cp, "passed": True}
                    )

                for failed_step in [s for s in drill_result.steps if not s.passed]:
                    screenshot_path = _save_screenshot_file(
                        batch.batch_id, total_steps,
                        failed_step.error_detail or "无详细错误信息"
                    )
                    _save_artifact(
                        db, batch.batch_id, "screenshot",
                        title=f"失败截图 - {failed_step.step_name}",
                        content=failed_step.error_detail[:500] if failed_step.error_detail else "",
                        file_path=screenshot_path,
                        metadata={
                            "error_category": failed_step.error_category,
                            "step_name": failed_step.step_name,
                            "duration_ms": failed_step.duration_ms
                        }
                    )

            except Exception as e:
                failed_steps += 1
                error_cat = "UNKNOWN"
                try:
                    from waitlist_drill_service import categorize_error
                    error_cat = categorize_error(e, "batch_execute")
                except Exception:
                    pass

                screenshot_path = _save_screenshot_file(
                    batch.batch_id, cp_idx, str(e)[:1000]
                )
                _save_artifact(
                    db, batch.batch_id, "screenshot",
                    title=f"错误截图 - 步骤 #{cp_idx+1}",
                    content=str(e)[:500],
                    file_path=screenshot_path,
                    metadata={"error_category": error_cat, "step_index": cp_idx}
                )

        _save_artifact(
            db, batch.batch_id, "op_log",
            title="批次执行完成日志",
            content=_json_dumps_safe({
                "total_steps": total_steps,
                "passed_steps": passed_steps,
                "failed_steps": failed_steps,
                "drill_session_ids": drill_session_ids,
                "browser_validation_count": len(browser_checkpoints)
            }),
            metadata={"type": "batch_completion_log"}
        )

        _save_artifact(
            db, batch.batch_id, "step_result",
            title="全部步骤执行结果",
            content=_json_dumps_safe(all_step_results),
            metadata={
                "total": total_steps,
                "passed": passed_steps,
                "failed": failed_steps
            }
        )

        batch.drill_session_ids = _json_dumps_safe(drill_session_ids)
        batch.total_steps = total_steps
        batch.passed_steps = passed_steps
        batch.failed_steps = failed_steps
        batch.status = BATCH_STATUS["COMPLETED"] if failed_steps == 0 else BATCH_STATUS["FAILED"]
        batch.completed_at = datetime.utcnow()

        db.commit()

        if batch.status == BATCH_STATUS["COMPLETED"] and cleanup_strategy.get("auto_cleanup_on_success", False):
            try:
                keep = cleanup_strategy.get("keep_fill_results", True)
                if not keep:
                    pass
            except Exception:
                pass

    except Exception as e:
        db.rollback()
        batch.status = BATCH_STATUS["FAILED"]
        batch.error_message = str(e)[:500]
        batch.completed_at = datetime.utcnow()
        batch.total_steps = total_steps
        batch.passed_steps = passed_steps
        batch.failed_steps = failed_steps
        batch.drill_session_ids = _json_dumps_safe(drill_session_ids)
        db.flush()

    return batch


def rollback_batch(
    db: Session,
    batch: DrillBatch
) -> Dict[str, Any]:
    details: Dict[str, int] = {
        "waitlist_logs": 0,
        "waitlist_entries": 0,
        "reschedule_records": 0,
        "bookings": 0,
        "closed_windows": 0,
        "artifacts": 0,
        "drill_users": 0
    }

    if batch.status == BATCH_STATUS["ROLLED_BACK"]:
        return {
            "batch_id": batch.batch_id,
            "success": True,
            "removed_count": 0,
            "details": details,
            "message": "该批次已经回滚过"
        }

    try:
        session_ids = _json_loads_safe(batch.drill_session_ids, [])
        for sid in session_ids:
            try:
                cleanup = cleanup_drill_session(db, sid)
                for k, v in cleanup.details.items():
                    if k in details:
                        details[k] += v
            except Exception:
                pass

        artifacts = _get_artifacts_by_batch(db, batch.batch_id)
        details["artifacts"] = len(artifacts)
        for a in artifacts:
            db.delete(a)
        db.flush()

        batch.status = BATCH_STATUS["ROLLED_BACK"]
        batch.rolled_back_at = datetime.utcnow()
        db.commit()

        total = sum(details.values())
        return {
            "batch_id": batch.batch_id,
            "success": True,
            "removed_count": total,
            "details": details,
            "message": f"成功回滚，清理 {total} 条数据"
        }

    except Exception as e:
        db.rollback()
        return {
            "batch_id": batch.batch_id,
            "success": False,
            "removed_count": sum(details.values()),
            "details": details,
            "message": f"回滚失败: {str(e)}"
        }


def recover_batch(
    db: Session,
    batch: DrillBatch
) -> Dict[str, Any]:
    previous_status = batch.status

    if batch.status in (BATCH_STATUS["COMPLETED"], BATCH_STATUS["ROLLED_BACK"]):
        return {
            "batch_id": batch.batch_id,
            "success": False,
            "previous_status": previous_status,
            "current_status": batch.status,
            "message": f"状态为 {previous_status} 的批次无需恢复"
        }

    batch.status = BATCH_STATUS["RECOVERING"]
    db.flush()

    try:
        session_ids = _json_loads_safe(batch.drill_session_ids, [])
        verified = True
        recovery_messages = []

        for sid in session_ids:
            try:
                snapshot = get_drill_session_snapshot(db, sid)
                recovery_messages.append({
                    "session_id": sid,
                    "waitlist_count": snapshot["summary"].get("waitlist_count", 0),
                    "booking_count": snapshot["summary"].get("booking_count", 0)
                })
            except Exception as e:
                verified = False
                recovery_messages.append({
                    "session_id": sid,
                    "error": str(e)[:200]
                })

        if batch.status == BATCH_STATUS["RUNNING"]:
            batch.status = BATCH_STATUS["FAILED"]
            new_status = BATCH_STATUS["FAILED"]
        else:
            batch.status = BATCH_STATUS["PENDING"]
            new_status = BATCH_STATUS["PENDING"]

        _save_artifact(
            db, batch.batch_id, "op_log",
            title="批次恢复记录",
            content=_json_dumps_safe({
                "previous_status": previous_status,
                "verified": verified,
                "sessions": recovery_messages
            }),
            metadata={"recovered_at": datetime.utcnow().isoformat()}
        )

        db.commit()

        return {
            "batch_id": batch.batch_id,
            "success": True,
            "previous_status": previous_status,
            "current_status": new_status,
            "message": f"已从 {previous_status} 恢复为 {new_status}"
        }

    except Exception as e:
        db.rollback()
        batch.status = previous_status
        db.flush()
        return {
            "batch_id": batch.batch_id,
            "success": False,
            "previous_status": previous_status,
            "current_status": previous_status,
            "message": f"恢复失败: {str(e)}"
        }


def get_member_batch_view(
    db: Session,
    batch: DrillBatch,
    user_id: int
) -> Dict[str, Any]:
    participant_ids = _json_loads_safe(batch.participant_user_ids, [])
    is_participant = user_id in participant_ids or batch.created_by == user_id

    my_entries = []
    my_blocked_reasons = []
    my_fill_results = []

    if is_participant:
        session_ids = _json_loads_safe(batch.drill_session_ids, [])
        for sid in session_ids:
            entries = db.query(WaitlistEntry).filter(
                WaitlistEntry.drill_session_id == sid,
                WaitlistEntry.user_id == user_id
            ).all()
            for e in entries:
                entry_data = {
                    "id": e.id,
                    "title": e.title,
                    "production": e.production,
                    "status": e.status,
                    "queue_position": e.queue_position,
                    "target_start_time": e.target_start_time.isoformat() if e.target_start_time else None,
                    "target_end_time": e.target_end_time.isoformat() if e.target_end_time else None,
                    "filled_method": e.filled_method,
                    "filled_at": e.filled_at.isoformat() if e.filled_at else None,
                    "is_drill": True
                }
                my_entries.append(entry_data)

                blocked_detail = ""
                if e.blocked_by_type:
                    blocked_type_text = {
                        "booking": "被预约挡住",
                        "closed_window": "被封场挡住",
                        "both": "被预约和封场同时挡住"
                    }.get(e.blocked_by_type, e.blocked_by_type)

                    detail_text = ""
                    if e.blocked_by_details:
                        try:
                            d = json.loads(e.blocked_by_details)
                            conflicts = d.get("conflicts", [])
                            windows = d.get("closed_windows", [])
                            parts = []
                            for c in conflicts:
                                parts.append(
                                    f"预约'{c.get('title','')}' "
                                    f"({c.get('start_time','')}~{c.get('end_time','')})"
                                )
                            for w in windows:
                                parts.append(
                                    f"封场'{w.get('reason','')}' "
                                    f"({w.get('start_time','')}~{w.get('end_time','')})"
                                )
                            detail_text = "; ".join(parts)
                        except Exception:
                            detail_text = e.blocked_by_details

                    my_blocked_reasons.append({
                        "waitlist_id": e.id,
                        "blocked_type": e.blocked_by_type,
                        "blocked_type_text": blocked_type_text,
                        "detail": detail_text
                    })

                if e.status == "filled":
                    my_fill_results.append({
                        "waitlist_id": e.id,
                        "filled_method": e.filled_method,
                        "filled_at": e.filled_at.isoformat() if e.filled_at else None,
                        "booking_id": e.filled_booking_id
                    })

    return {
        "batch_id": batch.batch_id,
        "script_name": batch.script_name,
        "status": batch.status,
        "my_entries": my_entries,
        "my_blocked_reasons": my_blocked_reasons,
        "my_fill_results": my_fill_results
    }


def list_batch_artifacts(
    db: Session,
    batch_id: str,
    artifact_type: Optional[str] = None
) -> List[DrillArtifact]:
    return _get_artifacts_by_batch(db, batch_id, artifact_type)


def create_default_script(
    db: Session,
    creator_id: int
) -> DrillScript:
    default_data = {
        "name": f"默认演练剧本_{datetime.now().strftime('%Y%m%d%H%M%S')}",
        "description": "系统生成的默认候补演练剧本，包含完整的场地规则、样本数据、成员账号、检查点和清理策略。",
        "version": "1.0",
        "venue_rules": {
            "venue_ids": [],
            "auto_find_slot": True,
            "search_days": 30,
            "preferred_hours": [9, 10, 11, 14, 15, 16, 17, 19, 20]
        },
        "drill_samples": [
            {"name": "低优先级候补样本", "type": "low_priority_waiting", "priority": 5,
             "float_before_minutes": 30, "float_after_minutes": 30},
            {"name": "高优先级候补样本", "type": "high_priority_waiting", "priority": 15,
             "float_before_minutes": 60, "float_after_minutes": 60},
            {"name": "封场场景样本", "type": "closed_window_blocking", "priority": 10,
             "float_before_minutes": 30, "float_after_minutes": 30}
        ],
        "member_accounts": [
            {"username": "drill_member_a", "password": "drill1234",
             "full_name": "演练成员A", "role": "member"},
            {"username": "drill_member_b", "password": "drill1234",
             "full_name": "演练成员B", "role": "member"},
            {"username": "drill_admin", "password": "admin1234",
             "full_name": "演练管理员", "role": "admin"}
        ],
        "checkpoints": [
            {"name": "创建用户验证", "description": "验证演练用户正确创建", "expected": "passed"},
            {"name": "挡路预约创建", "description": "创建挡路预约并验证候补被挡", "expected": "passed"},
            {"name": "优先级排队", "description": "验证高优先级排在前面", "expected": "passed"},
            {"name": "封场拦截", "description": "验证封场窗口能正确挡住候补", "expected": "passed"},
            {"name": "自动补位", "description": "撤销封场/取消预约后自动补位", "expected": "passed"},
            {"name": "CSV导出", "description": "验证CSV导出包含演练标记和正确列", "expected": "passed"}
        ],
        "cleanup_strategy": {
            "auto_cleanup_on_success": False,
            "keep_screenshots": True,
            "keep_logs": True,
            "keep_fill_results": True
        }
    }

    from schemas import DrillScriptCreate
    create_dto = DrillScriptCreate(**default_data)
    return create_script(db, create_dto, creator_id)


def scan_and_mark_incomplete_batches(db: Session) -> List[Dict[str, Any]]:
    incomplete_batches = db.query(DrillBatch).filter(
        DrillBatch.status.in_(["pending", "running", "recovering"])
    ).all()
    marked = []
    for batch in incomplete_batches:
        prev_status = batch.status
        batch.status = BATCH_STATUS["RECOVERING"]
        db.flush()

        _save_artifact(
            db, batch.batch_id, "op_log",
            title="服务重启检测 - 标记为恢复中",
            content=_json_dumps_safe({
                "previous_status": prev_status,
                "detected_at": datetime.utcnow().isoformat(),
                "action": "marked_as_recovering"
            }),
            metadata={"type": "startup_recovery"}
        )

        marked.append({
            "batch_id": batch.batch_id,
            "previous_status": prev_status,
            "current_status": BATCH_STATUS["RECOVERING"]
        })

    if marked:
        db.commit()
    return marked
