#!/usr/bin/env python3
"""HTML analysis report generator — creates a self-contained HTML report with
Chart.js visualizations from a vault_cli JSON chat export.
"""

import json
import re
import sys
from collections import Counter
from datetime import datetime
from pathlib import Path


def _prepare_chart_data(data: dict) -> dict:
    msgs = data["messages"]

    # Top participants
    senders = Counter(m["sender"] for m in msgs if m["sender"] != "系统")
    top_senders = senders.most_common(15)

    # Daily trend
    days = Counter()
    for m in msgs:
        t = m.get("time", "")
        if t:
            days[t[:10]] += 1
    daily = sorted(days.items())

    # Countries
    all_text = "\n".join(m["content"] for m in msgs if m["content_type"] in (0, 2))
    countries_list = ["美国","加拿大","德国","西班牙","意大利","荷兰","瑞士","法国","奥地利",
                      "墨西哥","塞浦路斯","波兰","瑞典","巴西","哥伦比亚","英国","日本","澳大利亚"]
    country_data = sorted(
        [(c, all_text.count(c)) for c in countries_list if all_text.count(c) > 0],
        key=lambda x: -x[1],
    )

    # Shipping methods
    methods_list = ["空运","卡派","空卡","空派","卡车","包税","双清","快递","专线","海运","FBA","海派","海卡"]
    method_data = sorted(
        [(m, all_text.count(m)) for m in methods_list if all_text.count(m) > 0],
        key=lambda x: -x[1],
    )

    # Product types
    products_list = ["普货","带电","电池","不带电","LED","塑料","认证","金属","玩具","液体",
                     "玻璃","灯具","FDA","医疗","CPSC","服装","椅子","实木","纺织品"]
    product_data = sorted(
        [(p, all_text.count(p)) for p in products_list if all_text.count(p) > 0],
        key=lambda x: -x[1],
    )

    # Price keywords
    price_list = ["价格","附加费","单价","报价","费用","运费","多少钱"]
    price_data = sorted(
        [(p, all_text.count(p)) for p in price_list if all_text.count(p) > 0],
        key=lambda x: -x[1],
    )

    # Message types
    types = Counter(m["type_name"] for m in msgs)
    type_data = types.most_common()

    # Hourly activity
    hours = Counter()
    for m in msgs:
        t = m.get("time", "")
        if t and len(t) >= 13:
            hours[int(t[11:13])] += 1
    hourly = [(h, hours.get(h, 0)) for h in range(24)]

    # Weekday activity
    weekdays = Counter()
    weekday_names = ["周一","周二","周三","周四","周五","周六","周日"]
    for m in msgs:
        t = m.get("time", "")
        if t:
            try:
                dt = datetime.strptime(t[:19], "%Y-%m-%d %H:%M:%S")
                weekdays[dt.weekday()] += 1
            except (ValueError, TypeError):
                pass
    weekday_data = [(weekday_names[i], weekdays.get(i, 0)) for i in range(7)]

    return {
        "top_senders": top_senders,
        "daily": daily,
        "countries": country_data,
        "methods": method_data,
        "products": product_data,
        "prices": price_data,
        "types": type_data,
        "hourly": hourly,
        "weekdays": weekday_data,
        "total_msgs": len(msgs),
        "participants": len(senders),
        "date_range": [daily[0][0] if daily else "", daily[-1][0] if daily else ""],
        "active_days": len(days),
    }


