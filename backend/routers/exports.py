from fastapi import APIRouter, Depends, Query
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session
from typing import Optional
from datetime import datetime
import io
import csv

from database import get_db, Booking, RescheduleRecord
from auth import get_current_user

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
            b.updated_at.strftime("%Y-%m-%d %H:%M:%S")
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
