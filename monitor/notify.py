"""Xabar yuborish: Telegram bot yoki (token bo'lmasa) faqat konsol."""
from __future__ import annotations

import logging
from typing import Protocol

log = logging.getLogger(__name__)


class Notifier(Protocol):
    def send(self, text: str) -> None: ...


class ConsoleNotifier:
    def __init__(self):
        self.sent: list[str] = []

    def send(self, text: str) -> None:
        self.sent.append(text)
        print("\n" + text + "\n")


class TelegramNotifier:
    """Telegram Bot API: https://core.telegram.org/bots/api#sendmessage"""

    def __init__(self, token: str, chat_id: str, session):
        self.url = f"https://api.telegram.org/bot{token}/sendMessage"
        self.chat_id = chat_id
        self.session = session

    def send(self, text: str) -> None:
        try:
            r = self.session.post(self.url, json={"chat_id": self.chat_id, "text": text}, timeout=10)
            if r.status_code != 200:
                log.error("Telegram xato javob berdi: HTTP %s", r.status_code)
        except Exception as exc:
            # Internet uzilsa ham monitoring ishlashda davom etadi
            log.error("Telegram'ga yuborib bo'lmadi: %s", exc.__class__.__name__)


def build(settings, session) -> Notifier:
    if settings.telegram_token and settings.telegram_chat_id:
        return TelegramNotifier(settings.telegram_token, settings.telegram_chat_id, session)
    log.info("TELEGRAM_BOT_TOKEN berilmagan - xabarlar faqat konsolga chiqadi")
    return ConsoleNotifier()
