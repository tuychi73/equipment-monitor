"""Uskunalar simulyatori: real qurilmalar bo'lmaganda monitoringni sinash uchun.

HTTP (port 9100):
  /robot/{n}/health      robo-gid: batareya, holat, LiDAR
  /printer/{n}/status    3D printer: holat, nozzle harorati, progress
  /kiosk/{n}/health      AI-personaj ekrani / interaktiv kiosk
  POST /sim/{key}/fail?seconds=60   qurilmani vaqtincha "buzish" (503 qaytaradi)
TCP:
  14352  proyektor (PJLink protokoli kabi salomlashadi)

Ishga tushirish:  python -m simulator
"""
from __future__ import annotations

import math
import socket
import threading
import time

import uvicorn
from fastapi import FastAPI, HTTPException

START = time.time()
FAILED_UNTIL: dict[str, float] = {}
app = FastAPI(title="Equipment simulator")


def _t() -> float:
    return time.time() - START


def _guard(key: str) -> None:
    if FAILED_UNTIL.get(key, 0) > time.time():
        raise HTTPException(503, "device failure (simulated)")
    # robot-2 har 4 daqiqada ~45 soniya "o'chib qoladi" - nosozlik va tiklanishni ko'rsatish uchun
    if key == "robot-2" and _t() % 240 > 195:
        raise HTTPException(503, "robot offline (simulated)")


@app.get("/robot/{n}/health")
def robot(n: int):
    key = f"robot-{n}"
    _guard(key)
    # batareya 100% -> 10% gacha kamayib, keyin zaryadlanadi (10 daqiqalik sikl)
    phase = (_t() / 600 + n * 0.37) % 1
    battery = round(100 - 90 * phase) if phase < 0.85 else round(10 + 600 * (phase - 0.85))
    return {"status": "charging" if phase >= 0.85 else "touring", "battery": min(battery, 100),
            "lidar": "ok", "visitors_today": int(_t() // 30) + n * 7}


@app.get("/printer/{n}/status")
def printer(n: int):
    key = f"printer-{n}"
    _guard(key)
    cycle = _t() % 300
    state = "Printing" if cycle < 200 else ("Error" if 250 < cycle < 270 else "Operational")
    return {"state": state, "hotend_temp": round(210 + 5 * math.sin(_t() / 20), 1),
            "bed_temp": 60.0, "progress": round(min(cycle / 200, 1) * 100)}


@app.get("/kiosk/{n}/health")
def kiosk(n: int):
    _guard(f"kiosk-{n}")
    return {"status": "ok", "cpu_temp": round(55 + 10 * math.sin(_t() / 45), 1), "mic": "ok", "display": "on"}


@app.post("/sim/{key}/fail")
def fail(key: str, seconds: int = 60):
    FAILED_UNTIL[key] = time.time() + seconds
    return {"key": key, "failed_for_seconds": seconds}


def _pjlink_server(port: int) -> None:
    srv = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    srv.bind(("127.0.0.1", port))
    srv.listen()
    while True:
        conn, _ = srv.accept()
        with conn:
            conn.sendall(b"PJLINK 0\r")


if __name__ == "__main__":
    threading.Thread(target=_pjlink_server, args=(14352,), daemon=True).start()
    print("Simulyator: http://127.0.0.1:9100  |  proyektor TCP: 127.0.0.1:14352")
    uvicorn.run(app, host="127.0.0.1", port=9100, log_level="warning")
