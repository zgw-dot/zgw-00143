from fastapi import APIRouter, Depends, HTTPException, status, UploadFile, File, Query, Request, Body
from fastapi.responses import JSONResponse
from sqlalchemy.orm import Session
from typing import Optional, List
import json
from datetime import date, datetime, time as dt_time

from database import (
    get_db, User, Venue, DrillScript,
    ScheduleTemplate, ScheduleTemplateVersion,
    DrillSchedule, ScheduleAuditLog, ScheduleMember
)
from auth import get_current_admin, get_current_user
from schemas import (
    ScheduleTemplateCreate, ScheduleTemplateUpdate,
    ScheduleTemplateResponse, ScheduleTemplateVersionResponse,
    ScheduleTemplateImportValidateResult, ScheduleTemplateImportResult,
    DrillScheduleCreate, DrillScheduleUpdate,
    DrillScheduleResponse, DrillScheduleListResponse,
    ScheduleAuditLogResponse, ScheduleMemberResponse,
    ScheduleMemberPersonalView, ScheduleActionResponse,
    ScheduleCopyResult, ScheduleBatchGenerateResult,
    ScheduleCleanupResult, ScheduleRecoverResult,
    ScheduleCalendarItem, ScheduleCancelBody, ScheduleCopyBody,
    ScheduleBatchGenerateBody, ScheduleRecoverSummary,
    AuditLogListResponse
)
from drill_schedule_center import (
    get_template, get_template_by_name, list_templates,
    create_template, update_template, delete_template,
    toggle_template_active, list_template_versions,
    validate_template_import, import_template, export_template,
    detect_schedule_conflicts,
    get_schedule, get_schedule_by_no, list_schedules,
    list_schedules_for_member, list_schedule_calendar,
    create_schedule, update_schedule, publish_schedule,
    lock_schedule, unlock_schedule, cancel_schedule,
    copy_schedule, generate_execution_batch,
    get_schedule_members, get_member_personal_view,
    list_schedule_audit_logs, manual_cleanup_schedule,
    generate_schedules_from_template,
    recover_pending_schedules_on_startup,
    _template_to_dict, _template_version_to_dict, _schedule_to_dict
)

router = APIRouter()


def _get_client_ip(request: Request) -> str:
    try:
        forwarded = request.headers.get("x-forwarded-for", "")
        if forwarded:
            return forwarded.split(",")[0].strip()
        return request.client.host if request.client else ""
    except Exception:
        return ""


# ============================================================================
# 模板管理 API
# ============================================================================

@router.post("/templates", response_model=ScheduleTemplateResponse)
def api_create_template(
    data: ScheduleTemplateCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_admin)
):
    existing = get_template_by_name(db, data.name)
    if existing:
        raise HTTPException(status_code=409, detail=f"模板名称已存在: {data.name}")
    if data.template_type not in ["venue", "group", "checklist", "cleanup"]:
        raise HTTPException(status_code=400, detail="模板类型无效 (venue/group/checklist/cleanup)")
    try:
        t = create_template(db, data, current_user.id)
        db.commit()
        return _template_to_dict(t)
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=f"创建模板失败: {str(e)}")


@router.get("/templates", response_model=List[ScheduleTemplateResponse])
def api_list_templates(
    template_type: Optional[str] = None,
    is_active: Optional[bool] = None,
    keyword: str = "",
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    items = list_templates(db, template_type=template_type, is_active=is_active, keyword=keyword)
    return [_template_to_dict(t) for t in items]


@router.post("/templates/validate", response_model=ScheduleTemplateImportValidateResult)
def api_validate_template_import(
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_admin)
):
    try:
        content = file.file.read()
        tpl_data = json.loads(content.decode("utf-8"))
    except Exception as e:
        return ScheduleTemplateImportValidateResult(
            valid=False,
            errors=[f"JSON解析失败: {str(e)}"],
            blocking_errors=[f"JSON解析失败: {str(e)}"],
            warnings=[]
        )
    result = validate_template_import(db, tpl_data)
    result.blocking_errors = list(result.errors) if result.errors else []
    return result


