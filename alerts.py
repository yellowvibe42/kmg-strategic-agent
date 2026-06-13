"""
alerts.py — Telegram-алерты при пересечении триггерных значений (бесплатно).
Telegram Bot API: создайте бота через @BotFather, получите TOKEN и CHAT_ID.
"""

import json
import logging
import requests
from pathlib import Path
from analyzer import Alert

log = logging.getLogger(__name__)

CONFIG_PATH = Path(__file__).parent / "config.json"

# ---------------------------------------------------------------------------
# Конфигурация (хранится в config.json, не в коде)
# ---------------------------------------------------------------------------

def load_config() -> dict:
    if CONFIG_PATH.exists():
        return json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
    return {}


def save_config(cfg: dict):
    CONFIG_PATH.write_text(
        json.dumps(cfg, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


# ---------------------------------------------------------------------------
# Telegram отправка
# ---------------------------------------------------------------------------

LEVEL_EMOJI = {
    "КРИТИЧЕСКИЙ": "🚨",
    "ВЫСОКИЙ":     "⚠️",
    "ПЛАНОВЫЙ":    "✅",
}


def send_telegram(token: str, chat_id: str, text: str) -> bool:
    url = f"https://api.telegram.org/bot{token}/sendMessage"
    try:
        r = requests.post(url, json={
            "chat_id": chat_id,
            "text": text,
            "parse_mode": "HTML",
        }, timeout=10)
        r.raise_for_status()
        log.info("Telegram отправлен: %s...", text[:60])
        return True
    except Exception as exc:
        log.error("Telegram ошибка: %s", exc)
        return False


def format_alert_message(alerts: list[Alert],
                          brent: float | None,
                          kzt_usd: float | None) -> str:
    lines = ["<b>КМГ Strategic — Мониторинг рисков</b>"]
    if brent:
        lines.append(f"💰 Brent: <b>${brent:.2f}/барр.</b>")
    if kzt_usd:
        lines.append(f"💱 KZT/USD: <b>{kzt_usd:.0f}</b>")
    lines.append("")
    for a in alerts:
        emoji = LEVEL_EMOJI.get(a.level, "•")
        lines.append(f"{emoji} <b>[{a.level}]</b> {a.message}")
    return "\n".join(lines)


def notify(alerts: list[Alert],
           brent: float | None = None,
           kzt_usd: float | None = None,
           force: bool = False):
    """
    Отправляет алерты в Telegram.
    force=True — отправить даже если уровень ПЛАНОВЫЙ.
    """
    cfg = load_config()
    token   = cfg.get("telegram_token")
    chat_id = cfg.get("telegram_chat_id")

    if not token or not chat_id:
        log.warning("Telegram не настроен. Запустите: python setup.py")
        _print_alerts(alerts)
        return

    # Фильтр: ПЛАНОВЫЙ отправляем только при force=True
    to_send = [a for a in alerts if force or a.level != "ПЛАНОВЫЙ"]
    if not to_send:
        log.info("Нет алертов для отправки (все ПЛАНОВЫЙ).")
        return

    text = format_alert_message(to_send, brent, kzt_usd)
    send_telegram(token, chat_id, text)


def _print_alerts(alerts: list[Alert]):
    """Консольный вывод если Telegram не настроен."""
    for a in alerts:
        emoji = LEVEL_EMOJI.get(a.level, "•")
        print(f"  {emoji} [{a.level}] {a.metric}: {a.message}")


# ---------------------------------------------------------------------------
# Настройка Telegram (интерактивно)
# ---------------------------------------------------------------------------

def setup_telegram():
    """Сохраняет токен и chat_id в config.json."""
    print("\n=== Настройка Telegram-алертов ===")
    print("1. Откройте Telegram, найдите @BotFather")
    print("2. Отправьте /newbot и получите TOKEN")
    print("3. Напишите своему боту любое сообщение")
    print("4. Откройте: https://api.telegram.org/bot<TOKEN>/getUpdates")
    print("   и найдите chat.id в ответе\n")

    token   = input("Введите TOKEN бота: ").strip()
    chat_id = input("Введите CHAT_ID: ").strip()

    cfg = load_config()
    cfg["telegram_token"]   = token
    cfg["telegram_chat_id"] = chat_id
    save_config(cfg)

    # Тестовая отправка
    ok = send_telegram(token, chat_id,
                       "✅ <b>КМГ Strategic Agent</b>\nAlerts настроены и работают!")
    if ok:
        print("✅ Telegram настроен успешно!")
    else:
        print("❌ Ошибка. Проверьте TOKEN и CHAT_ID.")


if __name__ == "__main__":
    setup_telegram()
