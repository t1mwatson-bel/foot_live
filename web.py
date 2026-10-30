import json
from datetime import datetime
from flask import Flask, render_template_string
import database as db

app = Flask(__name__)

HTML_TEMPLATE = r"""
<!doctype html>
<html lang="ru">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<meta http-equiv="refresh" content="60">
<title>OLD — Live Statistics</title>
<script src="https://cdn.jsdelivr.net/npm/chart.js"></script>
<style>
:root {
  color-scheme: dark;
  --bg: #090d18;
  --panel: #111827;
  --panel2: #151f31;
  --border: #25334a;
  --text: #eef3ff;
  --muted: #96a5bd;
  --green: #41e6a1;
  --red: #ff6b81;
  --blue: #6da8ff;
  --yellow: #ffd36b;
}
* { box-sizing: border-box; }
body {
  margin: 0;
  background: radial-gradient(ellipse at top, #17233b 0, var(--bg) 60%);
  color: var(--text);
  font-family: Inter, system-ui, -apple-system, sans-serif;
}
.wrap { width: min(1250px, 94%); margin: 0 auto; padding: 28px 0 50px; }
header {
  display: flex; justify-content: space-between; align-items: center;
  gap: 16px; flex-wrap: wrap; margin-bottom: 24px;
}
.logo { font-size: 27px; font-weight: 900; letter-spacing: 2px; }
.logo span { color: var(--blue); }
.sub { color: var(--muted); font-size: 13px; margin-top: 5px; }
.updated { color: var(--muted); font-size: 12px; }
.cards {
  display: grid; grid-template-columns: repeat(5, minmax(0, 1fr));
  gap: 12px; margin-bottom: 18px;
}
.card, .panel {
  background: linear-gradient(145deg, var(--panel2), var(--panel));
  border: 1px solid var(--border); border-radius: 16px;
  box-shadow: 0 10px 35px #0002;
}
.card { padding: 18px; min-width: 0; }
.card .label { color: var(--muted); font-size: 12px; margin-bottom: 10px; }
.card .value { font-size: clamp(20px, 2.5vw, 29px); font-weight: 800; overflow-wrap: anywhere; }
.green { color: var(--green); }
.red { color: var(--red); }
.blue { color: var(--blue); }
.yellow { color: var(--yellow); }
.panel { padding: 20px; margin-bottom: 18px; }
.panel h2 { margin: 0 0 16px; font-size: 17px; }
.chart-wrap { height: 260px; }
.table-wrap { overflow-x: auto; }
table { width: 100%; border-collapse: collapse; min-width: 760px; }
th, td {
  padding: 13px 12px; border-bottom: 1px solid var(--border);
  text-align: left; font-size: 13px; vertical-align: top;
}
th { color: var(--muted); font-size: 11px; text-transform: uppercase; letter-spacing: .6px; }
tr:last-child td { border-bottom: 0; }
.match { font-weight: 700; min-width: 190px; }
.small { color: var(--muted); font-size: 11px; margin-top: 5px; }
.pill {
  display: inline-block; padding: 5px 9px; border-radius: 20px;
  font-size: 11px; font-weight: 800; white-space: nowrap;
}
.pill-WIN { color: var(--green); background: #41e6a118; }
.pill-LOSE { color: var(--red); background: #ff6b8118; }
.pill-PENDING { color: var(--yellow); background: #ffd36b18; }
.empty { text-align: center; padding: 32px; color: var(--muted); }
footer { text-align: center; color: var(--muted); font-size: 12px; padding-top: 8px; }
@media (max-width: 850px) {
  .cards { grid-template-columns: repeat(2, minmax(0, 1fr)); }
  .card:last-child { grid-column: span 2; }
  .panel { padding: 14px; }
}
</style>
</head>
<body>
<div class="wrap">
  <header>
    <div>
      <div class="logo"><span>OLD</span> LIVE STATS</div>
      <div class="sub">Статистика прогнозов на следующий гол до конца матча</div>
    </div>
    <div class="updated">Обновлено: {{ updated }}</div>
  </header>

  <section class="cards">
    <div class="card">
      <div class="label">Всего прогнозов</div>
      <div class="value">{{ total }}</div>
    </div>
    <div class="card">
      <div class="label">Зашло</div>
      <div class="value green">{{ wins }}</div>
    </div>
    <div class="card">
      <div class="label">Не зашло</div>
      <div class="value red">{{ loses }}</div>
    </div>
    <div class="card">
      <div class="label">Ожидают результата</div>
      <div class="value yellow">{{ pending }}</div>
    </div>
    <div class="card">
      <div class="label">Проходимость</div>
      <div class="value blue">{{ accuracy }}%</div>
      <div class="small">Только завершённые прогнозы</div>
    </div>
  </section>

  <section class="cards">
    <div class="card" style="grid-column: span 2">
      <div class="label">Общая прибыль, условные единицы</div>
      <div class="value {{ 'green' if profit >= 0 else 'red' }}">
        {{ '%+.2f'|format(profit) }}
      </div>
    </div>
    <div class="card" style="grid-column: span 3">
      <div class="label">ROI по завершённым прогнозам</div>
      <div class="value {{ 'green' if roi >= 0 else 'red' }}">{{ '%+.2f'|format(roi) }}%</div>
      <div class="small">Расчёт по единичной ставке на каждый завершённый сигнал</div>
    </div>
  </section>

  <section class="panel">
    <h2>Накопленная прибыль</h2>
    <div class="chart-wrap"><canvas id="profitChart"></canvas></div>
  </section>

  <section class="panel">
    <h2>История лайв-прогнозов</h2>
    <div class="table-wrap">
      <table>
        <thead>
          <tr>
            <th>Время</th><th>Матч</th><th>Лига</th><th>Стратегия</th>
            <th>Счёт при сигнале</th><th>Коэффициент</th><th>Результат</th><th>Прибыль</th>
          </tr>
        </thead>
        <tbody>
        {% for s in signals %}
          <tr>
            <td>
              {{ s.sent_at_text }}
              <div class="small">{{ s.minute or 0 }}'</div>
            </td>
            <td class="match">
              {{ s.match_name or 'Матч не указан' }}
              {% if s.final_score %}
                <div class="small">Итог: {{ s.final_score }}</div>
              {% endif %}
            </td>
            <td>{{ s.league or '—' }}</td>
            <td>{{ s.strategy or '—' }}</td>
            <td>{{ s.score or '—' }}</td>
            <td>{{ '%.2f'|format(s.odds|float) if s.odds is not none else '—' }}</td>
            <td><span class="pill pill-{{ s.status }}">{{ status_labels.get(s.status, s.status) }}</span></td>
            <td class="{{ 'green' if s.profit|float > 0 else ('red' if s.profit|float < 0 else '') }}">
              {{ '%+.2f'|format(s.profit|float) }}
            </td>
          </tr>
        {% else %}
          <tr><td colspan="8" class="empty">Пока нет записанных лайв-прогнозов</td></tr>
        {% endfor %}
        </tbody>
      </table>
    </div>
  </section>
  <footer>OLD · Статистика рассчитывается по данным SQLite</footer>
</div>

<script>
const labels = {{ chart_labels|safe }};
const values = {{ chart_data|safe }};
const ctx = document.getElementById('profitChart');
new Chart(ctx, {
  type: 'line',
  data: {
    labels,
    datasets: [{
      label: 'Накопленная прибыль',
      data: values,
      borderColor: '#6da8ff',
      backgroundColor: 'rgba(109,168,255,0.12)',
      fill: true,
      tension: 0.25,
      pointRadius: 3
    }]
  },
  options: {
    responsive: true,
    maintainAspectRatio: false,
    plugins: { legend: { labels: { color: '#eef3ff' } } },
    scales: {
      x: { ticks: { color: '#96a5bd' }, grid: { color: '#25334a' } },
      y: { ticks: { color: '#96a5bd' }, grid: { color: '#25334a' } }
    }
  }
});
</script>
</body>
</html>
"""


