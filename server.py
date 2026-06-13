# -*- coding: utf-8 -*-
"""
server.py — Flask веб-дашборд КМГ.
Запуск: python server.py  → http://localhost:5000
"""

import sys, json, sqlite3
from datetime import datetime
from pathlib import Path
from flask import Flask, jsonify, render_template_string

if sys.stdout.encoding and sys.stdout.encoding.lower() != "utf-8":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

sys.path.insert(0, str(Path(__file__).parent))
from collector import get_latest, get_history, get_recent_news, collect_all, DB_PATH
from analyzer import run_all_scenarios, check_triggers

app = Flask(__name__)

# ---------------------------------------------------------------------------
# API
# ---------------------------------------------------------------------------

@app.route("/api/data")
def api_data():
    """Все данные для дашборда одним запросом."""
    brent   = get_latest("Brent_USD") or 0
    kzt_usd = get_latest("KZT_USD")   or 0

    scenarios = run_all_scenarios(brent)
    alerts    = check_triggers(brent, kzt_usd)
    news      = get_recent_news(limit=10)
    history   = get_history("Brent_USD", days=30)

    return jsonify({
        "timestamp": datetime.now().strftime("%d.%m.%Y %H:%M"),
        "brent":     brent,
        "kzt_usd":   kzt_usd,
        "scenarios": {
            name: {
                "brent":             s.brent,
                "revenue":           s.revenue,
                "ebitda":            s.ebitda,
                "fcf":               s.fcf,
                "net_debt":          s.net_debt,
                "revenue_delta_pct": s.revenue_delta_pct,
                "ebitda_delta_pct":  s.ebitda_delta_pct,
                "fcf_delta_pct":     s.fcf_delta_pct,
                "budget_risk":       s.budget_risk,
                "rating_risk":       s.rating_risk,
            }
            for name, s in scenarios.items()
        },
        "alerts": [
            {"level": a.level, "metric": a.metric, "message": a.message}
            for a in alerts
        ],
        "news": news,
        "history": [{"date": d, "value": v} for d, v in history],
    })


@app.route("/api/refresh")
def api_refresh():
    """Принудительный сбор свежих данных."""
    result = collect_all()
    return jsonify({"ok": True, "brent": result["brent"], "kzt_usd": result["kzt_usd"]})


# ---------------------------------------------------------------------------
# Главная страница
# ---------------------------------------------------------------------------

