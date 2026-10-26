"""Monitoring dvigateli: tekshiradi, holatni tasdiqlaydi, nosozlik ochadi/yopadi va xabar yuboradi.

Holat mashinasi (state machine):
    OK ──(ketma-ket N ta xato)──► DOWN ──(1 ta muvaffaqiyatli tekshiruv)──► OK
    OK ──(ko'rsatkich chegaradan chiqdi)──► WARN ──(normaga qaytdi)──► OK
Bitta tasodifiy xato DOWN deb hisoblanmaydi - soxta ogohlantirishlar (false alarm) kamayadi.
"""
from __future__ import annotations

import logging
import threading
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from datetime import datetime

import requests

from monitor import checks
from monitor.checks import DOWN, OK, WARN
from monitor.config import Device, Settings
from monitor.notify import Notifier
from monitor.storage import Storage, now

log = logging.getLogger(__name__)
ICON = {OK: "✅", WARN: "⚠️", DOWN: "🔴"}


@dataclass
class Event:
    device: Device
    kind: str          # DOWN | RECOVERED | WARN | WARN_CLEARED
    detail: str


class Monitor:
    def __init__(self, settings: Settings, devices: list[Device], storage: Storage, notifier: Notifier,
                 session=None):
        self.settings = settings
        self.devices = devices
        self.storage = storage
        self.notifier = notifier
        self.session = session or requests.Session()
        self._stop = threading.Event()

    # ---------- bitta qurilma ----------
    def process(self, device: Device, result: checks.CheckResult) -> Event | None:
        ts = now()
        status, detail = checks.evaluate(device, result)
        self.storage.add_check(device.id, ts, status, result.latency_ms, detail)

        prev = self.storage.get_state(device.id)
        prev_status = prev["status"] if prev else OK
        fails = (prev["fail_count"] if prev else 0) + 1 if status == DOWN else 0

        if status == DOWN:
            if prev_status != DOWN and fails >= self.settings.fail_threshold:
                if prev_status == WARN:
                    self.storage.close_incident(device.id, ts)
                self.storage.open_incident(device.id, DOWN, ts, detail)
                self.storage.set_state(device.id, DOWN, fails, ts, detail)
                return Event(device, "DOWN", detail)
            # hali tasdiqlanmagan yoki allaqachon DOWN: holat o'zgarmaydi, faqat hisoblagich
            self.storage.set_state(device.id, prev_status, fails, _since(prev, ts), prev["detail"] if prev else detail)
            return None

        if prev_status == DOWN:
            inc = self.storage.close_incident(device.id, ts)
            self.storage.set_state(device.id, status, 0, ts, detail)
            if status == WARN:
                self.storage.open_incident(device.id, WARN, ts, detail)
            minutes = _minutes(inc["opened_at"], ts) if inc else 0
            return Event(device, "RECOVERED", f"{minutes} daqiqa ishlamadi. Hozir: {detail}")

        if status == WARN and prev_status != WARN:
            self.storage.open_incident(device.id, WARN, ts, detail)
            self.storage.set_state(device.id, WARN, 0, ts, detail)
            return Event(device, "WARN", detail)

        if status == OK and prev_status == WARN:
            self.storage.close_incident(device.id, ts)
            self.storage.set_state(device.id, OK, 0, ts, detail)
            return Event(device, "WARN_CLEARED", detail)

        self.storage.set_state(device.id, status, 0, _since(prev, ts), detail)
        return None

    # ---------- barcha qurilmalar ----------
    def run_once(self) -> list[Event]:
        with ThreadPoolExecutor(max_workers=min(16, len(self.devices) or 1)) as pool:
            results = list(pool.map(lambda d: checks.run_check(d, self.session), self.devices))
        events = [e for d, r in zip(self.devices, results) if (e := self.process(d, r))]
        for e in events:
            self._notify(e)
        return events

    def run_forever(self) -> None:
        log.info("Monitoring boshlandi: %s ta qurilma, har %s s", len(self.devices), self.settings.interval)
        while not self._stop.is_set():
            try:
                self.run_once()
            except Exception:
                log.exception("Tekshiruv aylanishida xato")   # monitoring hech qachon to'xtab qolmasligi kerak
            self._stop.wait(self.settings.interval)

    def stop(self) -> None:
        self._stop.set()

    def _notify(self, e: Event) -> None:
        title = {"DOWN": f"{ICON[DOWN]} ISHLAMAYAPTI", "RECOVERED": f"{ICON[OK]} TIKLANDI",
                 "WARN": f"{ICON[WARN]} OGOHLANTIRISH", "WARN_CLEARED": f"{ICON[OK]} NORMAGA QAYTDI"}[e.kind]
        text = f"{title}\n{e.device.name}\nJoyi: {e.device.location}\n{e.detail}"
        log.warning(text.replace("\n", " | "))
        self.notifier.send(text)


def _since(prev, ts):
    return datetime.fromisoformat(prev["since"]) if prev else ts


def _minutes(opened_iso: str, ts) -> float:
    return round((ts - datetime.fromisoformat(opened_iso)).total_seconds() / 60, 1)
