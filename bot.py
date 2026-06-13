# -*- coding: utf-8 -*-
"""
bot.py — Telegram-бот с командами для получения данных КМГ.
Запуск: python bot.py
"""

import sys, logging, json
from pathlib import Path
from telegram import Update
from telegram.ext import Application, CommandHandler, ContextTypes

if sys.stdout.encoding and sys.stdout.encoding.lower() != "utf-8":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)],
)
log = logging.getLogger(__name__)

CONFIG_PATH = Path(__file__).parent / "config.json"

def load_config():
    return json.loads(CONFIG_PATH.read_text(encoding="utf-8"))

# ---------------------------------------------------------------------------
# /start
# ---------------------------------------------------------------------------
async def cmd_start(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    text = (
        "🛢 <b>КМГ Strategic Agent</b>\n\n"
        "Доступные команды:\n\n"
        "/status   — Brent, KZT/USD и алерты прямо сейчас\n"
        "/analyze  — сценарии: оптимистичный / базовый / стресс\n"
        "/news     — последние новости по КМГ и нефти\n"
        "/report   — сгенерировать и прислать PPTX-презентацию\n"
        "/help     — эта справка"
    )
    await update.message.reply_text(text, parse_mode="HTML")

# ---------------------------------------------------------------------------
# /status — текущие данные + алерты
# ---------------------------------------------------------------------------
async def cmd_status(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("⏳ Собираю данные...", parse_mode="HTML")
    try:
        from collector import collect_all, get_latest
        from analyzer import check_triggers
        collect_all()
        brent   = get_latest("Brent_USD") or 0
        kzt_usd = get_latest("KZT_USD")   or 0
        alerts  = check_triggers(brent, kzt_usd)

        level_emoji = {"КРИТИЧЕСКИЙ": "🚨", "ВЫСОКИЙ": "⚠️", "ПЛАНОВЫЙ": "✅"}

        lines = [
            "📊 <b>Текущие показатели</b>\n",
            f"💰 Brent:   <b>${brent:.2f}/барр.</b>",
            f"💱 KZT/USD: <b>{kzt_usd:.0f}</b>",
            "",
            "<b>Оценка рисков:</b>",
        ]
        for a in alerts:
            e = level_emoji.get(a.level, "•")
            lines.append(f"{e} [{a.level}] {a.message}")

        await update.message.reply_text("\n".join(lines), parse_mode="HTML")
    except Exception as ex:
        await update.message.reply_text(f"❌ Ошибка: {ex}")

# ---------------------------------------------------------------------------
# /analyze — таблица сценариев
# ---------------------------------------------------------------------------
async def cmd_analyze(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("⏳ Считаю сценарии...", parse_mode="HTML")
    try:
        from collector import get_latest
        from analyzer import run_all_scenarios
        brent = get_latest("Brent_USD") or 85.0
        r = run_all_scenarios(brent)

        o, b, s = r["optimistic"], r["base"], r["stress"]

        lines = [
            "📈 <b>Сценарии 2026</b>\n",
            f"<b>Оптимистичный (20%) — Brent ${o.brent:.0f}</b>",
            f"  Выручка: ${o.revenue:,} млн  |  EBITDA: ${o.ebitda:,} млн  |  FCF: ${o.fcf:,} млн",
            f"  Δ выручка: {o.revenue_delta_pct:+.1f}%",
            "",
            f"<b>Базовый (55%) — Brent ${b.brent:.0f}</b>",
            f"  Выручка: ${b.revenue:,} млн  |  EBITDA: ${b.ebitda:,} млн  |  FCF: ${b.fcf:,} млн",
            f"  Δ выручка: {b.revenue_delta_pct:+.1f}%",
            "",
            f"<b>Стрессовый (25%) — Brent ${s.brent:.0f}</b>",
            f"  Выручка: ${s.revenue:,} млн  |  EBITDA: ${s.ebitda:,} млн  |  FCF: ${s.fcf:,} млн",
            f"  Δ выручка: {s.revenue_delta_pct:+.1f}%",
        ]
        if s.budget_risk:
            lines.append("\n⚠️ Стресс-сценарий: дефицит бюджета РК (Brent < $75)")
        if s.rating_risk:
            lines.append("⚠️ Стресс-сценарий: риск снижения рейтинга S&P BBB−")

        await update.message.reply_text("\n".join(lines), parse_mode="HTML")
    except Exception as ex:
        await update.message.reply_text(f"❌ Ошибка: {ex}")

# ---------------------------------------------------------------------------
# /news — последние новости
# ---------------------------------------------------------------------------
async def cmd_news(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("⏳ Загружаю новости...", parse_mode="HTML")
    try:
        from collector import get_recent_news, fetch_news, init_db
        conn = init_db()
        fetch_news(conn)
        conn.close()
        news = get_recent_news(limit=8)

        if not news:
            await update.message.reply_text("Новостей не найдено.")
            return

        lines = ["📰 <b>Последние новости</b>\n"]
        for n in news:
            title = n["title"][:120]
            source = n["source"]
            lines.append(f"• [{source}] {title}")

        await update.message.reply_text("\n".join(lines), parse_mode="HTML")
    except Exception as ex:
        await update.message.reply_text(f"❌ Ошибка: {ex}")

# ---------------------------------------------------------------------------
# /report — генерация и отправка PPTX
# ---------------------------------------------------------------------------
async def cmd_report(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("⏳ Генерирую презентацию...", parse_mode="HTML")
    try:
        from reporter import generate_reports
        paths = generate_reports()
        pptx = paths.get("pptx")
        if pptx and pptx.exists():
            await update.message.reply_document(
                document=open(pptx, "rb"),
                filename=pptx.name,
                caption="📊 КМГ Strategic — сценарии и риски",
            )
        else:
            await update.message.reply_text("❌ Файл не создан.")
    except Exception as ex:
        await update.message.reply_text(f"❌ Ошибка: {ex}")

# ---------------------------------------------------------------------------
# /help
# ---------------------------------------------------------------------------
async def cmd_help(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    await cmd_start(update, ctx)

# ---------------------------------------------------------------------------
# Запуск
# ---------------------------------------------------------------------------
def main():
    cfg = load_config()
    token = cfg.get("telegram_token")
    if not token:
        print("Ошибка: telegram_token не задан в config.json")
        sys.exit(1)

    app = Application.builder().token(token).build()
    app.add_handler(CommandHandler("start",   cmd_start))
    app.add_handler(CommandHandler("help",    cmd_help))
    app.add_handler(CommandHandler("status",  cmd_status))
    app.add_handler(CommandHandler("analyze", cmd_analyze))
    app.add_handler(CommandHandler("news",    cmd_news))
    app.add_handler(CommandHandler("report",  cmd_report))

    log.info("Бот запущен. Ожидаю команды...")
    app.run_polling(drop_pending_updates=True)

if __name__ == "__main__":
    main()
