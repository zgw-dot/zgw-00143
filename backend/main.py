from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from pathlib import Path

from database import engine, Base

Base.metadata.create_all(bind=engine)

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


@app.get("/api/health")
def health_check():
    return {"status": "ok", "message": "剧场排练厅预约系统运行正常"}


from routers import auth, venues, config, bookings, exports

app.include_router(auth.router, prefix="/api/auth", tags=["认证"])
app.include_router(venues.router, prefix="/api/venues", tags=["场地管理"])
app.include_router(config.router, prefix="/api/config", tags=["配置管理"])
app.include_router(bookings.router, prefix="/api/bookings", tags=["预约管理"])
app.include_router(exports.router, prefix="/api/exports", tags=["导出"])

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