HTML_TEMPLATE = """<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>{title} - 群聊记录分析报告</title>
<script src="https://cdn.jsdelivr.net/npm/chart.js@4.4.1/dist/chart.umd.min.js"></script>
<style>
  :root {{ --bg:#f5f7fa; --card:#fff; --text:#1a1a2e; --muted:#6b7280; --border:#e5e7eb; --blue:#2563eb; --blue-l:#dbeafe; --red:#dc2626; --green:#16a34a; --orange:#ea580c; --purple:#7c3aed; --teal:#0d9488; }}
  * {{ margin:0; padding:0; box-sizing:border-box; }}
  body {{ font-family:-apple-system,BlinkMacSystemFont,"Segoe UI","PingFang SC","Microsoft YaHei",sans-serif; background:var(--bg); color:var(--text); line-height:1.6; }}
  .container {{ max-width:1200px; margin:0 auto; padding:24px 16px; }}
  .header {{ background:linear-gradient(135deg,#1e3a5f 0%,#2563eb 100%); color:#fff; border-radius:16px; padding:32px; margin-bottom:24px; box-shadow:0 4px 20px rgba(37,99,235,0.15); }}
  .header h1 {{ font-size:24px; margin-bottom:8px; }}
  .header .sub {{ font-size:14px; opacity:0.85; }}
  .header .meta {{ display:flex; gap:24px; margin-top:16px; flex-wrap:wrap; }}
  .header .meta-item {{ background:rgba(255,255,255,0.15); border-radius:8px; padding:8px 16px; font-size:13px; }}
  .header .meta-item strong {{ font-size:20px; display:block; }}
  .stats {{ display:grid; grid-template-columns:repeat(auto-fit,minmax(220px,1fr)); gap:16px; margin-bottom:24px; }}
  .stat {{ background:var(--card); border-radius:12px; padding:20px; border:1px solid var(--border); box-shadow:0 1px 3px rgba(0,0,0,0.05); }}
  .stat .l {{ font-size:13px; color:var(--muted); margin-bottom:4px; }}
  .stat .v {{ font-size:28px; font-weight:700; color:var(--blue); }}
  .stat .s {{ font-size:12px; color:var(--muted); margin-top:4px; }}
  .section {{ background:var(--card); border-radius:12px; padding:24px; margin-bottom:20px; border:1px solid var(--border); box-shadow:0 1px 3px rgba(0,0,0,0.05); }}
  .section-title {{ font-size:17px; font-weight:700; margin-bottom:16px; display:flex; align-items:center; gap:8px; }}
  .section-title::before {{ content:""; width:4px; height:18px; background:var(--blue); border-radius:2px; }}
  .grid {{ display:grid; grid-template-columns:1fr 1fr; gap:20px; }}
  .grid.full {{ grid-template-columns:1fr; }}
  .box {{ position:relative; }}
  .box h3 {{ font-size:14px; color:var(--muted); margin-bottom:8px; }}
  .insights {{ display:grid; grid-template-columns:1fr 1fr; gap:16px; }}
  .insight {{ background:var(--blue-l); border-radius:10px; padding:16px; border-left:4px solid var(--blue); }}
  .insight h4 {{ font-size:14px; margin-bottom:6px; color:var(--blue); }}
  .insight p {{ font-size:13px; }}
  .table {{ width:100%; border-collapse:collapse; font-size:13px; }}
  .table th {{ text-align:left; padding:8px 12px; background:var(--bg); color:var(--muted); font-weight:600; border-bottom:2px solid var(--border); }}
  .table td {{ padding:8px 12px; border-bottom:1px solid var(--border); }}
  .badge {{ display:inline-block; padding:2px 8px; border-radius:4px; font-size:11px; font-weight:600; }}
  .footer {{ text-align:center; padding:20px; color:var(--muted); font-size:12px; }}
  @media (max-width:768px) {{ .grid,.insights {{ grid-template-columns:1fr; }} }}
</style>
</head>
<body>
<div class="container">
  <div class="header">
    <h1>{title} · 群聊记录分析</h1>
    <div class="sub">企业微信本地数据库解密分析报告 · 数据范围 {date_start} ~ {date_end}</div>
    <div class="meta">
      <div class="meta-item"><strong>{total}</strong>条消息</div>
      <div class="meta-item"><strong>{participants}</strong>位参与者</div>
      <div class="meta-item"><strong>{active_days}</strong>个活跃天</div>
    </div>
  </div>
  <div class="stats">
    <div class="stat"><div class="l">消息总量</div><div class="v">{total}</div><div class="s">已导出</div></div>
    <div class="stat"><div class="l">参与人数</div><div class="v">{participants}</div><div class="s">发过消息的成员</div></div>
    <div class="stat"><div class="l">日均消息</div><div class="v">{avg_daily}</div><div class="s">条/活跃天</div></div>
    <div class="stat"><div class="l">活跃天数</div><div class="v">{active_days}</div><div class="s">天</div></div>
  </div>
  <div class="section"><div class="section-title">消息趋势</div><div class="grid full"><div class="box"><h3>每日消息量</h3><canvas id="c1" height="60"></canvas></div></div></div>
  <div class="section"><div class="section-title">活跃度</div><div class="grid"><div class="box"><h3>按小时</h3><canvas id="c2" height="160"></canvas></div><div class="box"><h3>按星期</h3><canvas id="c3" height="160"></canvas></div></div></div>
  <div class="section"><div class="section-title">参与者 Top 15</div><div class="grid full"><div class="box"><canvas id="c4" height="100"></canvas></div></div></div>
  <div class="section"><div class="section-title">业务分析</div><div class="grid"><div class="box"><h3>目的国家</h3><canvas id="c5" height="200"></canvas></div><div class="box"><h3>物流方式</h3><canvas id="c6" height="200"></canvas></div><div class="box"><h3>货物类型</h3><canvas id="c7" height="200"></canvas></div><div class="box"><h3>价格关键词</h3><canvas id="c8" height="200"></canvas></div></div></div>
  <div class="section"><div class="section-title">消息类型</div><div class="grid"><div class="box"><canvas id="c9" height="200"></canvas></div><div class="box"><h3>明细</h3><table class="table"><thead><tr><th>类型</th><th>数量</th><th>占比</th></tr></thead><tbody>{type_rows}</tbody></table></div></div></div>
  <div class="footer">报告生成于 {generated_at} · 数据来源：企业微信本地数据库解密快照</div>
</div>
<script>
const D={chart_json};
const P=['#2563eb','#dc2626','#16a34a','#ea580c','#7c3aed','#0d9488','#db2777','#ca8a04','#0891b2','#4f46e5','#059669','#b91c1c','#9333ea','#0284c7','#65a30d','#c2410c','#1d4ed8','#be185d'];
new Chart(document.getElementById('c1'),{{type:'line',data:{{labels:D.daily.map(d=>d[0]),datasets:[{{data:D.daily.map(d=>d[1]),borderColor:'#2563eb',backgroundColor:'rgba(37,99,235,0.1)',fill:true,tension:0.3,pointRadius:0,borderWidth:2}}]}},options:{{plugins:{{legend:{{display:false}}}},scales:{{x:{{ticks:{{maxTicksLimit:12,font:{{size:10}}}}}},y:{{beginAtZero:true}}}}}});
new Chart(document.getElementById('c2'),{{type:'bar',data:{{labels:D.hourly.map(h=>h[0]+':00'),datasets:[{{data:D.hourly.map(h=>h[1]),backgroundColor:'#2563eb',borderRadius:4}}]}},options:{{plugins:{{legend:{{display:false}}}},scales:{{y:{{beginAtZero:true}}}}}}}});
new Chart(document.getElementById('c3'),{{type:'bar',data:{{labels:D.weekdays.map(w=>w[0]),datasets:[{{data:D.weekdays.map(w=>w[1]),backgroundColor:['#2563eb','#2563eb','#2563eb','#2563eb','#2563eb','#dc2626','#dc2626'],borderRadius:4}}]}},options:{{plugins:{{legend:{{display:false}}}},scales:{{y:{{beginAtZero:true}}}}}}}});
new Chart(document.getElementById('c4'),{{type:'bar',data:{{labels:D.top_senders.map(s=>s[0]),datasets:[{{data:D.top_senders.map(s=>s[1]),backgroundColor:P,borderRadius:4}}]}},options:{{indexAxis:'y',plugins:{{legend:{{display:false}}}},scales:{{x:{{beginAtZero:true}}}}}}}});
new Chart(document.getElementById('c5'),{{type:'bar',data:{{labels:D.countries.map(c=>c[0]),datasets:[{{data:D.countries.map(c=>c[1]),backgroundColor:'#2563eb',borderRadius:4}}]}},options:{{indexAxis:'y',plugins:{{legend:{{display:false}}}},scales:{{x:{{beginAtZero:true}}}}}}}});
new Chart(document.getElementById('c6'),{{type:'bar',data:{{labels:D.methods.map(m=>m[0]),datasets:[{{data:D.methods.map(m=>m[1]),backgroundColor:'#0d9488',borderRadius:4}}]}},options:{{indexAxis:'y',plugins:{{legend:{{display:false}}}},scales:{{x:{{beginAtZero:true}}}}}}}});
new Chart(document.getElementById('c7'),{{type:'bar',data:{{labels:D.products.map(p=>p[0]),datasets:[{{data:D.products.map(p=>p[1]),backgroundColor:'#ea580c',borderRadius:4}}]}},options:{{indexAxis:'y',plugins:{{legend:{{display:false}}}},scales:{{x:{{beginAtZero:true}}}}}}}});
new Chart(document.getElementById('c8'),{{type:'bar',data:{{labels:D.prices.map(p=>p[0]),datasets:[{{data:D.prices.map(p=>p[1]),backgroundColor:'#7c3aed',borderRadius:4}}]}},options:{{indexAxis:'y',plugins:{{legend:{{display:false}}}},scales:{{x:{{beginAtZero:true}}}}}}}});
new Chart(document.getElementById('c9'),{{type:'doughnut',data:{{labels:D.types.map(t=>t[0]),datasets:[{{data:D.types.map(t=>t[1]),backgroundColor:P}}]}},options:{{plugins:{{legend:{{position:'right',labels:{{font:{{size:11}},padding:8}}}}}}}}}});
</script>
</body>
</html>"""


