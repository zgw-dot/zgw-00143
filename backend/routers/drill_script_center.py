from fastapi import APIRouter, Depends, HTTPException, status, UploadFile, File
from fastapi.responses import JSONResponse
from sqlalchemy.orm import Session
from typing import Optional, List
import json

from database import get_db, Venue
from auth import get_current_admin, get_current_user, User
from schemas import (
    DrillScriptCreate, DrillScriptUpdate,
    DrillScriptResponse, DrillScriptImportValidateResult,
    DrillBatchCreate, DrillBatchResponse, DrillBatchDetailResponse,
    DrillArtifactResponse, DrillMemberBatchView,
    DrillRollbackResponse, DrillRecoverResponse
)
from drill_script_center import (
    create_script, get_script, get_script_by_name, list_scripts,
    update_script, delete_script, validate_script_import,
    import_script, export_script, create_batch, get_batch,
    get_batch_by_id, list_batches, list_batches_for_member,
    execute_batch, rollback_batch, recover_batch,
    get_member_batch_view, list_batch_artifacts,
    create_default_script,
    _script_to_response, _batch_to_response, _artifact_to_response
)

router = APIRouter()


@router.post("/scripts", response_model=DrillScriptResponse)
def create_drill_script(
    data: DrillScriptCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_admin)
):
    existing = get_script_by_name(db, data.name)
    if existing:
        raise HTTPException(
            status_code=409,
            detail=f"剧本名称已存在: {data.name}"
        )
    try:
        script = create_script(db, data, current_user.id)
        db.commit()
        return _script_to_response(script)
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=f"创建剧本失败: {str(e)}")


@router.get("/scripts", response_model=List[DrillScriptResponse])
def list_drill_scripts(
    is_active: Optional[bool] = None,
    keyword: str = "",
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    scripts = list_scripts(db, is_active=is_active, keyword=keyword)
    return [_script_to_response(s) for s in scripts]


@router.get("/scripts/{script_id}", response_model=DrillScriptResponse)
def get_drill_script(
    script_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    script = get_script(db, script_id)
    if not script:
        raise HTTPException(status_code=404, detail="剧本不存在")
    return _script_to_response(script)


@router.put("/scripts/{script_id}", response_model=DrillScriptResponse)
def update_drill_script(
    script_id: int,
    data: DrillScriptUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_admin)
):
    script = get_script(db, script_id)
    if not script:
        raise HTTPException(status_code=404, detail="剧本不存在")

    if data.name and data.name != script.name:
        existing = get_script_by_name(db, data.name)
        if existing:
            raise HTTPException(
                status_code=409,
                detail=f"剧本名称已存在: {data.name}"
            )

    try:
        script = update_script(db, script, data)
        db.commit()
        return _script_to_response(script)
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=f"更新剧本失败: {str(e)}")


@router.delete("/scripts/{script_id}")
def delete_drill_script(
    script_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_admin)
):
    script = get_script(db, script_id)
    if not script:
        raise HTTPException(status_code=404, detail="剧本不存在")

    from database import DrillBatch
    batches = db.query(DrillBatch).filter(DrillBatch.script_id == script_id).all()
    if batches:
        running = [b for b in batches if b.status in ("pending", "running", "recovering")]
        if running:
            raise HTTPException(
                status_code=400,
                detail=f"存在 {len(running)} 个未完成批次，无法删除剧本"
            )

    try:
        delete_script(db, script)
        db.commit()
        return {"success": True, "message": "剧本已删除"}
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=f"删除剧本失败: {str(e)}")


@router.post("/scripts/validate", response_model=DrillScriptImportValidateResult)
def validate_import_script(
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_admin)
):
    try:
        content = file.file.read()
        script_data = json.loads(content.decode("utf-8"))
    except Exception as e:
        return DrillScriptImportValidateResult(
            valid=False,
            errors=[f"JSON解析失败: {str(e)}"],
            warnings=[]
        )
    return validate_script_import(db, script_data)


