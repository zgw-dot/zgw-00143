from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from pathlib import Path

from database import engine, Base, SessionLocal

Base.metadata.create_all(bind=engine)

try:
    _startup_db = SessionLocal()
    from drill_script_center import scan_and_mark_incomplete_batches
    _recovered = scan_and_mark_incomplete_batches(_startup_db)
    if _recovered:
        print(f"[启动恢复] 检测到 {len(_recovered)} 个未完成批次，已标记为恢复中")
    try:
        from drill_schedule_center import recover_pending_schedules_on_startup
        _sched_recovered = recover_pending_schedules_on_startup(_startup_db)
        if _sched_recovered:
            print(f"[启动恢复] 检测到 {len(_sched_recovered)} 个待处理排期:")
            for _r in _sched_recovered:
                print(f"  - {_r['schedule_no']}: {_r['message']}")
        _startup_db.commit()
    except Exception as _se:
        print(f"[启动恢复] 排期恢复失败: {_se}")
        _startup_db.rollback()
    _startup_db.close()
except Exception as e:
    print(f"[启动恢复] 扫描未完成批次失败: {e}")
    try:
        _startup_db.close()
    except Exception:
        pass

app = FastAPI(title="剧场排练厅预约与冲突调解系统")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

static_dir = Path(__file__).parent / "static"
if static_dir.exists():
    app.mount("/static", StaticFiles(directory=str(static_dir)), name="static")


@app.get("/")
def read_root():
    index_path = Path(__file__).parent / "static" / "index.html"
    if index_path.exists():
        return FileResponse(str(index_path))
    return {"status": "ok", "message": "剧场排练厅预约系统API运行中"}


@app.get("/api/health")
def health_check():
    return {"status": "ok", "message": "剧场排练厅预约系统运行正常"}


from routers import auth, venues, config, bookings, exports, waitlist, waitlist_drill, drill_script_center, drill_schedule

app.include_router(auth.router, prefix="/api/auth", tags=["认证"])
app.include_router(venues.router, prefix="/api/venues", tags=["场地管理"])
app.include_router(config.router, prefix="/api/config", tags=["配置管理"])
app.include_router(bookings.router, prefix="/api/bookings", tags=["预约管理"])
app.include_router(exports.router, prefix="/api/exports", tags=["导出"])
app.include_router(waitlist.router, prefix="/api/waitlist", tags=["候补补位"])
app.include_router(waitlist_drill.router, prefix="/api/waitlist-drill", tags=["候补演练"])
app.include_router(drill_script_center.router, prefix="/api/drill-center", tags=["候补演练剧本中心"])
app.include_router(drill_schedule.router, prefix="/api/drill-schedule", tags=["演练排期台"])

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
