from fastapi import APIRouter, Depends, Query
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session
from typing import Optional
from datetime import datetime
import io
import csv

from database import get_db, Booking, RescheduleRecord, ClosedWindow, WaitlistEntry, WaitlistLog
from auth import get_current_user, get_current_admin
from conflict_detector import find_closed_windows

router = APIRouter()


@router.get("/bookings.csv")
def export_bookings_csv(
    production: Optional[str] = None,
    venue_id: Optional[int] = None,
    status: Optional[str] = None,
    user_id: Optional[int] = None,
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
    db: Session = Depends(get_db),
    current_user = Depends(get_current_user)
):
    query = db.query(Booking)

    if production:
        query = query.filter(Booking.production.like(f"%{production}%"))
    if venue_id:
        query = query.filter(Booking.venue_id == venue_id)
    if status:
        status_list = [s.strip() for s in status.split(",") if s.strip()]
        if status_list:
            query = query.filter(Booking.status.in_(status_list))
    if user_id:
        query = query.filter(Booking.user_id == user_id)
    if start_date:
        query = query.filter(Booking.start_time >= datetime.fromisoformat(start_date))
    if end_date:
        query = query.filter(Booking.start_time <= datetime.fromisoformat(end_date))

    bookings = query.order_by(Booking.start_time.desc()).all()

    output = io.StringIO()
    writer = csv.writer(output)

    writer.writerow([
        "预约ID", "标题", "剧目", "场地", "申请人", "状态",
        "开始时间", "结束时间", "优先级", "备注",
        "审批人", "审批时间", "创建时间", "更新时间",
        "撞封场窗口", "封场时段", "封场原因",
        "改期序号", "原时段", "新时段", "改期原因", "改期操作人", "改期时间"
    ])

    status_map = {
        "draft": "草稿",
        "pending": "待审",
        "confirmed": "已确认",
        "rescheduling": "改期中",
        "cancelled": "已取消"
    }

    for b in bookings:
        venue_name = b.venue.name if b.venue else ""
        user_name = b.user.full_name if b.user else ""
        approver_name = b.approver.full_name if b.approver else ""
        status_display = status_map.get(b.status, b.status)

        closed_windows = find_closed_windows(db, b.venue_id, b.start_time, b.end_time)
        has_closed_window = "是" if closed_windows else "否"
        closed_window_ranges = "; ".join([
            f"{w.start_time.strftime('%Y-%m-%d %H:%M')}~{w.end_time.strftime('%Y-%m-%d %H:%M')}"
            for w in closed_windows
        ]) if closed_windows else ""
        closed_window_reasons = "; ".join([w.reason or "封场" for w in closed_windows]) if closed_windows else ""

        base_row = [
            b.id,
            b.title,
            b.production,
            venue_name,
            user_name,
            status_display,
            b.start_time.strftime("%Y-%m-%d %H:%M:%S"),
            b.end_time.strftime("%Y-%m-%d %H:%M:%S"),
            b.priority,
            b.notes,
            approver_name,
            b.approved_at.strftime("%Y-%m-%d %H:%M:%S") if b.approved_at else "",
            b.created_at.strftime("%Y-%m-%d %H:%M:%S"),
            b.updated_at.strftime("%Y-%m-%d %H:%M:%S"),
            has_closed_window,
            closed_window_ranges,
            closed_window_reasons
        ]

        reschedule_records = db.query(RescheduleRecord).filter(
            RescheduleRecord.booking_id == b.id
        ).order_by(RescheduleRecord.created_at.asc()).all()

        if not reschedule_records:
            writer.writerow(base_row + ["", "", "", "", "", ""])
        else:
            for idx, r in enumerate(reschedule_records, 1):
                operator_name = r.operator.full_name if r.operator else ""
                original_range = (
                    f"{r.original_start_time.strftime('%Y-%m-%d %H:%M:%S')} ~ "
                    f"{r.original_end_time.strftime('%Y-%m-%d %H:%M:%S')}"
                )
                new_range = (
                    f"{r.new_start_time.strftime('%Y-%m-%d %H:%M:%S')} ~ "
                    f"{r.new_end_time.strftime('%Y-%m-%d %H:%M:%S')}"
                )
                reschedule_row = [
                    f"第{idx}次改期",
                    original_range,
                    new_range,
                    r.reason or "",
                    operator_name,
                    r.created_at.strftime("%Y-%m-%d %H:%M:%S") if r.created_at else ""
                ]
                writer.writerow(base_row + reschedule_row)

    output.seek(0)
    content = output.getvalue()
    content_bom = "\ufeff" + content

    filename = f"bookings_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv"

    return StreamingResponse(
        iter([content_bom]),
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": f"attachment; filename={filename}"}
    )


