"""Qurilmani tekshirish usullari: ping, TCP port, HTTP health endpoint."""
from __future__ import annotations

import platform
import socket
import subprocess
import time
from dataclasses import dataclass, field

from monitor.config import Device

OK, WARN, DOWN = "OK", "WARN", "DOWN"


@dataclass
class CheckResult:
    reachable: bool
    latency_ms: float | None = None
    detail: str = ""
    metrics: dict = field(default_factory=dict)


def ping(host: str, timeout: float) -> CheckResult:
    """Tizimning `ping` buyrug'i orqali (ICMP uchun administrator huquqi kerak emas)."""
    if platform.system() == "Windows":
        cmd = ["ping", "-n", "1", "-w", str(int(timeout * 1000)), host]
    else:
        cmd = ["ping", "-c", "1", "-W", str(max(1, int(timeout))), host]
    t0 = time.perf_counter()
    try:
        proc = subprocess.run(cmd, capture_output=True, timeout=timeout + 2)
    except subprocess.TimeoutExpired:
        return CheckResult(False, detail="ping timeout")
    ms = (time.perf_counter() - t0) * 1000
    # Windows'da "Destination host unreachable" javobida ham exit code 0 bo'lishi mumkin, shuning uchun TTL'ni tekshiramiz
    ok = proc.returncode == 0 and b"TTL=" in proc.stdout.upper()
    return CheckResult(ok, round(ms, 1) if ok else None, "javob bor" if ok else "ping javob bermadi")


def tcp(host: str, port: int, timeout: float) -> CheckResult:
    """Port ochiqligini tekshirish (proyektorlarda PJLink 4352, kameralarda RTSP 554, SSH 22 ...)."""
    t0 = time.perf_counter()
    try:
        with socket.create_connection((host, port), timeout=timeout):
            ms = (time.perf_counter() - t0) * 1000
            return CheckResult(True, round(ms, 1), f"{port}-port ochiq")
    except OSError as exc:
        return CheckResult(False, detail=f"{port}-port yopiq: {exc.__class__.__name__}")


def http(session, url: str, timeout: float) -> CheckResult:
    """Health endpoint: 200 javob va JSON ichidagi ko'rsatkichlar (batareya, harorat, holat)."""
    t0 = time.perf_counter()
    try:
        resp = session.get(url, timeout=timeout)
    except Exception as exc:  # ulanib bo'lmadi, timeout, DNS ...
        return CheckResult(False, detail=f"ulanib bo'lmadi: {exc.__class__.__name__}")
    ms = round((time.perf_counter() - t0) * 1000, 1)
    if resp.status_code != 200:
        return CheckResult(False, ms, f"HTTP {resp.status_code}")
    try:
        body = resp.json()
    except ValueError:
        body = {}
    metrics = {k: v for k, v in body.items() if isinstance(v, (int, float, str)) and not isinstance(v, bool)}
    return CheckResult(True, ms, "HTTP 200", metrics)


def run_check(device: Device, session) -> CheckResult:
    if device.check == "ping":
        return ping(device.host, device.timeout)
    if device.check == "tcp":
        return tcp(device.host, device.port, device.timeout)
    return http(session, device.url, device.timeout)


def evaluate(device: Device, result: CheckResult) -> tuple[str, str]:
    """Natijani holatga aylantirish: OK / WARN / DOWN va sababi."""
    if not result.reachable:
        return DOWN, result.detail
    problems = []
    for key, limit in device.min.items():
        v = result.metrics.get(key)
        if isinstance(v, (int, float)) and v < limit:
            problems.append(f"{key}={v} (min {limit})")
    for key, limit in device.max.items():
        v = result.metrics.get(key)
        if isinstance(v, (int, float)) and v > limit:
            problems.append(f"{key}={v} (max {limit})")
    for key, allowed in device.expect.items():
        v = result.metrics.get(key)
        if v is not None and v not in allowed:
            problems.append(f"{key}={v}")
    if problems:
        return WARN, "; ".join(problems)
    return OK, result.detail
