"""
analyzer.py — расчёт финансовых сценариев КМГ по формулам из PRD §2.1
Использует данные из SQLite (collector.py) и константы базового года 2025.
"""

import sqlite3
import logging
from dataclasses import dataclass
from pathlib import Path
from collector import get_latest, get_history, DB_PATH

log = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Базовые показатели КМГ 2025 (факт, из PRD §1)
# ---------------------------------------------------------------------------

BASE_2025 = {
    "revenue_usd":    17_977,   # млн USD
    "ebitda_usd":      4_591,   # млн USD
    "ebitda_adj":      4_980,   # скорректированный, млн USD
    "fcf_usd":         2_365,   # млн USD
    "capex_usd":       1_309,   # млн USD
    "net_debt_usd":      720,   # млн USD
    "gross_debt_usd":  6_967,   # млн USD
    "production_kt":  26_211,   # тыс. тонн (нефть + конденсат)
    "brent_avg_2025":    109,   # средний Brent за 2025, USD/барр.
}

# Чувствительность: $10/барр. Brent → изменение выручки и EBITDA
# Знак определяется знаком brent_10_steps (положит. = рост цены, отриц. = падение)
SENSITIVITY_PER_10_BRENT = {
    "revenue_per_10": 1_200,   # млн USD на каждые $10 изменения Brent
    "ebitda_per_10":    450,   # млн USD на каждые $10 изменения Brent
}

# Порог бюджетного дефицита РК
BUDGET_BREAK_EVEN_BRENT = 75  # USD/барр.

# Сценарные диапазоны Brent (из PRD §3)
SCENARIOS = {
    "optimistic": {"brent_lo": 92,  "brent_hi": 110, "probability": 0.20},
    "base":       {"brent_lo": 78,  "brent_hi": 88,  "probability": 0.55},
    "stress":     {"brent_lo": 65,  "brent_hi": 75,  "probability": 0.25},
}

# Дополнительный рост OPEX в 2026 из-за инфляции (PRD §2.6)
OPEX_GROWTH_2026 = 400  # млн USD (середина диапазона 300–500)

# Дополнительные издержки КТК → БТД при 1.5–2 млн т/год через БТД (PRD §2.3)
BTD_EXTRA_COST = 40  # млн USD/год (середина диапазона 30–50)


# ---------------------------------------------------------------------------
# Датакласс результата
# ---------------------------------------------------------------------------

@dataclass
class ScenarioResult:
    name: str
    brent: float
    revenue: float       # млн USD
    ebitda: float        # млн USD
    fcf: float           # млн USD
    net_debt: float      # млн USD
    revenue_delta_pct: float
    ebitda_delta_pct: float
    fcf_delta_pct: float
    budget_risk: bool    # Brent ниже порога дефицита бюджета РК
    rating_risk: bool    # Риск снижения рейтинга S&P BBB−


# ---------------------------------------------------------------------------
# Расчётное ядро
# ---------------------------------------------------------------------------