@router.post("/scripts/import", response_model=DrillScriptResponse)
def import_drill_script(
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_admin)
):
    try:
        content = file.file.read()
        script_data = json.loads(content.decode("utf-8"))
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"JSON解析失败: {str(e)}")

    validation = validate_script_import(db, script_data)
    if not validation.valid:
        raise HTTPException(
            status_code=400,
            detail={
                "message": "剧本校验失败",
                "errors": validation.errors,
                "warnings": validation.warnings
            }
        )

    try:
        script, _ = import_script(db, script_data, current_user.id)
        db.commit()
        return _script_to_response(script)
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=f"导入剧本失败: {str(e)}")


@router.get("/scripts/{script_id}/export")
def export_drill_script(
    script_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    script = get_script(db, script_id)
    if not script:
        raise HTTPException(status_code=404, detail="剧本不存在")
    data = export_script(script)
    return JSONResponse(
        content=data,
        headers={
            "Content-Disposition": f"attachment; filename=drill_script_{script.id}.json"
        }
    )


@router.post("/scripts/default", response_model=DrillScriptResponse)
def create_default_drill_script(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_admin)
):
    try:
        script = create_default_script(db, current_user.id)
        db.commit()
        return _script_to_response(script)
    except Exception as e:
        db.rollback()
        err_msg = str(e)
        if "UNIQUE constraint" in err_msg or "已存在" in err_msg:
            script = create_default_script(db, current_user.id)
            db.commit()
            return _script_to_response(script)
        raise HTTPException(status_code=500, detail=f"创建默认剧本失败: {err_msg}")


@router.post("/batches", response_model=DrillBatchResponse)
def create_drill_batch(
    data: DrillBatchCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_admin)
):
    script = get_script(db, data.script_id)
    if not script:
        raise HTTPException(status_code=404, detail="剧本不存在")
    if not script.is_active:
        raise HTTPException(status_code=400, detail="剧本未启用")

    if data.venue_id:
        venue = db.query(Venue).filter(
            Venue.id == data.venue_id, Venue.is_active == True
        ).first()
        if not venue:
            raise HTTPException(status_code=404, detail="指定场地不存在或未启用")

    try:
        batch = create_batch(db, script, current_user.id, data.venue_id)
        db.commit()
        return _batch_to_response(batch)
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=f"创建批次失败: {str(e)}")


@router.get("/batches", response_model=List[DrillBatchResponse])
def list_drill_batches(
    script_id: Optional[int] = None,
    status: Optional[str] = None,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    if current_user.role == "admin":
        batches = list_batches(db, script_id=script_id, status=status)
    else:
        batches = list_batches_for_member(db, current_user.id)
        if script_id:
            batches = [b for b in batches if b.script_id == script_id]
        if status:
            batches = [b for b in batches if b.status == status]
    return [_batch_to_response(b) for b in batches]


@router.get("/batches/{batch_id}", response_model=DrillBatchDetailResponse)
def get_drill_batch(
    batch_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    batch = get_batch(db, batch_id)
    if not batch:
        raise HTTPException(status_code=404, detail="批次不存在")

    if current_user.role != "admin":
        participant_ids = []
        import json as _json
        try:
            participant_ids = _json.loads(batch.participant_user_ids)
        except Exception:
            pass
        if current_user.id not in participant_ids and batch.created_by != current_user.id:
            raise HTTPException(status_code=403, detail="无权查看此批次")

    data = _batch_to_response(batch)
    artifacts = list_batch_artifacts(db, batch_id)
    if current_user.role != "admin":
        artifacts = [a for a in artifacts if a.user_id is None or a.user_id == current_user.id]
    data["artifacts"] = [_artifact_to_response(a) for a in artifacts]
    return data


@router.post("/batches/{batch_id}/execute", response_model=DrillBatchResponse)
def execute_drill_batch(
    batch_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_admin)
):
    batch = get_batch(db, batch_id)
    if not batch:
        raise HTTPException(status_code=404, detail="批次不存在")
    if batch.status in ("running", "recovering"):
        raise HTTPException(status_code=400, detail=f"批次当前状态为 {batch.status}，不能执行")
    if batch.status == "rolled_back":
        raise HTTPException(status_code=400, detail="批次已回滚，不能再执行")
    if batch.status in ("completed", "failed"):
        raise HTTPException(status_code=400, detail=f"批次已执行完成（状态: {batch.status}），不能重复执行")

    try:
        batch = execute_batch(db, batch)
        db.commit()
        return _batch_to_response(batch)
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=f"执行批次失败: {str(e)}")