@router.get("/waitlist.csv")
def export_waitlist_csv(
    production: Optional[str] = None,
    venue_id: Optional[int] = None,
    status: Optional[str] = None,
    user_id: Optional[int] = None,
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
    db: Session = Depends(get_db),
    current_user = Depends(get_current_admin)
):
    query = db.query(WaitlistEntry)

    if production:
        query = query.filter(WaitlistEntry.production.like(f"%{production}%"))
    if venue_id:
        query = query.filter(WaitlistEntry.venue_id == venue_id)
    if status:
        status_list = [s.strip() for s in status.split(",") if s.strip()]
        if status_list:
            query = query.filter(WaitlistEntry.status.in_(status_list))
    if user_id:
        query = query.filter(WaitlistEntry.user_id == user_id)
    if start_date:
        query = query.filter(WaitlistEntry.target_start_time >= datetime.fromisoformat(start_date))
    if end_date:
        query = query.filter(WaitlistEntry.target_start_time <= datetime.fromisoformat(end_date))

    entries = query.order_by(
        WaitlistEntry.status.asc(),
        WaitlistEntry.venue_id.asc(),
        WaitlistEntry.target_start_time.asc(),
        WaitlistEntry.queue_position.asc(),
        WaitlistEntry.created_at.desc()
    ).all()

    output = io.StringIO()
    writer = csv.writer(output)

    writer.writerow([
        "候补ID", "标题", "剧目", "场地", "申请人", "优先级",
        "目标开始时间", "目标结束时间",
        "前浮动(分钟)", "后浮动(分钟)",
        "状态", "排队序号", "被挡住类型",
        "补位方式", "补位时间", "对应预约ID",
        "取消人", "取消时间", "取消原因",
        "过期时间", "备注", "创建时间", "更新时间",
        "日志序号", "操作类型", "触发原因",
        "操作人", "对应预约ID", "日志备注", "日志时间"
    ])

    status_map = {
        "waiting": "排队中",
        "filled": "已补位",
        "cancelled": "已取消",
        "expired": "已过期"
    }
    blocked_map = {
        "booking": "预约冲突",
        "closed_window": "封场挡住",
        "both": "预约+封场",
        "": ""
    }
    fill_method_map = {
        "auto": "自动补位",
        "manual": "手动补位"
    }
    action_map = {
        "create": "登记候补",
        "fill": "补位成功",
        "cancel": "取消候补",
        "expire": "自动过期",
        "auto_trigger": "自动触发"
    }
    trigger_map = {
        "user_registered": "用户登记",
        "booking_cancelled": "预约取消",
        "booking_rescheduled": "预约改期",
        "closed_window_revoked": "封场撤销",
        "manual_fill": "管理员手动补位",
        "manual_cancel": "手动取消",
        "auto_expire": "自动过期"
    }

    for e in entries:
        venue_name = e.venue.name if e.venue else ""
        user_name = e.user.full_name if e.user else ""
        canceller_name = e.canceller.full_name if e.canceller else ""
        status_display = status_map.get(e.status, e.status)
        blocked_display = blocked_map.get(e.blocked_by_type, e.blocked_by_type)
        fill_method_display = fill_method_map.get(e.filled_method, e.filled_method or "")

        base_row = [
            e.id,
            e.title,
            e.production,
            venue_name,
            user_name,
            e.priority,
            e.target_start_time.strftime("%Y-%m-%d %H:%M:%S"),
            e.target_end_time.strftime("%Y-%m-%d %H:%M:%S"),
            e.float_before_minutes,
            e.float_after_minutes,
            status_display,
            e.queue_position,
            blocked_display,
            fill_method_display,
            e.filled_at.strftime("%Y-%m-%d %H:%M:%S") if e.filled_at else "",
            e.filled_booking_id if e.filled_booking_id else "",
            canceller_name,
            e.cancelled_at.strftime("%Y-%m-%d %H:%M:%S") if e.cancelled_at else "",
            e.cancel_reason or "",
            e.expires_at.strftime("%Y-%m-%d %H:%M:%S") if e.expires_at else "",
            e.notes or "",
            e.created_at.strftime("%Y-%m-%d %H:%M:%S"),
            e.updated_at.strftime("%Y-%m-%d %H:%M:%S")
        ]

        logs = db.query(WaitlistLog).filter(
            WaitlistLog.waitlist_entry_id == e.id
        ).order_by(WaitlistLog.created_at.asc()).all()

        if not logs:
            writer.writerow(base_row + ["", "", "", "", "", "", ""])
        else:
            for idx, log in enumerate(logs, 1):
                operator_name = log.operator.full_name if log.operator else ""
                action_display = action_map.get(log.action, log.action)
                trigger_display = trigger_map.get(log.trigger_reason, log.trigger_reason or "")
                log_row = [
                    f"第{idx}条",
                    action_display,
                    trigger_display,
                    operator_name,
                    log.result_booking_id if log.result_booking_id else "",
                    log.notes or "",
                    log.created_at.strftime("%Y-%m-%d %H:%M:%S") if log.created_at else ""
                ]
                writer.writerow(base_row + log_row)

    output.seek(0)
    content = output.getvalue()
    content_bom = "\ufeff" + content

    filename = f"waitlist_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv"

    return StreamingResponse(
        iter([content_bom]),
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": f"attachment; filename={filename}"}
    )
