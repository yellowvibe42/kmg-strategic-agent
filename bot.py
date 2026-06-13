# -*- coding: utf-8 -*-
"""
bot.py — Telegram-бот КМГ.
- Команды: /status /analyze /news /report /help
- Автообновление: сбор данных каждый час, пуш при изменении Brent > $1
Запуск: python bot.py  (работает непрерывно в фоне)
"""

import sys, logging, json, html
from datetime import datetime, timedelta
from pathlib import Path
from telegram import Update, Bot
from telegram.ext import Application, CommandHandler, ContextTypes

if sys.stdout.encoding and sys.stdout.encoding.lower() != "utf-8":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
if sys.stderr.encoding and sys.stderr.encoding.lower() != "utf-8":
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)],
)
log = logging.getLogger(__name__)

CONFIG_PATH = Path(__file__).parent / "config.json"
LEVEL_EMOJI = {"КРИТИЧЕСКИЙ": "🚨", "ВЫСОКИЙ": "⚠️", "ПЛАНОВЫЙ": "✅"}

def load_config():
    return json.loads(CONFIG_PATH.read_text(encoding="utf-8"))

# ---------------------------------------------------------------------------
# /start  /help
# ---------------------------------------------------------------------------
async def cmd_start(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    text = (
        "🛢 <b>КМГ Strategic Agent</b>\n\n"
        "Доступные команды:\n\n"
        "/status   — Brent, KZT/USD и оценка рисков прямо сейчас\n"
        "/analyze  — сценарии: оптимистичный / базовый / стресс\n"
        "/news     — последние новости по КМГ и нефти\n"
        "/report   — PPTX-презентация прямо в чат\n"
        "/help     — эта справка\n\n"
        "📡 <i>Автообновления: каждый час + пуш при изменении Brent на $1+</i>"
    )
    await update.message.reply_text(text, parse_mode="HTML")

async def cmd_help(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    await cmd_start(update, ctx)

# ---------------------------------------------------------------------------
# /status
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
        lines = [
            "📊 <b>Текущие показатели</b>\n",
            f"💰 Brent:   <b>${brent:.2f}/барр.</b>",
            f"💱 KZT/USD: <b>{kzt_usd:.0f}</b>",
            f"🕐 {datetime.now().strftime('%d.%m.%Y %H:%M')}\n",
            "<b>Оценка рисков:</b>",
        ]
        for a in alerts:
            lines.append(f"{LEVEL_EMOJI.get(a.level,'•')} [{a.level}] {html.escape(a.message)}")
        await update.message.reply_text("\n".join(lines), parse_mode="HTML")
    except Exception as ex:
        await update.message.reply_text(f"❌ Ошибка: {html.escape(str(ex))}")

# ---------------------------------------------------------------------------
# /analyze
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
            f"📈 <b>Сценарии 2026</b>  (Brent сейчас: ${brent:.2f})\n",
            f"🟢 <b>Оптимистичный 20% — Brent ${o.brent:.0f}</b>",
            f"   Выручка ${o.revenue:,} млн | EBITDA ${o.ebitda:,} млн | FCF ${o.fcf:,} млн",
            f"   Δ выручка: {o.revenue_delta_pct:+.1f}%\n",
            f"🔵 <b>Базовый 55% — Brent ${b.brent:.0f}</b>",
            f"   Выручка ${b.revenue:,} млн | EBITDA ${b.ebitda:,} млн | FCF ${b.fcf:,} млн",
            f"   Δ выручка: {b.revenue_delta_pct:+.1f}%\n",
            f"🔴 <b>Стрессовый 25% — Brent ${s.brent:.0f}</b>",
            f"   Выручка ${s.revenue:,} млн | EBITDA ${s.ebitda:,} млн | FCF ${s.fcf:,} млн",
            f"   Δ выручка: {s.revenue_delta_pct:+.1f}%",
        ]
        if s.budget_risk:
            lines.append("\n⚠️ Стресс: дефицит бюджета РК (Brent &lt; $75)")
        if s.rating_risk:
            lines.append("⚠️ Стресс: риск снижения рейтинга S&amp;P BBB−")
        await update.message.reply_text("\n".join(lines), parse_mode="HTML")
    except Exception as ex:
        await update.message.reply_text(f"❌ Ошибка: {html.escape(str(ex))}")

# ---------------------------------------------------------------------------
# /news
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
            await update.message.reply_text("Новостей пока нет.")
            return
        lines = ["📰 <b>Последние новости</b>\n"]
        for n in news:
            lines.append(f"• [{html.escape(n['source'])}] {html.escape(n['title'][:110])}")
        await update.message.reply_text("\n".join(lines), parse_mode="HTML")
    except Exception as ex:
        await update.message.reply_text(f"❌ Ошибка: {html.escape(str(ex))}")

# ---------------------------------------------------------------------------
# /report
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
# Автообновление — каждый час + пуш при изменении Brent на $1+
# ---------------------------------------------------------------------------
_last_brent: float = 0.0
_last_auto_push: datetime = datetime.min

async def auto_update(ctx: ContextTypes.DEFAULT_TYPE):
    """Вызывается планировщиком каждые 30 минут."""
    global _last_brent, _last_auto_push
    cfg = load_config()
    chat_id = cfg.get("telegram_chat_id")
    if not chat_id:
        return

    try:
        from collector import collect_all, get_latest
        from analyzer import check_triggers
        collect_all()
        brent   = get_latest("Brent_USD") or 0
        kzt_usd = get_latest("KZT_USD")   or 0
        alerts  = check_triggers(brent, kzt_usd)
        now     = datetime.now()

        brent_change  = abs(brent - _last_brent) if _last_brent else 0
        hour_elapsed  = (now - _last_auto_push) >= timedelta(hours=1)
        critical_alert = any(a.level == "КРИТИЧЕСКИЙ" for a in alerts)

        # Пушим если: критический алерт ИЛИ Brent изменился на $1+ ИЛИ прошёл час
        should_push = critical_alert or brent_change >= 1.0 or hour_elapsed

        if not should_push:
            return

        _last_brent     = brent
        _last_auto_push = now

        lines = [
            f"📡 <b>Автообновление</b> {now.strftime('%d.%m %H:%M')}\n",
            f"💰 Brent:   <b>${brent:.2f}/барр.</b>",
            f"💱 KZT/USD: <b>{kzt_usd:.0f}</b>\n",
        ]

        # Показываем только не-плановые алерты, если всё тихо — пишем OK
        non_routine = [a for a in alerts if a.level != "ПЛАНОВЫЙ"]
        if non_routine:
            for a in non_routine:
                lines.append(f"{LEVEL_EMOJI.get(a.level,'•')} [{a.level}] {html.escape(a.message)}")
        else:
            lines.append("✅ Параметры в норме. Базовый сценарий.")

        if brent_change >= 1.0:
            direction = "▲" if brent > _last_brent else "▼"
            lines.append(f"\n{direction} Brent изменился на ${brent_change:.2f} с последнего обновления")

        await ctx.bot.send_message(chat_id=chat_id, text="\n".join(lines), parse_mode="HTML")
        log.info("Автообновление отправлено. Brent=%.2f, Δ=%.2f", brent, brent_change)

    except Exception as ex:
        log.error("Автообновление: ошибка %s", ex)

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

    # Автообновление каждые 30 минут
    app.job_queue.run_repeating(auto_update, interval=1800, first=10)

    log.info("Бот запущен. Автообновление каждые 30 мин. Жду команды...")
    app.run_polling(drop_pending_updates=True)

if __name__ == "__main__":
    main()