@router.post("/batches/{batch_id}/rollback", response_model=DrillRollbackResponse)
def rollback_drill_batch(
    batch_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_admin)
):
    batch = get_batch(db, batch_id)
    if not batch:
        raise HTTPException(status_code=404, detail="批次不存在")
    if batch.status == "running":
        raise HTTPException(status_code=400, detail="批次正在执行中，不能回滚")

    result = rollback_batch(db, batch)
    return result


@router.post("/batches/{batch_id}/recover", response_model=DrillRecoverResponse)
def recover_drill_batch(
    batch_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_admin)
):
    batch = get_batch(db, batch_id)
    if not batch:
        raise HTTPException(status_code=404, detail="批次不存在")

    result = recover_batch(db, batch)
    return result


@router.get("/batches/{batch_id}/artifacts", response_model=List[DrillArtifactResponse])
def list_batch_drill_artifacts(
    batch_id: str,
    artifact_type: Optional[str] = None,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    batch = get_batch(db, batch_id)
    if not batch:
        raise HTTPException(status_code=404, detail="批次不存在")

    if current_user.role != "admin":
        import json as _json
        try:
            participant_ids = _json.loads(batch.participant_user_ids)
        except Exception:
            participant_ids = []
        if current_user.id not in participant_ids and batch.created_by != current_user.id:
            raise HTTPException(status_code=403, detail="无权查看此批次的产物")

    artifacts = list_batch_artifacts(db, batch_id, artifact_type)
    if current_user.role != "admin":
        artifacts = [a for a in artifacts if a.user_id is None or a.user_id == current_user.id]
    return [_artifact_to_response(a) for a in artifacts]


@router.get("/batches/{batch_id}/member-view", response_model=DrillMemberBatchView)
def get_member_drill_batch_view(
    batch_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    batch = get_batch(db, batch_id)
    if not batch:
        raise HTTPException(status_code=404, detail="批次不存在")
    return get_member_batch_view(db, batch, current_user.id)


@router.get("/batches/{batch_id}/member-download")
def get_member_download(
    batch_id: str,
    artifact_type: Optional[str] = None,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    batch = get_batch(db, batch_id)
    if not batch:
        raise HTTPException(status_code=404, detail="批次不存在")

    if current_user.role != "admin":
        import json as _json
        try:
            participant_ids = _json.loads(batch.participant_user_ids)
        except Exception:
            participant_ids = []
        if current_user.id not in participant_ids and batch.created_by != current_user.id:
            raise HTTPException(status_code=403, detail="无权下载此批次数据")

    from drill_script_center import _json_loads_safe, _json_dumps_safe
    artifacts = list_batch_artifacts(db, batch_id, artifact_type)
    if current_user.role != "admin":
        artifacts = [a for a in artifacts if a.user_id is None or a.user_id == current_user.id]

    result = []
    for a in artifacts:
        if a.artifact_type in ("download_summary", "op_log", "fill_result", "step_result"):
            result.append({
                "id": a.id,
                "artifact_type": a.artifact_type,
                "title": a.title,
                "content": a.content,
                "created_at": a.created_at.isoformat() if a.created_at else None
            })

    return JSONResponse(content={"batch_id": batch_id, "downloads": result})
