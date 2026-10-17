# 持仓组合（个人数据，仅本地）

本目录的实际数据文件（`watchlist.json`、`positions.md`）包含真实自选与持仓，
属敏感信息，**不入远端仓库**（`.gitignore` 已排除）。

- `watchlist.template.json` / `positions.template.md` — 结构模板，随源码入库
- 首次使用：复制模板为 `watchlist.json` / `positions.md` 后填写真实内容

自选池规范见根目录 README：`asset_type` = `stock`（A股）/ `etf`（场内 ETF、LOF）/
`of_fund`（场外基金）；场内标的走每日盯盘循环，场外基金周度跟踪。
