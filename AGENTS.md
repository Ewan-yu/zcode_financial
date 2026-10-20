# 项目工作规范（对本项目所有会话生效）

## 项目定位

个人投资研究工作台（A股 + 场内 ETF + 场外基金）。输出分析、信号与证据辅助用户决策，
不代做决策。核心原则：**所有可验证判断必须留痕**——没有台账记录的判断视为没有判断。

## 硬性约定

1. **技能作用域**：技能只创建在 `.zcode/skills/`（项目级）。禁止写入用户全局技能目录
   （`~/.zcode/skills`、`~/.agents/skills`）。
2. **数据来源**：默认走已装 MCP 插件——同花顺（`hexin-*`）、万得（`wind-*`）、天眼查
   （`tianyancha`）。不引入 Python 直连数据源（tushare/akshare 等）。
   **妙想官方技能包（`.zcode/skills/mx-*`，2026-10-20 用户指示安装）为第三通道**：
   选股类可平替问财（涨停/区间/成分股均线句式已对账一致）、资讯类可平替 wind-docs、
   行情类可冗余 wind；配额独立互为冗余，鉴权走用户级环境变量 `MX_APIKEY`
   （值不入任何 git 文件），手册见 `docs/miaoxiang-api.md`（本地）。
   **乐咕乐股（legulegu.com）为估值/情绪/宽度类指标的优先通道（2026-10-18 用户指示）**：
   其覆盖的数据（各指数 PE/PB、破净股、股债利差、巴菲特指标、风险溢价、拥挤度、市场宽度、
   赚钱效应、涨跌停统计等，目录普查见 `data/snapshots/20261018/legulegu_catalog_20261018.json`）
   优先用乐咕、不再调同花顺/万得；经 AI 会话内置浏览器抓取页面接口存档（`data/snapshots/`）
   后入库，禁止写成 Python 直连抓取代码；MCP 保留为乐咕无此数据或站点不可用时的回退。
3. **省配额**：低频数据（公司档案、财务、股本股东、工商）先查 `data/cache/`，命中且未过期
   则不重复调用 MCP。当日交易数据不入缓存。
4. **资产类型**：`stock`（A股）/ `etf`（场内 ETF、LOF）/ `of_fund`（场外基金）。
   自选/股池登记权威源为 `data/workbench.db` 股池体系（`tools/db.py pool`，预置
   dt_watchlist/author_short/author_long/dt_rejected + user_* 自建）；`portfolio/watchlist.json`
   降级为导出件（2026-10-17 起）。
5. **数据通道**：场内 ETF 行情、折溢价、IOPV 走 `wind-fund`（get_fund_kline /
   get_fund_price_indicators）；场外基金净值、档案、持仓走 `hexin-fund` 或 `wind-fund`；
   股票日频行情 `hexin get_stock_performance` 与 `wind-stock` 均可。
6. **判断留痕**：每次产生可验证判断（方向、买卖点、目标位）必须当场经
   `python tools/db.py add-prediction` 登记（权威源 `data/workbench.db` predictions 表），
   验证后 `db.py verify` 仅回填结果列；禁止事后补记、改写历史内容行。
   `predictions/predictions.csv` 已冻结为 2026-10-16 前历史存档。
7. **报告存档与入库**：`reports/daily/YYYY-MM-DD/`、`reports/weekly/`、`reports/research/`
   为存档原件；收尾动作同步写库——`db.py import-day`（结构化结论）+ `db.py report-add`
   （md 全文+关联标的/板块）+ `db.py export`（备份）。会话内展示用 visualize 交互看板，
   文件与库是存档与回溯依据。
8. **依据可溯**：分析结论注明所依据的方法论条目编号（`knowledge/distilled/`）；
   无条目支撑的直觉判断单独标注为"盘感"。
9. **交易日历**：非交易日定时任务空转跳过，不产出报告。
10. **输出语言**：中文。
11. **版本控制**：远端仓库（GitHub，公开）只保存源码、配置与模板；个人数据与知识资产
   （raw 原始资料、distilled 方法论、data/ 数据、portfolio 实际持仓、predictions 台账、
   reports 报告、docs/ 模块设计文档——含方法论流程细节）仅存本地，由 `.gitignore` 强制排除。
   禁止用 `git add -f` 绕过；提交前如新增文件位于这些目录，须确认未被误加。
12. **证据链与模板化输出**：四类分析产出（整体复盘 / 单票分析 / 板块对比 / 盘前简报）
    一律逐节套用 `templates/dt/` 固定模板，禁止增删章节与内容漂移；报告中每个数字必须
    可溯源到落盘快照（`data/snapshots/`、`data/cache/`）或当次工具返回，取不到写
    「数据缺失（原因）」，禁止估算编造；同一标的重复分析必须含「前次判断对账」节；
    交付前跑 `python tools/report_lint.py` 自检；用户可见看板不出现知识条目编号，
    以 `templates/dt/dashboard.html` 为统一骨架。
13. **本地数据库与服务**：权威存储 `data/workbench.db`（SQLite，WAL，属数据资产不入远端）；
    AI 会话经 `tools/db.py` CLI 写库（不依赖服务存活）。本地 Web 服务 `python webapp/app.py`
    仅绑定 127.0.0.1（读为主，写仅股池导入接口）；`webapp/` 源码随远端分发。
    设计与采集目录见 `docs/webapp-design.md`（本地）。
14. **采集目录治理**：新增数据采集项须先更新 `docs/webapp-design.md` 第三节目录再落地；
    每日常规 MCP 调用控制在约 10-15 次，低频数据走 `data/cache`。
