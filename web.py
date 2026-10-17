from flask import Flask, render_template_string
import database as db
from datetime import datetime
from collections import defaultdict
import os

app = Flask(__name__)

# =====================================================================
# HTML ШАБЛОН С ТВОИМ ФОНОМ
# =====================================================================
HTML_TEMPLATE = """
<!DOCTYPE html>
<html lang="ru">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Статистика Live-Бота</title>
    <script src="https://cdn.jsdelivr.net/npm/chart.js"></script>
    <style>
        body { 
            font-family: Inter, Arial, sans-serif; 
            
            /* 🔥 ФОН С ТВОЕЙ КАРТИНКОЙ */
            background-image: url('https://raw.githubusercontent.com/t1mwatson-bel/foot_live/main/IMG_1843.png');
            background-size: cover;
            background-position: center;
            background-attachment: fixed;
            background-color: #03050a;
            
            color: #fff; 
            margin: 0; 
            padding: 20px; 
            min-height: 100vh; 
        }
        
                /* Затемнение, чтобы текст читался (сделали чуть прозрачнее) */
        body::before {
            content: "";
            position: fixed;
            top: 0; left: 0; width: 100%; height: 100%;
            background: rgba(0, 0, 0, 0.5); /* Было 0.75, стало 0.5 */
            z-index: -1;
        }
        
        .container { max-width: 1400px; margin: auto; }
        .header { text-align: center; margin-bottom: 30px; }
        .logo { font-size: 32px; font-weight: 900; letter-spacing: 3px; text-shadow: 0 0 10px rgba(0, 200, 255, .6); }
        .grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(200px, 1fr)); gap: 15px; margin-bottom: 25px; }
        
        /* КАРТОЧКИ (сделали прозрачными и размытыми) */
        .card { 
            background: rgba(30, 41, 59, 0.4); /* Прозрачность 40% */
            backdrop-filter: blur(12px);       /* Эффект матового стекла */
            -webkit-backdrop-filter: blur(12px);
            border: 1px solid rgba(255, 255, 255, 0.15); /* Светлая рамка */
            border-radius: 18px; 
            padding: 22px; 
            text-align: center; 
            box-shadow: 0 8px 32px 0 rgba(0, 0, 0, 0.3); 
        }
        .card h3 { color: #e2e8f0; font-size: 13px; margin-bottom: 10px; text-transform: uppercase; }
        .val { font-size: 32px; font-weight: 800; }
        .green { color: #4cff9b; text-shadow: 0 0 12px rgba(76, 255, 155, .7); }
        .red { color: #ff5d70; text-shadow: 0 0 12px rgba(255, 93, 112, .7); }
        .orange { color: #ffbd66; }
        
        /* СЕКЦИИ (График и Таблица) */
        .section { 
            background: rgba(30, 41, 59, 0.4); /* Прозрачность 40% */
            backdrop-filter: blur(12px);
            -webkit-backdrop-filter: blur(12px);
            border: 1px solid rgba(255, 255, 255, 0.15); 
            border-radius: 20px; 
            padding: 22px; 
            margin-bottom: 25px; 
        }
        .section-title { font-size: 20px; font-weight: 800; margin-bottom: 18px; text-shadow: 0 0 8px rgba(0, 255, 200, .5); }
        .chart-container { height: 300px; }
        table { width: 100%; border-collapse: collapse; }
        th { text-align: left; color: #7e8ba0; font-size: 12px; text-transform: uppercase; padding: 13px; border-bottom: 1px solid rgba(0, 200, 255, .15); }
        td { padding: 14px 13px; border-bottom: 1px solid rgba(255, 255, 255, .05); font-size: 14px; }
        tr:hover td { background: rgba(0, 200, 255, .04); }
    </style>
</head>
<body>
<div class="container">
    <div class="header"><div class="logo">🔴 LIVE-БОТ СТАТИСТИКА</div></div>
    <div class="grid">
        <div class="card"><h3>Профит</h3><div class="val {{ 'green' if total_profit >= 0 else 'red' }}">{{ "%+.2f"|format(total_profit) }}</div></div>
        <div class="card"><h3>ROI</h3><div class="val {{ 'green' if roi >= 0 else 'red' }}">{{ "%.1f"|format(roi) }}%</div></div>
        <div class="card"><h3>Зашло / Не зашло</h3><div class="val"><span class="green">{{ wins }}</span> / <span class="red">{{ loses }}</span></div></div>
        <div class="card"><h3>В ожидании</h3><div class="val orange">{{ pendings }}</div></div>
    </div>
    <div class="section">
        <div class="section-title">📈 График профита</div>
        <div class="chart-container"><canvas id="profitChart"></canvas></div>
    </div>
    <div class="section">
        <div class="section-title">📜 Все сигналы</div>
        <table>
            <thead><tr><th>Дата</th><th>Матч</th><th>Лига</th><th>Стратегия</th><th>Кэф</th><th>Статус</th><th>Профит</th></tr></thead>
            <tbody>
                {% for s in signals %}
                <tr>
                    <td>{{ s.sent_at | timestamp_to_date }}</td>
                    <td><strong>{{ s.match_name }}</strong></td>
                    <td>{{ s.league }}</td>
                    <td><span style="color: #65aaff">{{ s.strategy }}</span></td>
                    <td>{{ "%.2f"|format(s.odds) }}</td>
                    <td class="{{ 'green' if s.status=='WIN' else 'red' if s.status=='LOSE' else 'orange' }}">{{ s.status }}</td>
                    <td class="{{ 'green' if s.profit>0 else 'red' if s.profit<0 else '' }}">{{ "%+.2f"|format(s.profit) }}</td>
                </tr>
                {% endfor %}
            </tbody>
        </table>
    </div>
</div>
<script>
    new Chart(document.getElementById('profitChart').getContext('2d'), {
        type: 'line',
        data: { labels: {{ chart_labels | safe }}, datasets: [{ label: 'Профит', data: {{ chart_data | safe }}, borderColor: '#00ffe0', backgroundColor: 'rgba(0, 255, 224, 0.1)', borderWidth: 3, fill: true, tension: 0.3 }] },
        options: { responsive: true, maintainAspectRatio: false, plugins: { legend: { display: false } }, scales: { y: { grid: { color: '#1e293b' }, ticks: { color: '#64748b' } }, x: { grid: { display: false }, ticks: { color: '#64748b' } } } }
    });
</script>
</body>
</html>
"""

