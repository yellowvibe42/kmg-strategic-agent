# -*- coding: utf-8 -*-
"""
main.py — точка входа агента КМГ.
Запуск: python main.py [--collect | --analyze | --brief | --report | --alerts | --all]
Планировщик: python main.py --schedule  (запускает APScheduler)
"""

import argparse
import logging
import sys
import json
from pathlib import Path

# Фикс кодировки Windows-консоли
if sys.stdout.encoding and sys.stdout.encoding.lower() != "utf-8":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
if sys.stderr.encoding and sys.stderr.encoding.lower() != "utf-8":
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
log = logging.getLogger(__name__)

CONFIG_PATH = Path(__file__).parent / "config.json"


# ---------------------------------------------------------------------------
# Команды
# ---------------------------------------------------------------------------

def cmd_collect():
    """Сбор данных из всех источников."""
    from collector import collect_all
    results = collect_all()
    print(f"\n  Brent:   ${results['brent']}/барр." if results['brent'] else "  Brent: н/д")
    print(f"  KZT/USD: {results['kzt_usd']}" if results['kzt_usd'] else "  KZT/USD: н/д")
    print(f"  KMGZ:    {results['kmgz']}" if results['kmgz'] else "  KMGZ: н/д")
    print(f"  Новостей: {results['news_count']}")


def cmd_analyze():
    """Расчёт сценариев и проверка триггеров."""
    from collector import get_latest
    from analyzer import run_all_scenarios, check_triggers, print_scenarios

    brent   = get_latest("Brent_USD")
    kzt_usd = get_latest("KZT_USD")
    print(f"\n  Данные: Brent={brent}, KZT/USD={kzt_usd}")

    scenarios = run_all_scenarios(brent)
    print_scenarios(scenarios)

    alerts = check_triggers(brent, kzt_usd)
    print("\n=== Алерты ===")
    for a in alerts:
        print(f"  [{a.level}] {a.metric}: {a.message}")


def cmd_brief():
    """Генерация брифинга через Claude API."""
    from llm_agent import run_daily_briefing
    briefing = run_daily_briefing()
    print("\n" + briefing)


def cmd_report():
    """Генерация DOCX и PPTX отчётов."""
    from reporter import generate_reports
    paths = generate_reports()
    print("\n  Отчёты сохранены:")
    for fmt, p in paths.items():
        print(f"    {fmt.upper()}: {p}")


def cmd_alerts(force: bool = False):
    """Проверка триггеров и отправка Telegram-алертов."""
    from collector import get_latest
    from analyzer import check_triggers
    from alerts import notify

    brent   = get_latest("Brent_USD")
    kzt_usd = get_latest("KZT_USD")
    alert_list = check_triggers(brent, kzt_usd)
    notify(alert_list, brent, kzt_usd, force=force)


def cmd_all():
    """Полный цикл: сбор → анализ → брифинг → отчёты → алерты."""
    log.info("=== Полный цикл агента ===")
    cmd_collect()

    from collector import get_latest
    from analyzer import run_all_scenarios, check_triggers
    from alerts import notify
    from llm_agent import run_daily_briefing
    from reporter import generate_reports

    brent   = get_latest("Brent_USD") or 85.0
    kzt_usd = get_latest("KZT_USD")   or 485.0

    alerts = check_triggers(brent, kzt_usd)

    briefing = run_daily_briefing()
    paths = generate_reports(briefing)

    notify(alerts, brent, kzt_usd)

    print("\n=== Готово ===")
    print(f"  Брифинг: reports/briefing_{__import__('datetime').date.today()}.md")
    for fmt, p in paths.items():
        print(f"  {fmt.upper()}: {p}")


# ---------------------------------------------------------------------------
# Планировщик (APScheduler)
# ---------------------------------------------------------------------------

def cmd_schedule():
    """Запускает планировщик: сбор в 07:00, брифинг в 07:30, алерты каждые 2ч."""
    try:
        from apscheduler.schedulers.blocking import BlockingScheduler
    except ImportError:
        print("Установите: pip install apscheduler")
        sys.exit(1)

    scheduler = BlockingScheduler(timezone="Asia/Almaty")

    scheduler.add_job(cmd_collect, "cron", hour=7,  minute=0,  id="collect")
    scheduler.add_job(cmd_all,     "cron", hour=7,  minute=30, id="briefing")
    scheduler.add_job(cmd_alerts,  "cron", hour="*/2", id="alerts")

    log.info("Планировщик запущен (Ctrl+C для остановки).")
    log.info("  07:00 — сбор данных")
    log.info("  07:30 — полный брифинг + отчёты")
    log.info("  кажд. 2ч — проверка алертов")

    try:
        scheduler.start()
    except KeyboardInterrupt:
        log.info("Планировщик остановлен.")


# ---------------------------------------------------------------------------
# Настройка
# ---------------------------------------------------------------------------

def cmd_setup():
    """Интерактивная настройка API ключей."""
    print("\n=== Настройка КМГ Strategic Agent ===\n")

    cfg = {}
    if CONFIG_PATH.exists():
        cfg = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))

    # Anthropic API Key
    current = cfg.get("anthropic_api_key", "")
    hint = f" [уже задан: {current[:8]}...]" if current else ""
    key = input(f"Anthropic API Key{hint}: ").strip()
    if key:
        cfg["anthropic_api_key"] = key

    # Telegram (необязательно)
    setup_tg = input("\nНастроить Telegram алерты? (y/n): ").strip().lower()
    if setup_tg == "y":
        from alerts import setup_telegram
        setup_telegram()
        if CONFIG_PATH.exists():
            tg_cfg = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
            cfg.update(tg_cfg)

    CONFIG_PATH.write_text(json.dumps(cfg, ensure_ascii=False, indent=2), encoding="utf-8")
    print("\n✅ Настройки сохранены в config.json")


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(
        description="КМГ Strategic AI Agent",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Команды:
  --collect    Собрать данные (Brent, KZT/USD, KMGZ, новости)
  --analyze    Рассчитать сценарии и проверить триггеры
  --brief      Сгенерировать брифинг (требует Anthropic API Key)
  --report     Сгенерировать DOCX и PPTX
  --alerts     Проверить и отправить Telegram-алерты
  --all        Полный цикл (collect + brief + report + alerts)
  --schedule   Запустить планировщик (ежедневно, автоматически)
  --setup      Настройка API ключей
        """,
    )
    parser.add_argument("--collect",  action="store_true")
    parser.add_argument("--analyze",  action="store_true")
    parser.add_argument("--brief",    action="store_true")
    parser.add_argument("--report",   action="store_true")
    parser.add_argument("--alerts",   action="store_true")
    parser.add_argument("--force",    action="store_true", help="Отправить алерты принудительно")
    parser.add_argument("--all",      action="store_true")
    parser.add_argument("--schedule", action="store_true")
    parser.add_argument("--setup",    action="store_true")

    args = parser.parse_args()

    if args.setup:    cmd_setup()
    elif args.collect: cmd_collect()
    elif args.analyze: cmd_analyze()
    elif args.brief:   cmd_brief()
    elif args.report:  cmd_report()
    elif args.alerts:  cmd_alerts(force=args.force)
    elif args.all:     cmd_all()
    elif args.schedule: cmd_schedule()
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