def calc_scenario(scenario_name: str, brent: float,
                  opec_cut_pct: float = 0.0,
                  ktk_days_down: int = 0) -> ScenarioResult:
    """
    Рассчитывает финансовые показатели КМГ при заданных условиях.

    Args:
        scenario_name:  название сценария
        brent:          цена Brent USD/барр. (среднегодовая)
        opec_cut_pct:   сокращение добычи из-за квот ОПЕК+ (доля, 0–1)
        ktk_days_down:  число дней простоя КТК (форс-мажор)
    """
    # Δbrent / $10 → знак определяет направление изменения
    brent_delta = brent - BASE_2025["brent_avg_2025"]   # < 0 при падении цены
    brent_10_steps = brent_delta / 10                   # шаги по $10

    # Выручка: линейная чувствительность (каждые $10 изменения = ±1.2 млрд)
    revenue = (BASE_2025["revenue_usd"]
               + brent_10_steps * SENSITIVITY_PER_10_BRENT["revenue_per_10"])

    # Сокращение добычи ОПЕК+: каждый 1% объёма ≈ 1% выручки
    revenue *= (1 - opec_cut_pct)

    # Простой КТК: −$17.5 млн/сут. (середина диапазона 15–20 млн)
    ktk_loss = ktk_days_down * 17.5
    revenue -= ktk_loss

    # EBITDA: чувствительность к Brent + рост OPEX
    ebitda = (BASE_2025["ebitda_usd"]
              + brent_10_steps * SENSITIVITY_PER_10_BRENT["ebitda_per_10"])
    ebitda -= OPEX_GROWTH_2026           # инфляционный рост OPEX
    ebitda -= BTD_EXTRA_COST             # дополнительные издержки маршрутизации
    ebitda *= (1 - opec_cut_pct)         # объёмный эффект ОПЕК+
    ebitda -= ktk_loss * 0.4             # часть потерь выручки КТК падает на EBITDA

    # FCF = EBITDA − CAPEX − проценты по долгу (~$350 млн/год)
    debt_service = 350  # млн USD/год (оценка по gross_debt $6.97 млрд × ~5%)
    capex = BASE_2025["capex_usd"]
    # В стрессе — секвестр CAPEX до минимума $750 млн
    if brent < BUDGET_BREAK_EVEN_BRENT:
        capex = 750
    fcf = ebitda - capex - debt_service

    # Чистый долг растёт при отрицательном FCF
    net_debt = BASE_2025["net_debt_usd"] - min(fcf, 0)

    # Дельты к 2025
    revenue_delta_pct = (revenue - BASE_2025["revenue_usd"]) / BASE_2025["revenue_usd"] * 100
    ebitda_delta_pct  = (ebitda  - BASE_2025["ebitda_usd"])  / BASE_2025["ebitda_usd"]  * 100
    fcf_delta_pct     = (fcf     - BASE_2025["fcf_usd"])     / BASE_2025["fcf_usd"]     * 100

    # Флаги рисков
    budget_risk = brent < BUDGET_BREAK_EVEN_BRENT
    # Рейтинг под угрозой при net_debt/EBITDA > 1.5 или FCF < 500 млн
    rating_risk = (net_debt / max(ebitda, 1) > 1.5) or (fcf < 500)

    return ScenarioResult(
        name=scenario_name,
        brent=brent,
        revenue=round(revenue),
        ebitda=round(ebitda),
        fcf=round(fcf),
        net_debt=round(net_debt),
        revenue_delta_pct=round(revenue_delta_pct, 1),
        ebitda_delta_pct=round(ebitda_delta_pct, 1),
        fcf_delta_pct=round(fcf_delta_pct, 1),
        budget_risk=budget_risk,
        rating_risk=rating_risk,
    )


def run_all_scenarios(brent_current: float | None = None,
                      opec_cut_pct: float = 0.05,
                      ktk_days_down: int = 0) -> dict[str, ScenarioResult]:
    """
    Запускает все три сценария.
    brent_current — реальная текущая цена (подставляется в базовый сценарий).
    """
    if brent_current is None:
        brent_current = get_latest("Brent_USD") or 85.0

    results = {}
    for name, cfg in SCENARIOS.items():
        # В базовом сценарии используем реальную цену если она попадает в диапазон
        if name == "base" and cfg["brent_lo"] <= brent_current <= cfg["brent_hi"]:
            brent = brent_current
        else:
            brent = (cfg["brent_lo"] + cfg["brent_hi"]) / 2  # середина диапазона

        cut = opec_cut_pct if name != "optimistic" else 0.0
        results[name] = calc_scenario(name, brent, cut, ktk_days_down)

    return results


# ---------------------------------------------------------------------------
# Проверка алерт-триггеров (из PRD §5)
# ---------------------------------------------------------------------------

@dataclass
class Alert:
    level: str    # КРИТИЧЕСКИЙ / ВЫСОКИЙ / ПЛАНОВЫЙ
    metric: str
    value: float
    message: str


