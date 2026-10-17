# 提炼后的方法论（仅本地，不上传）

从 `../raw/` 提炼的结构化知识。**入口是 `00-index.md`（总索引）**，
规则定义见 `taxonomy.md`。

## 目录结构

```
00-index.md        总索引：域×层级条目清单与统计
taxonomy.md        分类体系：域/层级/类型/字段/状态机/溯源分级（权威定义）
conflicts.md       域边界与冲突消解 + 时效性风险清单
sources.md         SRC 编号 → 本地原始资料映射（不提作者）
data-source-map.md 条目 → MCP 工具映射 + 计算口径 + 数据盲区
dt/                DT 短线博弈域（41 条）
  market.md  targets.md  timing-buy.md  timing-sell.md  risk.md
xc/                XC 跨域共用
  trend-common.md  DT↔TR 趋势共性（6 条 + 参数差异对照）
vf/ tr/            待提炼
```

## 使用规则

- 分析前先声明风格域，只加载该域 + XC 适用条目（详见 taxonomy.md 隔离规则）
- 条目引用格式：`DT-R-014`；AI 补充条目带"AI补充"来源标注，信任级别见 taxonomy.md 溯源分级
- 引用"需校验"条目前先查 conflicts.md 第三节时效性风险清单
- 新增条目必须登记 00-index.md；作废条目保留编号标"已证伪"

## 提炼进度

- [x] DT 域首批：短线合集 10 PDF + 1 txt（2026-10-17）
- [ ] VF 域：价值投资入门与实战(41) + 老裘笔记(69) + 财报实战讲解（分批）
- [ ] TR 域：交易悟道 → 回填 xc/trend-common.md 的 TR 参数列
- [ ] 用户后续增补资料 → 按 taxonomy 流程入库
