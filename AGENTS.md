# 项目工作规范（对本项目所有会话生效）

## 项目定位

个人投资研究工作台（A股 + 场内 ETF + 场外基金）。输出分析、信号与证据辅助用户决策，
不代做决策。核心原则：**所有可验证判断必须留痕**——没有台账记录的判断视为没有判断。

## 硬性约定

1. **技能作用域**：技能只创建在 `.zcode/skills/`（项目级）。禁止写入用户全局技能目录
   （`~/.zcode/skills`、`~/.agents/skills`）。
2. **数据来源**：一律走已装 MCP 插件——同花顺（`hexin-*`）、万得（`wind-*`）、天眼查
   （`tianyancha`）。不引入 Python 直连数据源（tushare/akshare 等）。
3. **省配额**：低频数据（公司档案、财务、股本股东、工商）先查 `data/cache/`，命中且未过期
   则不重复调用 MCP。当日交易数据不入缓存。
4. **资产类型**：`stock`（A股）/ `etf`（场内 ETF、LOF）/ `of_fund`（场外基金），
   统一登记在 `portfolio/watchlist.json`。
5. **数据通道**：场内 ETF 行情、折溢价、IOPV 走 `wind-fund`（get_fund_kline /
   get_fund_price_indicators）；场外基金净值、档案、持仓走 `hexin-fund` 或 `wind-fund`；
   股票日频行情 `hexin get_stock_performance` 与 `wind-stock` 均可。
6. **判断留痕**：每次产生可验证判断（方向、买卖点、目标位）必须当场追加
   `predictions/predictions.csv`，禁止事后补记或改写历史行。
7. **报告存档**：`reports/daily/YYYY-MM-DD/`、`reports/weekly/`、`reports/research/`；
   会话内展示用 visualize 交互看板，文件是存档与回溯依据。
8. **依据可溯**：分析结论注明所依据的方法论条目编号（`knowledge/distilled/`）；
   无条目支撑的直觉判断单独标注为"盘感"。
9. **交易日历**：非交易日定时任务空转跳过，不产出报告。
10. **输出语言**：中文。
