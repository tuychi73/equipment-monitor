import socket
import threading

import pytest

from monitor import checks
from monitor.checks import CheckResult
from monitor.config import Device, Settings, _validate
from monitor.engine import Monitor
from monitor.notify import ConsoleNotifier, TelegramNotifier
from monitor.storage import Storage

ROBOT = Device(id="r1", name="Robo-gid", type="robot", location="1-qavat", check="http", url="http://x",
               min={"battery": 20}, expect={"lidar": ["ok"]})
UP = CheckResult(True, 12.0, "HTTP 200", {"battery": 80, "lidar": "ok"})
DOWN = CheckResult(False, detail="ulanib bo'lmadi")


@pytest.fixture
def mon():
    return Monitor(Settings(fail_threshold=2), [ROBOT], Storage(":memory:"), ConsoleNotifier(), session=object())


def test_evaluate_thresholds():
    assert checks.evaluate(ROBOT, UP)[0] == "OK"
    low = CheckResult(True, 10.0, "", {"battery": 12, "lidar": "ok"})
    assert checks.evaluate(ROBOT, low) == ("WARN", "battery=12 (min 20)")
    broken = CheckResult(True, 10.0, "", {"battery": 90, "lidar": "error"})
    assert checks.evaluate(ROBOT, broken)[0] == "WARN"
    assert checks.evaluate(ROBOT, DOWN)[0] == "DOWN"


def test_single_failure_is_not_an_alarm(mon):
    mon.process(ROBOT, UP)
    assert mon.process(ROBOT, DOWN) is None                      # 1-xato: hali signal yo'q
    assert mon.storage.get_state("r1")["status"] == "OK"
    assert mon.process(ROBOT, UP) is None                        # tiklandi - nosozlik ochilmadi
    assert mon.storage.incidents() == []


def test_down_then_recovered_opens_and_closes_incident(mon):
    mon.process(ROBOT, UP)
    mon.process(ROBOT, DOWN)
    ev = mon.process(ROBOT, DOWN)                                 # 2-xato: DOWN tasdiqlandi
    assert ev.kind == "DOWN"
    assert mon.process(ROBOT, DOWN) is None                      # takroriy signal yuborilmaydi
    inc = mon.storage.incidents()
    assert len(inc) == 1 and inc[0]["closed_at"] is None

    ev = mon.process(ROBOT, UP)
    assert ev.kind == "RECOVERED"
    inc = mon.storage.incidents()
    assert inc[0]["closed_at"] is not None
    assert mon.storage.mttr_minutes() is not None
    assert 0 < mon.storage.uptime("r1") < 100


def test_warn_cycle(mon):
    low = CheckResult(True, 10.0, "", {"battery": 15, "lidar": "ok"})
    assert mon.process(ROBOT, low).kind == "WARN"
    assert mon.process(ROBOT, low) is None
    assert mon.process(ROBOT, UP).kind == "WARN_CLEARED"
    assert [i["kind"] for i in mon.storage.incidents()] == ["WARN"]


def test_tcp_check_open_and_closed_port():
    srv = socket.socket()
    srv.bind(("127.0.0.1", 0))
    srv.listen()
    port = srv.getsockname()[1]
    threading.Thread(target=lambda: srv.accept()[0].close(), daemon=True).start()
    assert checks.tcp("127.0.0.1", port, 1).reachable
    srv.close()
    assert not checks.tcp("127.0.0.1", port, 0.5).reachable


def test_ping_localhost():
    assert checks.ping("127.0.0.1", 1).reachable


def test_http_check_against_simulator():
    from fastapi.testclient import TestClient
    from simulator.__main__ import app
    client = TestClient(app)
    r = checks.http(client, "/printer/1/status", 2)
    assert r.reachable and "hotend_temp" in r.metrics
    client.post("/sim/printer-1/fail", params={"seconds": 30})
    r = checks.http(client, "/printer/1/status", 2)
    assert not r.reachable and r.detail == "HTTP 503"


def test_telegram_notifier_payload():
    calls = []

    class FakeSession:
        def post(self, url, json, timeout):
            calls.append((url, json))
            return type("R", (), {"status_code": 200})()

    TelegramNotifier("TOKEN", "123", FakeSession()).send("salom")
    assert calls == [("https://api.telegram.org/botTOKEN/sendMessage", {"chat_id": "123", "text": "salom"})]


def test_config_validation():
    with pytest.raises(ValueError):
        _validate([Device(id="a", name="a", type="pc", location="", check="tcp", host="h")])   # port yo'q
    with pytest.raises(ValueError):
        _validate([ROBOT, ROBOT])                                                            # dublikat id
