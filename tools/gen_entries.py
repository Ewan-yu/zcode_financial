#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""从 knowledge/distilled/00-index.md 生成条目代号→中文标题映射 data/entries.json。
该文件含方法论标题，属本地敏感资产（.gitignore 排除，不入远端）；webapp 读它为
条目级胜率等处提供中文描述，文件不存在时优雅降级为仅显示代号。
知识库更新后重跑本脚本即可。"""
import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
src = ROOT / "knowledge" / "distilled" / "00-index.md"
out = ROOT / "data" / "entries.json"

entries = {}
for m in re.finditer(r"^\|\s*((?:DT|XC|TR|VF)-[RSJ]-\d+)\s*\|\s*([^|]+?)\s*\|", src.read_text(encoding="utf-8"), re.M):
    entries[m.group(1)] = m.group(2)

out.write_text(json.dumps(entries, ensure_ascii=False, indent=1), encoding="utf-8")
print("entries.json: %d 条 -> %s" % (len(entries), out))
