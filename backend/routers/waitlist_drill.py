from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session
from typing import Optional
from datetime import datetime, timedelta
import requests
import time
import os
import signal
import subprocess
import sys

from database import get_db, Venue
from auth import get_current_admin, get_current_user
from schemas import (
    DrillSessionCreate, DrillSessionResponse,
    DrillCleanupResponse, DrillRestartVerifyRequest,
    DrillStepResult
)
from waitlist_drill_service import (
    run_full_drill, cleanup_drill_session,
    get_drill_session_snapshot, verify_restart_consistency,
    ERROR_CATEGORIES
)

router = APIRouter()


@router.post("/session", response_model=DrillSessionResponse)
def create_drill_session(
    drill_config: DrillSessionCreate,
    db: Session = Depends(get_db),
    current_user = Depends(get_current_admin)
):
    if drill_config.venue_id:
        venue = db.query(Venue).filter(
            Venue.id == drill_config.venue_id,
            Venue.is_active == True
        ).first()
        if not venue:
            raise HTTPException(
                status_code=404,
                detail="场地不存在或未启用"
            )
        venue_id = drill_config.venue_id
    else:
        venue = db.query(Venue).filter(Venue.is_active == True).first()
        if not venue:
            raise HTTPException(
                status_code=404,
                detail="没有可用的场地，请先创建场地"
            )
        venue_id = venue.id

    base_date = datetime.now() + timedelta(days=drill_config.target_date_offset_days)

    try:
        result = run_full_drill(
            db, venue_id, base_date,
            auto_find_slot=drill_config.auto_find_slot
        )
        return result
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"演练执行失败: {str(e)}"
        )


@router.get("/session/{drill_session_id}/snapshot")
def get_drill_snapshot(
    drill_session_id: str,
    db: Session = Depends(get_db),
    current_user = Depends(get_current_admin)
):
    try:
        snapshot = get_drill_session_snapshot(db, drill_session_id)
        return snapshot
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"获取快照失败: {str(e)}"
        )


@router.delete("/session/{drill_session_id}", response_model=DrillCleanupResponse)
def cleanup_drill(
    drill_session_id: str,
    db: Session = Depends(get_db),
    current_user = Depends(get_current_admin)
):
    try:
        result = cleanup_drill_session(db, drill_session_id)
        return result
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"清理演练数据失败: {str(e)}"
        )


@router.post("/session/{drill_session_id}/restart-verify")
def restart_and_verify(
    drill_session_id: str,
    verify_request: DrillRestartVerifyRequest,
    db: Session = Depends(get_db),
    current_user = Depends(get_current_admin)
):
    pid = verify_request.server_pid
    port = verify_request.server_port

    try:
        import psutil
        proc = psutil.Process(pid)
        cmdline = " ".join(proc.cmdline())
        cwd = proc.cwd()

        project_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        if project_dir not in cwd and "zgw-00143" not in cmdline:
            raise HTTPException(
                status_code=400,
                detail=f"PID {pid} 不属于当前项目。cmdline={cmdline}, cwd={cwd}"
            )

        snapshot_before = get_drill_session_snapshot(db, drill_session_id)

        proc.terminate()
        try:
            proc.wait(timeout=10)
        except psutil.TimeoutExpired:
            proc.kill()
            proc.wait(timeout=5)

        time.sleep(2)

        max_retries = 30
        server_ready = False
        for i in range(max_retries):
            try:
                r = requests.get(f"http://127.0.0.1:{port}/api/health", timeout=2)
                if r.status_code == 200:
                    server_ready = True
                    break
            except requests.exceptions.RequestException:
                pass
            time.sleep(1)

        if not server_ready:
            return {
                "success": False,
                "error_category": "RESTART",
                "error_detail": f"服务重启超时，{max_retries}秒后仍未就绪",
                "snapshot_before": snapshot_before,
                "consistency_errors": []
            }

        success, errors = verify_restart_consistency(db, drill_session_id, snapshot_before)
        snapshot_after = get_drill_session_snapshot(db, drill_session_id)

        return {
            "success": success,
            "error_category": "" if success else "RESTART",
            "error_detail": "" if success else "; ".join(errors),
            "snapshot_before": snapshot_before,
            "snapshot_after": snapshot_after,
            "consistency_errors": errors
        }

    except ImportError:
        raise HTTPException(
            status_code=500,
            detail="需要安装 psutil: pip install psutil"
        )
    except psutil.NoSuchProcess:
        raise HTTPException(
            status_code=404,
            detail=f"PID {pid} 对应的进程不存在"
        )
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"重启验证失败: {str(e)}"
        )


@router.get("/error-categories")
def get_error_categories(
    current_user = Depends(get_current_user)
):
    return ERROR_CATEGORIES


@router.get("/session/{drill_session_id}/member-view")
def get_member_drill_view(
    drill_session_id: str,
    db: Session = Depends(get_db),
    current_user = Depends(get_current_user)
):
    from database import WaitlistEntry
    is_admin = current_user.role == "admin"

    query = db.query(WaitlistEntry).filter(
        WaitlistEntry.drill_session_id == drill_session_id
    )

    if not is_admin:
        query = query.filter(WaitlistEntry.user_id == current_user.id)

    entries = query.all()

    result = []
    for entry in entries:
        blocked_detail = ""
        if entry.blocked_by_details:
            try:
                import json
                details = json.loads(entry.blocked_by_details)
                if details.get("conflicts"):
                    blocked_detail += "被以下预约挡住："
                    for c in details["conflicts"]:
                        blocked_detail += f"{c.get('title', '')}({c.get('start_time', '')}~{c.get('end_time', '')}); "
                if details.get("closed_windows"):
                    blocked_detail += "被以下封场挡住："
                    for w in details["closed_windows"]:
                        blocked_detail += f"{w.get('reason', '')}({w.get('start_time', '')}~{w.get('end_time', '')}); "
            except:
                blocked_detail = entry.blocked_by_details

        result.append({
            "id": entry.id,
            "title": entry.title,
            "production": entry.production,
            "status": entry.status,
            "status_text": {
                "waiting": "排队中",
                "filled": "已补位",
                "cancelled": "已取消",
                "expired": "已过期"
            }.get(entry.status, entry.status),
            "queue_position": entry.queue_position,
            "blocked_by_type": entry.blocked_by_type,
            "blocked_by_type_text": {
                "booking": "被预约挡住",
                "closed_window": "被封场挡住",
                "both": "被预约和封场同时挡住"
            }.get(entry.blocked_by_type, ""),
            "blocked_detail": blocked_detail,
            "target_start_time": entry.target_start_time,
            "target_end_time": entry.target_end_time,
            "filled_booking_id": entry.filled_booking_id,
            "filled_at": entry.filled_at,
            "filled_method": entry.filled_method,
            "filled_method_text": {
                "auto": "自动补位",
                "manual": "手动补位"
            }.get(entry.filled_method, ""),
            "is_drill": entry.is_drill
        })

    return {
        "drill_session_id": drill_session_id,
        "is_admin": is_admin,
        "entries": result,
        "summary": {
            "total": len(result),
            "waiting": sum(1 for e in result if e["status"] == "waiting"),
            "filled": sum(1 for e in result if e["status"] == "filled"),
            "cancelled": sum(1 for e in result if e["status"] == "cancelled")
        }
    }
