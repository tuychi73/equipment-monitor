"""Dashboard: FastAPI + bitta HTML sahifa (har 5 soniyada /api/status dan yangilanadi)."""
from __future__ import annotations

import threading
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import FileResponse

from monitor.engine import Monitor

STATIC = Path(__file__).parent / "static"


def create_app(monitor: Monitor, background: bool = True) -> FastAPI:
    @asynccontextmanager
    async def lifespan(app: FastAPI):
        t = None
        if background:
            t = threading.Thread(target=monitor.run_forever, name="monitor", daemon=True)
            t.start()
        yield
        monitor.stop()

    app = FastAPI(title="Equipment Monitor", lifespan=lifespan)
    st = monitor.storage

    @app.get("/")
    def index():
        return FileResponse(STATIC / "index.html")

    @app.get("/api/status")
    def status():
        out = []
        for d in monitor.devices:
            state = st.get_state(d.id)
            last = st.last_check(d.id)
            out.append({
                "id": d.id, "name": d.name, "type": d.type, "location": d.location, "check": d.check,
                "status": state["status"] if state else "UNKNOWN",
                "since": state["since"] if state else None,
                "detail": last["detail"] if last else "",
                "latency_ms": last["latency_ms"] if last else None,
                "last_check": last["ts"] if last else None,
                "uptime_24h": st.uptime(d.id, 24),
            })
        return {"devices": out, "mttr_minutes": st.mttr_minutes()}

    @app.get("/api/incidents")
    def incidents(limit: int = 50):
        names = {d.id: d.name for d in monitor.devices}
        return [{**i, "device_name": names.get(i["device_id"], i["device_id"])} for i in st.incidents(limit)]

    return app