@router.post("/templates/import", response_model=ScheduleTemplateImportResult)
def api_import_template(
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_admin)
):
    try:
        content = file.file.read()
        tpl_data = json.loads(content.decode("utf-8"))
    except Exception as e:
        return ScheduleTemplateImportResult(
            success=False,
            errors=[f"JSON解析失败: {str(e)}"],
            blocking_errors=[f"JSON解析失败: {str(e)}"],
            warnings=[]
        )
    validation = validate_template_import(db, tpl_data)
    validation.blocking_errors = list(validation.errors) if validation.errors else []
    if not validation.valid:
        return ScheduleTemplateImportResult(
            success=False,
            errors=validation.errors,
            blocking_errors=validation.blocking_errors,
            warnings=validation.warnings
        )
    try:
        t, _ = import_template(db, tpl_data, current_user.id)
        db.commit()
        return ScheduleTemplateImportResult(
            success=True, template_id=t.id, version_snapshot=True, name=t.name,
            errors=[], blocking_errors=[], warnings=validation.warnings
        )
    except ValueError as e:
        db.rollback()
        return ScheduleTemplateImportResult(
            success=False, errors=[str(e)], blocking_errors=[str(e)], warnings=[]
        )
    except Exception as e:
        db.rollback()
        return ScheduleTemplateImportResult(
            success=False, errors=[f"导入失败: {str(e)}"],
            blocking_errors=[f"导入失败: {str(e)}"], warnings=[]
        )


@router.get("/templates/{template_id}", response_model=ScheduleTemplateResponse)
def api_get_template(
    template_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    t = get_template(db, template_id)
    if not t:
        raise HTTPException(status_code=404, detail="模板不存在")
    return _template_to_dict(t)


@router.put("/templates/{template_id}", response_model=ScheduleTemplateResponse)
def api_update_template(
    template_id: int,
    data: ScheduleTemplateUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_admin)
):
    t = get_template(db, template_id)
    if not t:
        raise HTTPException(status_code=404, detail="模板不存在")
    if data.name and data.name != t.name:
        existing = get_template_by_name(db, data.name)
        if existing:
            raise HTTPException(status_code=409, detail=f"模板名称已存在: {data.name}")
    try:
        t = update_template(db, t, data, current_user.id)
        db.commit()
        return _template_to_dict(t)
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=f"更新模板失败: {str(e)}")


@router.delete("/templates/{template_id}")
def api_delete_template(
    template_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_admin)
):
    t = get_template(db, template_id)
    if not t:
        raise HTTPException(status_code=404, detail="模板不存在")
    try:
        delete_template(db, t)
        db.commit()
        return {"success": True, "message": "模板已删除"}
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=f"删除模板失败: {str(e)}")


@router.post("/templates/{template_id}/toggle", response_model=ScheduleTemplateResponse)
def api_toggle_template(
    template_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_admin)
):
    t = get_template(db, template_id)
    if not t:
        raise HTTPException(status_code=404, detail="模板不存在")
    try:
        t = toggle_template_active(db, t, current_user.id)
        db.commit()
        return _template_to_dict(t)
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=f"启停模板失败: {str(e)}")


@router.get("/templates/{template_id}/versions", response_model=List[ScheduleTemplateVersionResponse])
def api_list_template_versions(
    template_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    t = get_template(db, template_id)
    if not t:
        raise HTTPException(status_code=404, detail="模板不存在")
    items = list_template_versions(db, template_id)
    return [_template_version_to_dict(v) for v in items]


@router.get("/templates/{template_id}/export")
def api_export_template(
    template_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    t = get_template(db, template_id)
    if not t:
        raise HTTPException(status_code=404, detail="模板不存在")
    data = export_template(t)
    filename = f"template_{t.template_type}_{t.id}_{datetime.now().strftime('%Y%m%d')}.json"
    return JSONResponse(
        content=data,
        headers={"Content-Disposition": f"attachment; filename={filename}"}
    )


# ============================================================================
# 排期管理 API (注意：静态路径必须放在 {schedule_id} 路径之前，避免被解析成参数)
# ============================================================================

@router.post("/schedules", response_model=DrillScheduleResponse)
def api_create_schedule(
    data: DrillScheduleCreate,
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_admin)
):
    try:
        s = create_schedule(db, data, current_user.id, _get_client_ip(request))
        db.commit()
        return _schedule_to_dict(s)
    except ValueError as e:
        db.rollback()
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=f"创建排期失败: {str(e)}")