@app.template_filter('timestamp_to_date')
def timestamp_to_date(ts):
    if not ts: return "-"
    return datetime.fromtimestamp(ts).strftime('%d.%m %H:%M')

@app.route('/')
def index():
    signals = db.get_all_signals() # Тянем из базы
    wins = sum(1 for s in signals if s['status'] == 'WIN')
    loses = sum(1 for s in signals if s['status'] == 'LOSE')
    pendings = sum(1 for s in signals if s['status'] == 'PENDING')
    total_profit = sum(s['profit'] for s in signals)
    total_bets = wins + loses
    roi = (total_profit / total_bets * 100) if total_bets > 0 else 0.0

    daily_profit = defaultdict(float)
    for s in signals:
        if s['status'] in ['WIN', 'LOSE']:
            day = datetime.fromtimestamp(s['sent_at']).strftime('%d.%m')
            daily_profit[day] += s['profit']
    
    chart_labels, chart_data = [], []
    cumulative = 0
    for day in sorted(daily_profit.keys(), key=lambda d: datetime.strptime(d, '%d.%m')):
        cumulative += daily_profit[day]
        chart_labels.append(day)
        chart_data.append(round(cumulative, 2))

    return render_template_string(HTML_TEMPLATE, signals=signals, wins=wins, loses=loses, pendings=pendings, total_profit=total_profit, roi=roi, chart_labels=str(chart_labels).replace("'", '"'), chart_data=chart_data)

@app.route('/health')
def health():
    return "OK", 200

if __name__ == '__main__':
    # Порт 3000, так как Bothost требует именно его
    app.run(host='0.0.0.0', port=3000)
