# 每日导出备份（`db.py export` 生成，仅本地）

每交易日复盘收尾执行 `python tools/db.py export <D>`，生成当日结构化 CSV；
`predictions` 与 `pool_events` 为全量导出。权威源是 `data/workbench.db`，本目录仅备份，
可删除后由库重建。报告全文以 `reports/` 存档原件为准（导出仅元数据，不含 content_md）。