@router.get("/schedules/calendar", response_model=List[ScheduleCalendarItem])
def api_get_schedule_calendar(
    start_date: date = Query(...),
    end_date: date = Query(...),
    venue_id: Optional[int] = None,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    user_id = None if current_user.role == "admin" else current_user.id
    return list_schedule_calendar(db, start_date, end_date, venue_id, user_id)


@router.get("/schedules/mine", response_model=DrillScheduleListResponse)
def api_list_my_schedules(
    status: Optional[str] = None,
    page: int = 1,
    page_size: int = 50,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    items = list_schedules_for_member(db, current_user.id, status)
    total = len(items)
    start_idx = (page - 1) * page_size
    paged = items[start_idx:start_idx + page_size]
    resp_items = [_schedule_to_dict(s) for s in paged]
    for i in resp_items:
        i["conflicts"] = i.get("conflict_details", [])
    return DrillScheduleListResponse(
        items=resp_items, total=total, page=page, page_size=page_size
    )


@router.get("/schedules", response_model=DrillScheduleListResponse)
def api_list_schedules(
    start_date: Optional[date] = None,
    end_date: Optional[date] = None,
    venue_id: Optional[int] = None,
    status: Optional[str] = None,
    keyword: str = "",
    page: int = 1,
    page_size: int = 50,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    if current_user.role == "admin":
        items, total = list_schedules(
            db, start_date=start_date, end_date=end_date, venue_id=venue_id,
            status=status, keyword=keyword, page=page, page_size=page_size
        )
    else:
        items = list_schedules_for_member(db, current_user.id, status)
        filtered = []
        for s in items:
            if start_date and s.schedule_date < start_date:
                continue
            if end_date and s.schedule_date > end_date:
                continue
            if venue_id and s.venue_id != venue_id:
                continue
            if keyword and keyword not in s.title and keyword not in s.schedule_no:
                continue
            filtered.append(s)
        total = len(filtered)
        start_idx = (page - 1) * page_size
        items = filtered[start_idx:start_idx + page_size]

    resp_items = []
    for s in items:
        d = _schedule_to_dict(s)
        d["conflicts"] = d.get("conflict_details", [])
        resp_items.append(d)

    return DrillScheduleListResponse(
        items=resp_items, total=total, page=page, page_size=page_size
    )


@router.get("/schedules/check-conflicts")
def api_check_conflicts(
    schedule_date: date = Query(...),
    start_time: str = Query(...),
    end_time: str = Query(...),
    venue_id: int = Query(...),
    exclude_schedule_id: Optional[int] = None,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_admin)
):
    try:
        sh, sm = map(int, start_time.split(":"))
        eh, em = map(int, end_time.split(":"))
        st = dt_time(hour=sh, minute=sm)
        et = dt_time(hour=eh, minute=em)
    except Exception:
        raise HTTPException(status_code=400, detail="时间格式错误，应为 HH:MM")
    conflicts = detect_schedule_conflicts(
        db, schedule_date, st, et, venue_id, exclude_schedule_id
    )
    return {"conflicts": conflicts, "has_conflict": len(conflicts) > 0}


@router.post("/schedules/recover", response_model=ScheduleRecoverSummary)
def api_recover_schedules(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_admin)
):
    try:
        results = recover_pending_schedules_on_startup(db)
        db.commit()
        items = [ScheduleRecoverResult(**r) for r in results]
        recovered_count = sum(1 for it in items if it.recovered)
        return ScheduleRecoverSummary(
            recovered_count=recovered_count,
            items=items,
            message=f"扫描 {len(items)} 项，恢复 {recovered_count} 项待执行排期"
        )
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=f"恢复失败: {str(e)}")


@router.post("/schedules/batch-generate")
def api_batch_generate_calendar(
    payload: ScheduleBatchGenerateBody,
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_admin)
):
    try:
        created = generate_schedules_from_template(
            db,
            payload.venue_template_id,
            payload.start_date,
            payload.end_date,
            current_user.id,
            payload.base_title,
            payload.drill_script_id,
            payload.group_template_id,
            payload.checklist_template_id,
            payload.cleanup_template_id,
            _get_client_ip(request),
            venue_id=payload.venue_id,
            daily_start_time=payload.daily_start_time,
            daily_end_time=payload.daily_end_time,
            exclude_weekends=payload.exclude_weekends
        )
        db.commit()
        ids = [s.id for s in created]
        return {
            "success": True,
            "created_count": len(created),
            "skipped_conflicts": 0,
            "schedule_ids": ids,
            "items": [_schedule_to_dict(s) for s in created]
        }
    except ValueError as e:
        db.rollback()
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=f"批量生成失败: {str(e)}")