def generate_html_report(input_json: str, output_html: str) -> None:
    """Generate a self-contained HTML analysis report from a vault_cli JSON export."""
    with Path(input_json).open(encoding="utf-8") as f:
        data = json.load(f)

    cd = _prepare_chart_data(data)
    title = data["session"]["display_name"]
    total = cd["total_msgs"]

    type_rows = "".join(
        f'<tr><td>{t}</td><td>{c:,}</td><td><span class="badge" style="background:#dbeafe;color:#2563eb">{c/total*100:.1f}%</span></td></tr>'
        for t, c in cd["types"]
    )

    html = HTML_TEMPLATE.format(
        title=title,
        date_start=cd["date_range"][0],
        date_end=cd["date_range"][1],
        total=f"{total:,}",
        participants=cd["participants"],
        active_days=cd["active_days"],
        avg_daily=total // max(cd["active_days"], 1),
        type_rows=type_rows,
        chart_json=json.dumps(cd, ensure_ascii=False),
        generated_at=datetime.now().strftime("%Y-%m-%d %H:%M"),
    )

    Path(output_html).write_text(html, encoding="utf-8")


if __name__ == "__main__":
    if len(sys.argv) < 3:
        print("Usage: python3 html_report.py <input.json> <output.html>")
        sys.exit(1)
    generate_html_report(sys.argv[1], sys.argv[2])
    print(f"Done: {sys.argv[2]}")
