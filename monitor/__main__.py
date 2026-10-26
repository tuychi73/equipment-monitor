"""CLI:
    python -m monitor serve  [--config devices.toml] [--port 8080]   # monitoring + dashboard
    python -m monitor once   [--config devices.toml]                 # bitta tekshiruv, jadval ko'rinishida
    python -m monitor report [--config devices.toml]                 # uptime, nosozliklar, MTTR
"""
from __future__ import annotations

import argparse
import logging
import sys

import requests

from monitor import config, notify
from monitor.engine import Monitor
from monitor.storage import Storage


def _build(cfg_path: str) -> Monitor:
    settings, devices = config.load(cfg_path)
    session = requests.Session()
    return Monitor(settings, devices, Storage(settings.db_path), notify.build(settings, session), session)


def main(argv=None) -> int:
    p = argparse.ArgumentParser(prog="monitor", description="Uskunalar holatini kuzatish")
    p.add_argument("cmd", choices=["serve", "once", "report"])
    p.add_argument("--config", default="devices.toml")
    p.add_argument("--port", type=int, default=8080)
    args = p.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")   # Windows konsolida emoji/o'zbekcha harflar uchun

    mon = _build(args.config)

    if args.cmd == "serve":
        import uvicorn
        from monitor.web import create_app
        print(f"Dashboard: http://localhost:{args.port}")
        uvicorn.run(create_app(mon), host="0.0.0.0", port=args.port, log_level="warning")
        return 0

    if args.cmd == "once":
        for _ in range(mon.settings.fail_threshold):   # DOWN tasdiqlanishi uchun N marta
            mon.run_once()
    st = mon.storage
    print(f"\n{'Qurilma':<34}{'Holat':<8}{'Uptime 24h':>11}  {'Javob':>9}  Izoh")
    print("-" * 96)
    for d in mon.devices:
        s, last = st.get_state(d.id), st.last_check(d.id)
        up = st.uptime(d.id)
        lat = f"{last['latency_ms']} ms" if last and last["latency_ms"] is not None else "—"
        print(f"{d.name[:33]:<34}{(s['status'] if s else '—'):<8}{(f'{up}%' if up is not None else '—'):>11}  "
              f"{lat:>9}  {last['detail'] if last else ''}")
    if args.cmd == "report":
        inc = st.incidents(1000)
        print(f"\nNosozliklar: {len(inc)} ta, ochiq: {sum(1 for i in inc if not i['closed_at'])} ta, "
              f"MTTR: {st.mttr_minutes() or '—'} daqiqa")
    return 0


if __name__ == "__main__":
    sys.exit(main())