# ========== 下面是带 {schedule_id} 的路径，必须在所有静态路径之后 ==========

@router.get("/schedules/{schedule_id}", response_model=DrillScheduleResponse)
def api_get_schedule(
    schedule_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    s = get_schedule(db, schedule_id)
    if not s:
        raise HTTPException(status_code=404, detail="排期不存在")

    if current_user.role != "admin":
        is_member = db.query(ScheduleMember).filter(
            ScheduleMember.schedule_id == s.id,
            ScheduleMember.user_id == current_user.id
        ).first()
        if not is_member and s.created_by != current_user.id:
            raise HTTPException(status_code=403, detail="无权查看此排期")

    return _schedule_to_dict(s)


@router.put("/schedules/{schedule_id}", response_model=DrillScheduleResponse)
def api_update_schedule(
    schedule_id: int,
    data: DrillScheduleUpdate,
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_admin)
):
    s = get_schedule(db, schedule_id)
    if not s:
        raise HTTPException(status_code=404, detail="排期不存在")
    try:
        s = update_schedule(db, s, data, current_user.id, _get_client_ip(request))
        db.commit()
        return _schedule_to_dict(s)
    except ValueError as e:
        db.rollback()
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=f"修改排期失败: {str(e)}")


@router.get("/schedules/{schedule_id}/conflicts")
def api_check_schedule_conflicts(
    schedule_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    s = get_schedule(db, schedule_id)
    if not s:
        raise HTTPException(status_code=404, detail="排期不存在")
    conflicts = detect_schedule_conflicts(
        db, s.schedule_date, s.start_time, s.end_time, s.venue_id,
        exclude_schedule_id=s.id
    )
    return {"schedule_id": s.id, "schedule_no": s.schedule_no, "conflicts": conflicts}


@router.post("/schedules/{schedule_id}/publish", response_model=ScheduleActionResponse)
def api_publish_schedule(
    schedule_id: int,
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_admin)
):
    s = get_schedule(db, schedule_id)
    if not s:
        raise HTTPException(status_code=404, detail="排期不存在")
    try:
        result = publish_schedule(db, s, current_user.id, _get_client_ip(request))
        db.commit()
        return result
    except ValueError as e:
        db.rollback()
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=f"发布失败: {str(e)}")


@router.post("/schedules/{schedule_id}/lock", response_model=ScheduleActionResponse)
def api_lock_schedule(
    schedule_id: int,
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_admin)
):
    s = get_schedule(db, schedule_id)
    if not s:
        raise HTTPException(status_code=404, detail="排期不存在")
    try:
        result = lock_schedule(db, s, current_user.id, _get_client_ip(request))
        db.commit()
        return result
    except ValueError as e:
        db.rollback()
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=f"锁定失败: {str(e)}")


@router.post("/schedules/{schedule_id}/unlock", response_model=ScheduleActionResponse)
def api_unlock_schedule(
    schedule_id: int,
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_admin)
):
    s = get_schedule(db, schedule_id)
    if not s:
        raise HTTPException(status_code=404, detail="排期不存在")
    try:
        result = unlock_schedule(db, s, current_user.id, _get_client_ip(request))
        db.commit()
        return result
    except ValueError as e:
        db.rollback()
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=f"解锁失败: {str(e)}")


@router.post("/schedules/{schedule_id}/cancel", response_model=ScheduleActionResponse)
def api_cancel_schedule(
    schedule_id: int,
    request: Request,
    body: ScheduleCancelBody = ScheduleCancelBody(),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_admin)
):
    s = get_schedule(db, schedule_id)
    if not s:
        raise HTTPException(status_code=404, detail="排期不存在")
    try:
        result = cancel_schedule(
            db, s, current_user.id, body.reason, _get_client_ip(request)
        )
        db.commit()
        return result
    except ValueError as e:
        db.rollback()
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=f"撤销失败: {str(e)}")


