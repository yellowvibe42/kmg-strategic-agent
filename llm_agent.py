"""
llm_agent.py — анализ новостей и генерация брифинга через Claude API.
"""

import os
import json
import logging
from datetime import date
from pathlib import Path
from anthropic import Anthropic
from collector import get_latest, get_recent_news
from analyzer import run_all_scenarios, check_triggers, ScenarioResult

log = logging.getLogger(__name__)

CONFIG_PATH = Path(__file__).parent / "config.json"
REPORTS_DIR = Path(__file__).parent / "reports"
REPORTS_DIR.mkdir(exist_ok=True)

PRD_PATH = Path(__file__).parent.parent / "KMG_Strategic_PRD.md"


def load_config() -> dict:
    if CONFIG_PATH.exists():
        return json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
    return {}


def get_client() -> Anthropic:
    cfg = load_config()
    api_key = cfg.get("anthropic_api_key") or os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        raise ValueError(
            "API ключ не найден. Добавьте anthropic_api_key в config.json "
            "или установите переменную ANTHROPIC_API_KEY."
        )
    return Anthropic(api_key=api_key)


# ---------------------------------------------------------------------------
# Системный промпт
# ---------------------------------------------------------------------------

SYSTEM_PROMPT = """Ты — стратегический аналитик АО НК «КазМунайГаз» (КМГ).
Твоя задача: анализировать внешние факторы и готовить краткие брифинги для руководства.

Ключевые ориентиры из стратегического PRD:
- Базовые показатели 2025: Выручка $17.977 млрд, EBITDA $4.591 млрд, FCF $2.365 млрд
- Критический порог Brent: $75/барр. (ниже — дефицит бюджета РК, стресс-сценарий)
- КТК = 80% нефтяного экспорта Казахстана; потери при остановке — $15–20 млн/сут.
- ОПЕК+: Казахстан должен компенсировать 2.63 млн барр./сут. (55% от общего объёма)
- Арбитраж Кашаган: условное обязательство $4.8 млрд (в 6.5× превышает чистый долг)
- Рейтинг S&P: BBB− (инвестиционный, присвоен июнь 2025)

Формат ответа — чёткий, структурированный markdown. Без воды, только факты и выводы.
Язык: русский."""


# ---------------------------------------------------------------------------
# Анализ новостей
# ---------------------------------------------------------------------------

def analyze_news(news_items: list[dict], brent: float, kzt_usd: float) -> str:
    """Отправляет свежие новости в Claude для краткого анализа."""
    if not news_items:
        return "_Новостей за период не найдено._"

    client = get_client()
    news_text = "\n".join(
        f"- [{n['source']}] {n['title']}" for n in news_items[:15]
    )

    prompt = f"""Текущие рыночные данные:
- Brent: ${brent:.2f}/барр.
- KZT/USD: {kzt_usd:.0f}

Свежие новости (последние 24 часа):
{news_text}

Задача: выдели 2–3 новости, которые наиболее значимы для КМГ.
Для каждой: одна строка — суть события, одна строка — финансовое влияние на КМГ.
Формат: **Новость**: ... / **Влияние**: ..."""

    response = client.messages.create(
        model="claude-haiku-4-5-20251001",
        max_tokens=600,
        system=SYSTEM_PROMPT,
        messages=[{"role": "user", "content": prompt}],
    )
    return response.content[0].text


# ---------------------------------------------------------------------------
# Генерация ежедневного брифинга
# ---------------------------------------------------------------------------

def generate_briefing(scenarios: dict[str, ScenarioResult],
                      alerts: list,
                      news_analysis: str,
                      brent: float,
                      kzt_usd: float) -> str:
    """Генерирует полный ежедневный брифинг."""
    client = get_client()

    s_opt  = scenarios["optimistic"]
    s_base = scenarios["base"]
    s_str  = scenarios["stress"]

    alert_lines = "\n".join(f"- [{a.level}] {a.message}" for a in alerts)

    scenario_table = f"""
| Сценарий | Brent | Выручка | EBITDA | FCF | Δ выручка |
|---|---|---|---|---|---|
| Оптимистичный (20%) | ${s_opt.brent:.0f} | ${s_opt.revenue:,} млн | ${s_opt.ebitda:,} млн | ${s_opt.fcf:,} млн | {s_opt.revenue_delta_pct:+.1f}% |
| Базовый (55%) | ${s_base.brent:.0f} | ${s_base.revenue:,} млн | ${s_base.ebitda:,} млн | ${s_base.fcf:,} млн | {s_base.revenue_delta_pct:+.1f}% |
| Стрессовый (25%) | ${s_str.brent:.0f} | ${s_str.revenue:,} млн | ${s_str.ebitda:,} млн | ${s_str.fcf:,} млн | {s_str.revenue_delta_pct:+.1f}% |
"""

    prompt = f"""Подготовь ежедневный стратегический брифинг КМГ на {date.today().strftime('%d %B %Y')}.

Текущие рыночные показатели:
- Brent: ${brent:.2f}/барр.
- KZT/USD: {kzt_usd:.0f}

Активные алерты:
{alert_lines}

Расчётные сценарии 2026:
{scenario_table}

Анализ новостей:
{news_analysis}

Структура брифинга:
1. **Резюме дня** (3–4 предложения: ключевое событие + влияние на КМГ)
2. **Рыночные индикаторы** (таблица выше)
3. **Активные риски** (из алертов, кратко)
4. **Новости дня** (анализ выше)
5. **Рекомендуемые действия на сегодня** (1–3 конкретных действия)

Объём: не более 400 слов. Язык: деловой русский."""

    response = client.messages.create(
        model="claude-sonnet-4-6",
        max_tokens=1200,
        system=SYSTEM_PROMPT,
        messages=[{"role": "user", "content": prompt}],
    )
    return response.content[0].text


# ---------------------------------------------------------------------------
# Главная функция
# ---------------------------------------------------------------------------

def run_daily_briefing() -> str:
    """Полный цикл: данные → анализ → брифинг → сохранение файла."""
    brent   = get_latest("Brent_USD") or 85.0
    kzt_usd = get_latest("KZT_USD")   or 485.0

    log.info("Генерация брифинга: Brent=%.2f, KZT/USD=%.0f", brent, kzt_usd)

    scenarios = run_all_scenarios(brent)
    alerts    = check_triggers(brent, kzt_usd)
    news      = get_recent_news(limit=20)

    news_analysis = analyze_news(news, brent, kzt_usd)
    briefing = generate_briefing(scenarios, alerts, news_analysis, brent, kzt_usd)

    # Сохранение
    today = date.today().isoformat()
    md_path = REPORTS_DIR / f"briefing_{today}.md"
    md_path.write_text(
        f"# КМГ Стратегический брифинг — {today}\n\n{briefing}\n",
        encoding="utf-8",
    )
    log.info("Брифинг сохранён: %s", md_path)
    return briefing


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
    print(run_daily_briefing())