HTML = r"""<!DOCTYPE html>
<html lang="ru">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>КМГ Strategic Dashboard</title>
<script src="https://cdn.jsdelivr.net/npm/chart.js@4.4.0/dist/chart.umd.min.js"></script>
<style>
  :root {
    --bg:      #0d1117;
    --card:    #161b22;
    --border:  #30363d;
    --text:    #e6edf3;
    --muted:   #8b949e;
    --green:   #3fb950;
    --red:     #f85149;
    --yellow:  #d29922;
    --blue:    #58a6ff;
    --accent:  #1f6feb;
  }
  * { box-sizing: border-box; margin: 0; padding: 0; }
  body { background: var(--bg); color: var(--text); font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif; font-size: 14px; }

  header { background: var(--card); border-bottom: 1px solid var(--border); padding: 14px 24px; display: flex; align-items: center; justify-content: space-between; position: sticky; top: 0; z-index: 100; }
  header h1 { font-size: 16px; font-weight: 700; color: var(--text); }
  #timestamp { font-size: 12px; color: var(--muted); }
  #refresh-btn { background: var(--accent); color: #fff; border: none; border-radius: 6px; padding: 6px 14px; cursor: pointer; font-size: 13px; }
  #refresh-btn:hover { opacity: .85; }
  #status-dot { width: 8px; height: 8px; border-radius: 50%; background: var(--green); display: inline-block; margin-right: 6px; animation: pulse 2s infinite; }
  @keyframes pulse { 0%,100%{opacity:1} 50%{opacity:.4} }

  main { max-width: 1400px; margin: 0 auto; padding: 20px 16px; display: grid; gap: 16px; }

  /* Метрики вверху */
  .metrics { display: grid; grid-template-columns: repeat(auto-fit, minmax(180px, 1fr)); gap: 12px; }
  .metric-card { background: var(--card); border: 1px solid var(--border); border-radius: 10px; padding: 16px; }
  .metric-card .label { font-size: 11px; color: var(--muted); text-transform: uppercase; letter-spacing: .5px; margin-bottom: 8px; }
  .metric-card .value { font-size: 28px; font-weight: 700; line-height: 1; }
  .metric-card .sub   { font-size: 12px; color: var(--muted); margin-top: 6px; }
  .metric-card.brent  .value { color: var(--blue); }
  .metric-card.kzt    .value { color: var(--green); }
  .metric-card.alert-ok   .value { color: var(--green); }
  .metric-card.alert-warn .value { color: var(--yellow); }
  .metric-card.alert-crit .value { color: var(--red); }

  /* Двухколоночный layout */
  .two-col { display: grid; grid-template-columns: 1fr 1fr; gap: 16px; }
  @media(max-width: 900px) { .two-col { grid-template-columns: 1fr; } }

  .card { background: var(--card); border: 1px solid var(--border); border-radius: 10px; padding: 20px; }
  .card h2 { font-size: 13px; font-weight: 600; color: var(--muted); text-transform: uppercase; letter-spacing: .5px; margin-bottom: 16px; }

  /* Таблица сценариев */
  .scenarios { display: grid; grid-template-columns: 1fr 1fr 1fr; gap: 10px; }
  .scenario { border-radius: 8px; padding: 14px; border: 1px solid var(--border); }
  .scenario.opt  { border-color: #2ea04326; background: #2ea04310; }
  .scenario.base { border-color: #58a6ff26; background: #58a6ff10; }
  .scenario.str  { border-color: #f8514926; background: #f8514910; }
  .scenario .s-label { font-size: 11px; font-weight: 700; text-transform: uppercase; letter-spacing: .5px; margin-bottom: 10px; }
  .scenario.opt  .s-label { color: var(--green); }
  .scenario.base .s-label { color: var(--blue); }
  .scenario.str  .s-label { color: var(--red); }
  .scenario .s-brent { font-size: 22px; font-weight: 700; margin-bottom: 8px; }
  .scenario .s-row { display: flex; justify-content: space-between; font-size: 12px; padding: 3px 0; border-bottom: 1px solid var(--border); }
  .scenario .s-row:last-child { border: none; }
  .scenario .s-key { color: var(--muted); }
  .scenario .s-val { font-weight: 600; }
  .scenario .delta.pos { color: var(--green); }
  .scenario .delta.neg { color: var(--red); }
  .scenario .risk-badge { margin-top: 8px; font-size: 11px; padding: 3px 7px; border-radius: 4px; background: #f8514920; color: var(--red); display: inline-block; }

  /* Алерты */
  .alert-item { display: flex; align-items: flex-start; gap: 10px; padding: 10px 0; border-bottom: 1px solid var(--border); }
  .alert-item:last-child { border: none; }
  .alert-badge { font-size: 10px; font-weight: 700; padding: 2px 7px; border-radius: 4px; white-space: nowrap; flex-shrink: 0; margin-top: 1px; }
  .badge-КРИТИЧЕСКИЙ { background: #f8514930; color: var(--red); }
  .badge-ВЫСОКИЙ     { background: #d2992230; color: var(--yellow); }
  .badge-ПЛАНОВЫЙ    { background: #3fb95030; color: var(--green); }
  .alert-msg { font-size: 13px; line-height: 1.4; }

  /* Новости */
  .news-item { padding: 10px 0; border-bottom: 1px solid var(--border); }
  .news-item:last-child { border: none; }
  .news-source { font-size: 11px; color: var(--accent); font-weight: 600; margin-bottom: 3px; }
  .news-title  { font-size: 13px; line-height: 1.4; }

  /* График */
  .chart-wrap { height: 200px; position: relative; }

  /* Обновление */
  #auto-label { font-size: 11px; color: var(--muted); }
  .spinner { display: none; width: 14px; height: 14px; border: 2px solid var(--border); border-top-color: var(--blue); border-radius: 50%; animation: spin .7s linear infinite; vertical-align: middle; }
  @keyframes spin { to { transform: rotate(360deg); } }
</style>
</head>
<body>

<header>
  <div style="display:flex;align-items:center;gap:10px">
    <span id="status-dot"></span>
    <h1>КМГ Strategic Dashboard</h1>
  </div>
  <div style="display:flex;align-items:center;gap:16px">
    <span id="auto-label">обновление через <b id="countdown">30</b>с</span>
    <span class="spinner" id="spinner"></span>
    <span id="timestamp" style="color:var(--muted);font-size:12px"></span>
    <button id="refresh-btn" onclick="loadData(true)">↻ Обновить</button>
  </div>
</header>

<main>

  <!-- Метрики -->
  <div class="metrics">
    <div class="metric-card brent">
      <div class="label">Brent Crude</div>
      <div class="value" id="m-brent">—</div>
      <div class="sub">USD / барр.</div>
    </div>
    <div class="metric-card kzt">
      <div class="label">KZT / USD</div>
      <div class="value" id="m-kzt">—</div>
      <div class="sub">Нацбанк РК</div>
    </div>
    <div class="metric-card" id="m-alert-card">
      <div class="label">Статус рисков</div>
      <div class="value" id="m-alert-val">—</div>
      <div class="sub" id="m-alert-sub"></div>
    </div>
    <div class="metric-card" style="background:var(--card)">
      <div class="label">База 2025 (факт)</div>
      <div class="value" style="font-size:18px;color:var(--muted)">$17.98B</div>
      <div class="sub">Выручка · EBITDA $4.59B</div>
    </div>
  </div>

  <!-- График + Алерты -->
  <div class="two-col">
    <div class="card">
      <h2>📈 Brent — история 30 дней</h2>
      <div class="chart-wrap"><canvas id="brentChart"></canvas></div>
    </div>
    <div class="card">
      <h2>🚨 Активные алерты</h2>
      <div id="alerts-list"></div>
    </div>
  </div>

  <!-- Сценарии -->
  <div class="card">
    <h2>📊 Сценарии 2026</h2>
    <div class="scenarios" id="scenarios"></div>
  </div>

  <!-- Новости -->
  <div class="card">
    <h2>📰 Последние новости</h2>
    <div id="news-list"></div>
  </div>

</main>

<script>
let chart = null;
let countdown = 30;
let timer;

// ---------------------------------------------------------------------------
// Загрузка данных
// ---------------------------------------------------------------------------
async function loadData(forceRefresh = false) {
  document.getElementById('spinner').style.display = 'inline-block';
  try {
    if (forceRefresh) await fetch('/api/refresh');
    const r = await fetch('/api/data');
    const d = await r.json();
    render(d);
  } catch(e) {
    console.error(e);
  }
  document.getElementById('spinner').style.display = 'none';
  resetCountdown();
}

// ---------------------------------------------------------------------------
// Рендер
// ---------------------------------------------------------------------------
function render(d) {
  // Шапка
  document.getElementById('timestamp').textContent = d.timestamp;

  // Метрики
  document.getElementById('m-brent').textContent = '$' + d.brent.toFixed(2);
  document.getElementById('m-kzt').textContent = Math.round(d.kzt_usd);

  // Статус алерта
  const levels = d.alerts.map(a => a.level);
  const alertCard = document.getElementById('m-alert-card');
  const alertVal  = document.getElementById('m-alert-val');
  const alertSub  = document.getElementById('m-alert-sub');
  alertCard.className = 'metric-card';
  if (levels.includes('КРИТИЧЕСКИЙ')) {
    alertCard.classList.add('alert-crit');
    alertVal.textContent = '🚨 КРИТИЧЕСКИЙ';
    alertSub.textContent = 'Требует немедленных действий';
  } else if (levels.includes('ВЫСОКИЙ')) {
    alertCard.classList.add('alert-warn');
    alertVal.textContent = '⚠️ ВЫСОКИЙ';
    alertSub.textContent = 'Контроль повышен';
  } else {
    alertCard.classList.add('alert-ok');
    alertVal.textContent = '✅ НОРМА';
    alertSub.textContent = 'Базовый сценарий';
  }

  // График Brent
  renderChart(d.history);

  // Сценарии
  const sc = d.scenarios;
  document.getElementById('scenarios').innerHTML = [
    scenarioHTML('opt',  '🟢 Оптимистичный · 20%', sc.optimistic),
    scenarioHTML('base', '🔵 Базовый · 55%',        sc.base),
    scenarioHTML('str',  '🔴 Стрессовый · 25%',     sc.stress),
  ].join('');

  // Алерты
  document.getElementById('alerts-list').innerHTML = d.alerts.map(a => `
    <div class="alert-item">
      <span class="alert-badge badge-${a.level}">${a.level}</span>
      <span class="alert-msg">${a.message}</span>
    </div>`).join('') || '<div style="color:var(--muted);padding:8px 0">Нет активных алертов</div>';

  // Новости
  document.getElementById('news-list').innerHTML = d.news.length
    ? d.news.map(n => `
        <div class="news-item">
          <div class="news-source">${n.source}</div>
          <div class="news-title">${n.title}</div>
        </div>`).join('')
    : '<div style="color:var(--muted);padding:8px 0">Новостей пока нет — нажмите «Обновить»</div>';
}

function scenarioHTML(cls, label, s) {
  const dRev = s.revenue_delta_pct;
  const dEbi = s.ebitda_delta_pct;
  const dFcf = s.fcf_delta_pct;
  const sign = v => v >= 0 ? '+' : '';
  const cls2 = v => v >= 0 ? 'pos' : 'neg';
  let risks = '';
  if (s.budget_risk) risks += '<span class="risk-badge">⚠ Дефицит бюджета РК</span> ';
  if (s.rating_risk) risks += '<span class="risk-badge">⚠ Риск рейтинга BBB−</span>';
  return `
    <div class="scenario ${cls}">
      <div class="s-label">${label}</div>
      <div class="s-brent">$${s.brent.toFixed(0)}<span style="font-size:13px;font-weight:400;color:var(--muted)">/барр.</span></div>
      <div class="s-row"><span class="s-key">Выручка</span><span class="s-val">$${s.revenue.toLocaleString()} млн</span></div>
      <div class="s-row"><span class="s-key">EBITDA</span><span class="s-val">$${s.ebitda.toLocaleString()} млн</span></div>
      <div class="s-row"><span class="s-key">FCF</span><span class="s-val">$${s.fcf.toLocaleString()} млн</span></div>
      <div class="s-row"><span class="s-key">Δ Выручка</span><span class="s-val delta ${cls2(dRev)}">${sign(dRev)}${dRev.toFixed(1)}%</span></div>
      <div class="s-row"><span class="s-key">Δ EBITDA</span><span class="s-val delta ${cls2(dEbi)}">${sign(dEbi)}${dEbi.toFixed(1)}%</span></div>
      <div class="s-row"><span class="s-key">Δ FCF</span><span class="s-val delta ${cls2(dFcf)}">${sign(dFcf)}${dFcf.toFixed(1)}%</span></div>
      ${risks}
    </div>`;
}

// ---------------------------------------------------------------------------
// График
// ---------------------------------------------------------------------------
function renderChart(history) {
  const labels = history.map(h => h.date.slice(5));   // MM-DD
  const values = history.map(h => h.value);
  if (chart) {
    chart.data.labels = labels;
    chart.data.datasets[0].data = values;
    chart.update('none');
    return;
  }
  const ctx = document.getElementById('brentChart').getContext('2d');
  chart = new Chart(ctx, {
    type: 'line',
    data: {
      labels,
      datasets: [{
        label: 'Brent USD/барр.',
        data: values,
        borderColor: '#58a6ff',
        backgroundColor: 'rgba(88,166,255,0.08)',
        borderWidth: 2,
        pointRadius: 3,
        pointBackgroundColor: '#58a6ff',
        tension: 0.3,
        fill: true,
      }]
    },
    options: {
      responsive: true,
      maintainAspectRatio: false,
      plugins: { legend: { display: false } },
      scales: {
        x: { grid: { color: '#30363d' }, ticks: { color: '#8b949e', maxTicksLimit: 8 } },
        y: {
          grid: { color: '#30363d' },
          ticks: { color: '#8b949e', callback: v => '$' + v },
          suggestedMin: 60, suggestedMax: 120,
        }
      }
    }
  });
}

// ---------------------------------------------------------------------------
// Обратный отсчёт
// ---------------------------------------------------------------------------
function resetCountdown() {
  clearInterval(timer);
  countdown = 30;
  document.getElementById('countdown').textContent = countdown;
  timer = setInterval(() => {
    countdown--;
    document.getElementById('countdown').textContent = countdown;
    if (countdown <= 0) loadData();
  }, 1000);
}

// Старт
loadData();
</script>
</body>
</html>"""

@app.route("/")
def index():
    return render_template_string(HTML)


if __name__ == "__main__":
    import webbrowser, threading
    def open_browser():
        import time; time.sleep(1)
        webbrowser.open("http://localhost:5000")
    threading.Thread(target=open_browser, daemon=True).start()
    print("КМГ Dashboard: http://localhost:5000")
    app.run(host="0.0.0.0", port=5000, debug=False)