@router.post("/schedules/{schedule_id}/copy", response_model=ScheduleCopyResult)
def api_copy_schedule(
    schedule_id: int,
    request: Request,
    body: ScheduleCopyBody = ScheduleCopyBody(),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_admin)
):
    s = get_schedule(db, schedule_id)
    if not s:
        raise HTTPException(status_code=404, detail="排期不存在")
    try:
        start_t = None
        end_t = None
        if body.new_start_time:
            h, m = map(int, body.new_start_time.split(":"))
            start_t = dt_time(hour=h, minute=m)
        if body.new_end_time:
            h, m = map(int, body.new_end_time.split(":"))
            end_t = dt_time(hour=h, minute=m)
        result = copy_schedule(
            db, s, current_user.id, body.new_date, _get_client_ip(request),
            new_start_time=start_t, new_end_time=end_t
        )
        db.commit()
        return result
    except ValueError as e:
        db.rollback()
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=f"复制失败: {str(e)}")


@router.post("/schedules/{schedule_id}/generate-batch", response_model=ScheduleBatchGenerateResult)
def api_generate_batch(
    schedule_id: int,
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_admin)
):
    s = get_schedule(db, schedule_id)
    if not s:
        raise HTTPException(status_code=404, detail="排期不存在")
    try:
        result = generate_execution_batch(db, s, current_user.id, _get_client_ip(request))
        db.commit()
        return result
    except ValueError as e:
        db.rollback()
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=f"生成批次失败: {str(e)}")


@router.get("/schedules/{schedule_id}/members", response_model=List[ScheduleMemberResponse])
def api_get_schedule_members(
    schedule_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    s = get_schedule(db, schedule_id)
    if not s:
        raise HTTPException(status_code=404, detail="排期不存在")
    if current_user.role != "admin":
        is_member = db.query(ScheduleMember).filter(
            ScheduleMember.schedule_id == s.id,
            ScheduleMember.user_id == current_user.id
        ).first()
        if not is_member and s.created_by != current_user.id:
            raise HTTPException(status_code=403, detail="无权查看")
    return get_schedule_members(db, schedule_id)


@router.get("/schedules/{schedule_id}/my-view", response_model=ScheduleMemberPersonalView)
def api_get_my_schedule_view(
    schedule_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    s = get_schedule(db, schedule_id)
    if not s:
        raise HTTPException(status_code=404, detail="排期不存在")
    try:
        return get_member_personal_view(db, s, current_user.id)
    except ValueError as e:
        raise HTTPException(status_code=403, detail=str(e))


@router.get("/schedules/{schedule_id}/audit-logs", response_model=List[ScheduleAuditLogResponse])
def api_get_schedule_audit_logs(
    schedule_id: int,
    page: int = 1,
    page_size: int = 100,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_admin)
):
    s = get_schedule(db, schedule_id)
    if not s:
        raise HTTPException(status_code=404, detail="排期不存在")
    items, _ = list_schedule_audit_logs(db, schedule_id=schedule_id, page=page, page_size=page_size)
    return items


@router.post("/schedules/{schedule_id}/cleanup", response_model=ScheduleCleanupResult)
def api_cleanup_schedule(
    schedule_id: int,
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_admin)
):
    s = get_schedule(db, schedule_id)
    if not s:
        raise HTTPException(status_code=404, detail="排期不存在")
    try:
        result = manual_cleanup_schedule(db, s, current_user.id, _get_client_ip(request))
        db.commit()
        return result
    except ValueError as e:
        db.rollback()
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=f"清理失败: {str(e)}")


@router.delete("/schedules/{schedule_id}")
def api_delete_schedule(
    schedule_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_admin)
):
    from drill_schedule_center import delete_schedule as _delete_schedule
    s = get_schedule(db, schedule_id)
    if not s:
        raise HTTPException(status_code=404, detail="排期不存在")
    try:
        _delete_schedule(db, s, current_user.id)
        db.commit()
        return {"success": True, "message": "排期已删除", "schedule_id": schedule_id}
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=f"删除排期失败: {str(e)}")


# ============================================================================
# 审计日志 API
# ============================================================================

@router.get("/audit-logs", response_model=AuditLogListResponse)
def api_list_all_audit_logs(
    action: Optional[str] = None,
    user_id: Optional[int] = None,
    page: int = 1,
    page_size: int = 100,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_admin)
):
    items, total = list_schedule_audit_logs(
        db, action=action, user_id=user_id, page=page, page_size=page_size
    )
    return AuditLogListResponse(
        items=items, total=total, page=page, page_size=page_size
    )
