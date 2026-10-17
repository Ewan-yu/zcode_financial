# webapp —— 本地复盘工作台（P2/P3）

只读展示 `data/workbench.db`（写权限仅股池导入 `POST /pool/import`）。

## 启动

```bash
pip install flask        # 唯一依赖
python webapp/app.py     # → http://127.0.0.1:8787
```

仅绑定本机 127.0.0.1，不对局域网/公网开放；服务无需常驻——分析写库走 `tools/db.py` CLI，
不依赖本服务存活。

## 页面

| 路由 | 内容 |
|---|---|
| `/` | 总览：温度卡组 + 情绪周期位置条 + 指数趋势 + 当日候选 + 待验证台账 + 股池摘要 |
| `/trend` | 情绪时序（六指标/广度/指数——随每日复盘前向积累） |
| `/ledger` | 判断台账 + 胜率统计 |
| `/pools` `/pool/<key>` | 股池总览 / 单池（成员+事件时间线+**自助导入**） |
| `/reports` `/report/<id>` | 报告中心：md 全文渲染 |
| `/review/<date>` | 每日复盘六模块（与看板同一渲染引擎 board.js） |
| `/stock/<code>` | 个股档案：日K + 历次分析 + 台账 + **合并时间线** + 相关报告 |

## 结构

- `app.py`：路由 + REAL_DATA 组装（复盘页数据由库拼装，结构与看板注入完全一致）
- `static/js/board.js`：渲染引擎（自 `templates/dt/dashboard.html` 抽取，单一来源原则）
- `static/css/board.css`：主题（涨红跌绿）
- `templates/`：Jinja2 页面

数据注入采用 Jinja `tojson`（中文转 `\uXXXX` 属正常，浏览器端解析无影响）。