def check_triggers(brent: float | None = None,
                   kzt_usd: float | None = None) -> list[Alert]:
    """Проверяет текущие значения и возвращает список алертов."""
    alerts = []

    brent = brent or get_latest("Brent_USD") or 0
    kzt_usd = kzt_usd or get_latest("KZT_USD") or 0

    # Brent триггеры
    if brent and brent < 75:
        alerts.append(Alert("КРИТИЧЕСКИЙ", "Brent", brent,
                            f"Brent ${brent:.1f} — НИЖЕ ПОРОГА $75. "
                            f"Активировать стресс-сценарий, секвестр CAPEX до $750 млн."))
    elif brent and brent < 82:
        alerts.append(Alert("ВЫСОКИЙ", "Brent", brent,
                            f"Brent ${brent:.1f} — в зоне риска $75–82. "
                            f"Проверить статус хеджирования."))
    elif brent and brent > 92:
        alerts.append(Alert("ПЛАНОВЫЙ", "Brent", brent,
                            f"Brent ${brent:.1f} — оптимистичный сценарий. "
                            f"Рассмотреть пересмотр CAPEX вверх."))

    # KZT/USD триггеры
    if kzt_usd and kzt_usd < 470:
        alerts.append(Alert("ВЫСОКИЙ", "KZT_USD", kzt_usd,
                            f"KZT/USD {kzt_usd:.0f} — тенге укрепился сверх нормы. "
                            f"Пересчитать тенговую выручку в МСФО."))
    elif kzt_usd and kzt_usd > 510:
        alerts.append(Alert("ВЫСОКИЙ", "KZT_USD", kzt_usd,
                            f"KZT/USD {kzt_usd:.0f} — тенге ослаб. "
                            f"Рост тенговой стоимости долгового обслуживания."))

    if not alerts:
        alerts.append(Alert("ПЛАНОВЫЙ", "overall", brent,
                            f"Brent ${brent:.1f}, KZT/USD {kzt_usd:.0f} — "
                            f"параметры в норме. Базовый сценарий."))
    return alerts


# ---------------------------------------------------------------------------
# Текстовый вывод для отладки
# ---------------------------------------------------------------------------

def print_scenarios(results: dict[str, ScenarioResult]):
    labels = {"optimistic": "Оптимистичный", "base": "Базовый", "stress": "Пессимистичный"}
    print("\n{'─'*72}")
    print(f"  {'Показатель':<28} {'Оптим.':>12} {'Базовый':>12} {'Стресс':>12}")
    print(f"  {'─'*66}")
    r = results
    rows = [
        ("Brent USD/барр.",         "brent",             ".1f"),
        ("Выручка, млн USD",        "revenue",           ",.0f"),
        ("EBITDA, млн USD",         "ebitda",            ",.0f"),
        ("FCF, млн USD",            "fcf",               ",.0f"),
        ("Чистый долг, млн USD",    "net_debt",          ",.0f"),
        ("Δ Выручка к 2025, %",     "revenue_delta_pct", "+.1f"),
        ("Δ EBITDA к 2025, %",      "ebitda_delta_pct",  "+.1f"),
        ("Δ FCF к 2025, %",         "fcf_delta_pct",     "+.1f"),
    ]
    for label, field, fmt in rows:
        vals = [format(getattr(r[s], field), fmt) for s in ("optimistic", "base", "stress")]
        print(f"  {label:<28} {vals[0]:>12} {vals[1]:>12} {vals[2]:>12}")
    print()
    for name, res in r.items():
        flags = []
        if res.budget_risk:  flags.append("⚠ Дефицит бюджета РК")
        if res.rating_risk:  flags.append("⚠ Риск рейтинга BBB−")
        if flags:
            print(f"  [{labels[name]}] {' | '.join(flags)}")


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
    brent_now = get_latest("Brent_USD")
    kzt_now   = get_latest("KZT_USD")
    print(f"\nТекущие данные: Brent={brent_now}, KZT/USD={kzt_now}")

    results = run_all_scenarios(brent_now)
    print_scenarios(results)

    alerts = check_triggers(brent_now, kzt_now)
    print("=== Алерты ===")
    for a in alerts:
        print(f"  [{a.level}] {a.metric}: {a.message}")
