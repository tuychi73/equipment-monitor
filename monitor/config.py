"""Uskunalar ro'yxati va sozlamalarni TOML fayldan o'qish."""
from __future__ import annotations

import os
import tomllib
from dataclasses import dataclass, field
from pathlib import Path

CHECK_TYPES = {"ping", "tcp", "http"}


@dataclass(frozen=True)
class Device:
    id: str
    name: str
    type: str                     # robot | printer3d | projector | kiosk | pc | network ...
    location: str
    check: str                    # ping | tcp | http
    host: str | None = None
    port: int | None = None
    url: str | None = None
    timeout: float = 2.0
    min: dict = field(default_factory=dict)      # {"battery": 20} -> batareya 20% dan past bo'lsa WARN
    max: dict = field(default_factory=dict)      # {"hotend_temp": 260}
    expect: dict = field(default_factory=dict)   # {"state": ["Operational", "Printing"]}


@dataclass(frozen=True)
class Settings:
    interval: float = 15.0          # tekshiruvlar oralig'i (soniya)
    fail_threshold: int = 2         # ketma-ket shuncha xato -> DOWN (bitta tasodifiy xatoga signal bermaslik uchun)
    db_path: Path = Path("data/monitor.db")
    telegram_token: str | None = None
    telegram_chat_id: str | None = None


def load(path: str | Path) -> tuple[Settings, list[Device]]:
    raw = tomllib.loads(Path(path).read_text(encoding="utf-8"))
    s = raw.get("settings", {})
    settings = Settings(
        interval=float(s.get("interval", 15)),
        fail_threshold=int(s.get("fail_threshold", 2)),
        db_path=Path(s.get("db_path", "data/monitor.db")),
        # Maxfiy ma'lumot faylga emas, muhit o'zgaruvchisiga yoziladi
        telegram_token=os.getenv("TELEGRAM_BOT_TOKEN"),
        telegram_chat_id=os.getenv("TELEGRAM_CHAT_ID"),
    )
    devices = [Device(**d) for d in raw.get("device", [])]
    _validate(devices)
    return settings, devices


def _validate(devices: list[Device]) -> None:
    ids = [d.id for d in devices]
    dup = {i for i in ids if ids.count(i) > 1}
    if dup:
        raise ValueError(f"Takrorlangan qurilma id: {sorted(dup)}")
    for d in devices:
        if d.check not in CHECK_TYPES:
            raise ValueError(f"{d.id}: noma'lum check turi '{d.check}'")
        if d.check in ("ping", "tcp") and not d.host:
            raise ValueError(f"{d.id}: '{d.check}' uchun host kerak")
        if d.check == "tcp" and not d.port:
            raise ValueError(f"{d.id}: tcp uchun port kerak")
        if d.check == "http" and not d.url:
            raise ValueError(f"{d.id}: http uchun url kerak")
