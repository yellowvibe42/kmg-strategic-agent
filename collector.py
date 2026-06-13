# -*- coding: utf-8 -*-
"""
collector.py — сбор рыночных данных из бесплатных источников
Источники: nationalbank.kz (KZT/USD), oilprice.com (Brent), investing.com (KMGZ)
"""

import sys
import sqlite3
import requests
import feedparser
import re
import logging
from datetime import date, datetime
from pathlib import Path
from bs4 import BeautifulSoup

# Фикс кодировки для Windows-консоли
if sys.stdout.encoding and sys.stdout.encoding.lower() != "utf-8":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
if sys.stderr.encoding and sys.stderr.encoding.lower() != "utf-8":
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
    handlers=[logging.StreamHandler(sys.stdout)],
)
log = logging.getLogger(__name__)

DB_PATH = Path(__file__).parent / "data" / "data.db"

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    )
}

# ---------------------------------------------------------------------------
# База данных
# ---------------------------------------------------------------------------

def init_db() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS prices (
            id        INTEGER PRIMARY KEY AUTOINCREMENT,
            date      TEXT NOT NULL,
            source    TEXT NOT NULL,
            metric    TEXT NOT NULL,
            value     REAL NOT NULL,
            currency  TEXT NOT NULL,
            fetched_at TEXT NOT NULL,
            UNIQUE(date, source, metric)
        )
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS news (
            id         INTEGER PRIMARY KEY AUTOINCREMENT,
            fetched_at TEXT NOT NULL,
            source     TEXT NOT NULL,
            title      TEXT NOT NULL,
            link       TEXT,
            published  TEXT,
            UNIQUE(source, title)
        )
    """)
    conn.commit()
    return conn


def upsert_price(conn: sqlite3.Connection, source: str, metric: str,
                 value: float, currency: str, price_date: str | None = None):
    today = price_date or date.today().isoformat()
    now = datetime.now().isoformat(timespec="seconds")
    conn.execute(
        """
        INSERT INTO prices (date, source, metric, value, currency, fetched_at)
        VALUES (?, ?, ?, ?, ?, ?)
        ON CONFLICT(date, source, metric) DO UPDATE SET
            value=excluded.value,
            fetched_at=excluded.fetched_at
        """,
        (today, source, metric, value, currency, now),
    )
    conn.commit()


def insert_news(conn: sqlite3.Connection, source: str, title: str,
                link: str | None, published: str | None):
    now = datetime.now().isoformat(timespec="seconds")
    try:
        conn.execute(
            """
            INSERT OR IGNORE INTO news (fetched_at, source, title, link, published)
            VALUES (?, ?, ?, ?, ?)
            """,
            (now, source, title, link, published),
        )
        conn.commit()
    except Exception as exc:
        log.warning("news insert error: %s", exc)


# ---------------------------------------------------------------------------
# 1. KZT/USD — Национальный Банк Казахстана (бесплатный XML API)
# ---------------------------------------------------------------------------

def fetch_kzt_usd(conn: sqlite3.Connection) -> float | None:
    """nationalbank.kz предоставляет бесплатный XML API курсов."""
    today = date.today().strftime("%d.%m.%Y")
    url = f"https://nationalbank.kz/rss/rates_all.xml"
    try:
        r = requests.get(url, headers=HEADERS, timeout=15)
        r.raise_for_status()
        soup = BeautifulSoup(r.content, "xml")
        for item in soup.find_all("item"):
            title = item.find("title")
            if title and "USD" in title.text:
                desc = item.find("description")
                if desc:
                    value = float(desc.text.strip())
                    upsert_price(conn, "nationalbank.kz", "KZT_USD", value, "KZT")
                    log.info("KZT/USD = %.2f", value)
                    return value
    except Exception as exc:
        log.error("KZT/USD fetch failed: %s", exc)
    return None


# ---------------------------------------------------------------------------
# 2. Brent — oilprice.com (парсинг)
# ---------------------------------------------------------------------------

def fetch_brent(conn: sqlite3.Connection) -> float | None:
    """Парсинг текущей цены Brent с oilprice.com.
    Страница содержит таблицу: строка 'Brent Crude' → td.last_price.
    """
    url = "https://oilprice.com/oil-price-charts/"
    try:
        r = requests.get(url, headers=HEADERS, timeout=20)
        r.raise_for_status()
        soup = BeautifulSoup(r.text, "html.parser")

        # Ищем строку таблицы с "Brent Crude" (не Brent Weighted Average)
        for row in soup.find_all("tr"):
            row_text = row.get_text(" ", strip=True)
            if "Brent Crude" in row_text and "Weighted" not in row_text:
                td = row.find("td", class_="last_price")
                if td:
                    value = float(td.get_text(strip=True))
                    upsert_price(conn, "oilprice.com", "Brent_USD", value, "USD")
                    log.info("Brent = %.2f USD/барр.", value)
                    return value

        log.warning("Brent: строка не найдена, пробуем RSS")
        return _fetch_brent_fallback(conn)

    except Exception as exc:
        log.error("Brent fetch failed: %s", exc)
        return _fetch_brent_fallback(conn)


def _fetch_brent_fallback(conn: sqlite3.Connection) -> float | None:
    """Резерв: парсинг RSS oilprice.com."""
    url = "https://oilprice.com/rss/main"
    try:
        feed = feedparser.parse(url)
        for entry in feed.entries[:5]:
            match = re.search(r"[Bb]rent.*?\$(\d{2,3}[.,]\d{1,2})", entry.title)
            if match:
                value = float(match.group(1).replace(",", "."))
                upsert_price(conn, "oilprice.com", "Brent_USD", value, "USD")
                log.info("Brent (RSS) = %.2f USD/барр.", value)
                return value
    except Exception as exc:
        log.error("Brent fallback failed: %s", exc)
    return None


# ---------------------------------------------------------------------------
# 3. KMGZ — KASE (парсинг)
# ---------------------------------------------------------------------------

def fetch_kmgz(conn: sqlite3.Connection) -> float | None:
    """Котировки KMGZ (еврооблигации КМГ) с market.aixkz.com или investing.com.
    KMGZ торгуются на LSE/AIX, не на KASE — парсим AIX JSON API.
    """
    # Попытка 1: AIX JSON endpoint
    try:
        url = "https://market.aixkz.com/api/securities?search=KMG&type=bond"
        r = requests.get(url, headers=HEADERS, timeout=15)
        if r.status_code == 200:
            data = r.json()
            items = data if isinstance(data, list) else data.get("data", data.get("results", []))
            for item in items:
                ticker = str(item.get("ticker", item.get("symbol", ""))).upper()
                if "KMG" in ticker:
                    price = item.get("lastPrice", item.get("last_price", item.get("price")))
                    if price:
                        value = float(price)
                        upsert_price(conn, "aix.kz", "KMGZ", value, "USD")
                        log.info("KMGZ (AIX) = %.4f", value)
                        return value
    except Exception as exc:
        log.debug("KMGZ AIX attempt failed: %s", exc)

    # Попытка 2: AIX страница официального листинга
    try:
        r = requests.get("https://market.aixkz.com/official-list",
                         headers=HEADERS, timeout=15)
        soup = BeautifulSoup(r.text, "html.parser")
        for row in soup.find_all("tr"):
            row_text = row.get_text(" ", strip=True)
            if "KMG" in row_text.upper():
                numbers = re.findall(r"\d{2,3}\.\d{2,4}", row_text)
                for n in numbers:
                    v = float(n)
                    if 50 < v < 150:
                        upsert_price(conn, "aix.kz", "KMGZ", v, "USD")
                        log.info("KMGZ (AIX list) = %.4f", v)
                        return v
    except Exception as exc:
        log.debug("KMGZ AIX list failed: %s", exc)

    log.warning("KMGZ: данные недоступны (еврооблигации LSE/AIX, JS-рендеринг).")
    return None


# ---------------------------------------------------------------------------
# 4. Новости — RSS-ленты (бесплатно)
# ---------------------------------------------------------------------------

RSS_FEEDS = {
    "kmg.kz":       "https://kmg.kz/press-center/news/rss/",
    "oilprice.com": "https://oilprice.com/rss/main",
    "opec.org":      "https://www.opec.org/opec_web/en/press_room/rss.htm",
    "timesca.com":   "https://timesca.com/feed/",
}

KMG_KEYWORDS = [
    "КМГ", "KMG", "КазМунайГаз", "KazMunayGas",
    "KTK", "КТК", "ОПЕК", "OPEC", "Brent", "Тенгиз", "Tengiz",
    "Кашаган", "Kashagan", "санкции", "sanctions",
]


def fetch_news(conn: sqlite3.Connection) -> list[dict]:
    """Сбор новостей из RSS-лент, фильтрация по ключевым словам."""
    collected = []
    for source, url in RSS_FEEDS.items():
        try:
            feed = feedparser.parse(url)
            for entry in feed.entries[:20]:
                title = entry.get("title", "")
                link = entry.get("link", "")
                published = entry.get("published", "")
                # Фильтр по ключевым словам
                if any(kw.lower() in title.lower() for kw in KMG_KEYWORDS):
                    insert_news(conn, source, title, link, published)
                    collected.append({"source": source, "title": title, "link": link})
                    log.info("Новость [%s]: %s", source, title[:80])
        except Exception as exc:
            log.error("RSS %s failed: %s", source, exc)
    return collected


# ---------------------------------------------------------------------------
# 5. OFAC санкционные обновления — RSS
# ---------------------------------------------------------------------------

def fetch_ofac_updates(conn: sqlite3.Connection) -> list[dict]:
    """Мониторинг обновлений санкционного списка OFAC."""
    url = "https://ofac.treas.gov/recent-actions/rss"
    collected = []
    try:
        feed = feedparser.parse(url)
        for entry in feed.entries[:10]:
            title = entry.get("title", "")
            link = entry.get("link", "")
            published = entry.get("published", "")
            insert_news(conn, "ofac.treas.gov", title, link, published)
            collected.append({"source": "ofac.treas.gov", "title": title})
            log.info("OFAC: %s", title[:80])
    except Exception as exc:
        log.error("OFAC RSS failed: %s", exc)
    return collected


# ---------------------------------------------------------------------------
# Главная функция сбора
# ---------------------------------------------------------------------------

def collect_all() -> dict:
    """Запускает все источники и возвращает сводку."""
    conn = init_db()
    log.info("=== Начало сбора данных ===")

    results = {
        "kzt_usd":     fetch_kzt_usd(conn),
        "brent":       fetch_brent(conn),
        "kmgz":        fetch_kmgz(conn),
        "news_count":  len(fetch_news(conn)),
        "ofac_count":  len(fetch_ofac_updates(conn)),
        "timestamp":   datetime.now().isoformat(timespec="seconds"),
    }

    conn.close()
    log.info("=== Сбор завершён: %s ===", results)
    return results


def get_latest(metric: str) -> float | None:
    """Возвращает последнее значение метрики из БД."""
    conn = sqlite3.connect(DB_PATH)
    row = conn.execute(
        "SELECT value FROM prices WHERE metric=? ORDER BY date DESC, fetched_at DESC LIMIT 1",
        (metric,),
    ).fetchone()
    conn.close()
    return row[0] if row else None


def get_history(metric: str, days: int = 30) -> list[tuple]:
    """Возвращает историю значений метрики за N дней."""
    conn = sqlite3.connect(DB_PATH)
    rows = conn.execute(
        """
        SELECT date, value FROM prices
        WHERE metric=?
        ORDER BY date DESC
        LIMIT ?
        """,
        (metric, days),
    ).fetchall()
    conn.close()
    return list(reversed(rows))


def get_recent_news(limit: int = 20) -> list[dict]:
    """Последние новости из БД."""
    conn = sqlite3.connect(DB_PATH)
    rows = conn.execute(
        "SELECT source, title, link, published, fetched_at FROM news ORDER BY fetched_at DESC LIMIT ?",
        (limit,),
    ).fetchall()
    conn.close()
    return [
        {"source": r[0], "title": r[1], "link": r[2], "published": r[3], "fetched_at": r[4]}
        for r in rows
    ]


if __name__ == "__main__":
    results = collect_all()
    print("\n--- Результаты сбора ---")
    print(f"  KZT/USD : {results['kzt_usd']}")
    print(f"  Brent   : {results['brent']} USD/барр.")
    print(f"  KMGZ    : {results['kmgz']}")
    print(f"  Новостей: {results['news_count']}")
    print(f"  OFAC    : {results['ofac_count']}")
    print(f"  Время   : {results['timestamp']}")