@app.route("/")
def index():
    all_rows = db.get_live_signals()

    # Скрываем технические записи без названия матча.
    signals = [
        row for row in all_rows
        if row.get("game_id") and row.get("match_name")
    ]

    wins = sum(1 for row in signals if row.get("status") == "WIN")
    loses = sum(1 for row in signals if row.get("status") == "LOSE")
    pending = sum(1 for row in signals if row.get("status") == "PENDING")
    settled = wins + loses

    # === ИСПРАВЛЕНИЕ: Пересчитываем прибыль на лету по коэффициентам ===
    total_profit = 0.0
    for row in signals:
        if row.get("status") == "WIN":
            odds = float(row.get("odds") or 1.0)
            row["profit"] = max(0.0, odds - 1.0)
            total_profit += row["profit"]
        elif row.get("status") == "LOSE":
            row["profit"] = -1.0
            total_profit -= 1.0
        else:
            row["profit"] = 0.0

    profit = total_profit
    accuracy = round(wins / settled * 100, 2) if settled else 0.0
    roi = round(profit / settled * 100, 2) if settled else 0.0

    for row in signals:
        timestamp = row.get("sent_at")
        try:
            row["sent_at_text"] = datetime.fromtimestamp(
                int(timestamp)
            ).strftime("%d.%m.%Y %H:%M")
        except (TypeError, ValueError, OSError):
            row["sent_at_text"] = "—"

    # Строим график по времени, а не сортируем только по дню месяца.
    settled_rows = sorted(
        (
            row for row in signals
            if row.get("status") in ("WIN", "LOSE")
        ),
        key=lambda row: int(row.get("result_updated_at") or row.get("sent_at") or 0),
    )

    chart_labels = []
    chart_data = []
    cumulative = 0.0

    for row in settled_rows:
        timestamp = row.get("result_updated_at") or row.get("sent_at")
        try:
            label = datetime.fromtimestamp(int(timestamp)).strftime("%d.%m %H:%M")
        except (TypeError, ValueError, OSError):
            label = "—"

        # Здесь row["profit"] уже пересчитан правильно в цикле выше
        cumulative += float(row.get("profit") or 0)
        chart_labels.append(label)
        chart_data.append(round(cumulative, 2))

    return render_template_string(
        HTML_TEMPLATE,
        signals=signals,
        total=len(signals),
        wins=wins,
        loses=loses,
        pending=pending,
        accuracy=accuracy,
        profit=profit,
        roi=roi,
        updated=datetime.now().strftime("%d.%m.%Y %H:%M:%S"),
        chart_labels=json.dumps(chart_labels, ensure_ascii=False),
        chart_data=json.dumps(chart_data),
        status_labels={
            "WIN": "ЗАШЛО",
            "LOSE": "НЕ ЗАШЛО",
            "PENDING": "ОЖИДАНИЕ",
        },
    )


if __name__ == "__main__":
    db.init_db()
    app.run(host="0.0.0.0", port=3000, use_reloader=False)