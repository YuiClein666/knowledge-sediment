#!/usr/bin/env python3
# -*- coding: utf-8 -*-
r"""
tree.py —— 输出知识库目录结构树（到"最小单元的 _index.md"为止）

用途：给人看的知识库结构说明（作品集 / 汇报 / README 插图）。

用法：
    python tree.py                 # 输出到 stdout
    python tree.py --write         # 同时写入 STRUCTURE.md
    python tree.py --no-count      # 不显示每单元篇数
"""
import argparse
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

# 工具类目录不展示（结构树只呈现"知识"部分）
SKIP = {"scripts", ".git", ".codebuddy-plugin", "skills", "hooks", "__pycache__", ".vscode", ".idea"}
TOP_FILES = ["index.md", "_map.md", "_health.md", "README.md"]


def title_of(index_md: Path) -> str:
    """从 _index.md 的 frontmatter 取 title"""
    try:
        text = index_md.read_text(encoding="utf-8")
    except Exception:
        return ""
    m = re.search(r"^title:\s*(.+?)\s*$", text, re.M)
    if not m:
        return ""
    return m.group(1).strip().strip('"').strip("'")


def summary_of(index_md: Path) -> str:
    try:
        text = index_md.read_text(encoding="utf-8")
    except Exception:
        return ""
    m = re.search(r"^summary:\s*(.+?)\s*$", text, re.M)
    return m.group(1).strip().strip('"').strip("'") if m else ""


def note_count(d: Path) -> int:
    n = 0
    for p in d.rglob("*.md"):
        if not p.name.startswith("_"):
            n += 1
    return n


def render(show_count: bool = True) -> str:
    lines = ["knowledge/"]
    for f in TOP_FILES:
        if (ROOT / f).exists():
            lines.append(f"├── {f}")

    top = sorted([d for d in ROOT.iterdir() if d.is_dir() and d.name not in SKIP],
                 key=lambda x: x.name)

    for i, cat in enumerate(top):
        cat_last = (i == len(top) - 1)
        cat_t = title_of(cat / "_index.md")
        cat_n = note_count(cat)
        tag = f"  # {cat_t}" if cat_t else ""
        cnt = f"    [{cat_n} 篇]" if (show_count and cat_n) else ""
        lines.append(f"{'└──' if cat_last else '├──'} {cat.name}/{tag}{cnt}")

        pre = "    " if cat_last else "│   "

        subs = sorted([d for d in cat.iterdir() if d.is_dir() and d.name not in SKIP],
                      key=lambda x: x.name)

        # 分类自己的 _index.md 与子单元并列展示
        entries = []
        if (cat / "_index.md").exists():
            entries.append(("file", None))
        entries += [("dir", s) for s in subs]

        for j, (kind, item) in enumerate(entries):
            last = (j == len(entries) - 1)
            br = "└──" if last else "├──"
            if kind == "file":
                lines.append(f"{pre}{br} _index.md")
                continue
            sub_t = title_of(item / "_index.md")
            sub_n = note_count(item)
            st = f"  # {sub_t}" if sub_t else ""
            sc = f"    [{sub_n} 篇]" if (show_count and sub_n) else ("    [空单元]" if show_count else "")
            lines.append(f"{pre}{br} {item.name}/{st}{sc}")
            pre2 = pre + ("    " if last else "│   ")
            lines.append(f"{pre2}└── _index.md")
    return "\n".join(lines)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--write", action="store_true", help="同时写入 STRUCTURE.md")
    ap.add_argument("--no-count", action="store_true", help="不显示篇数")
    args = ap.parse_args()

    tree = render(show_count=not args.no_count)
    print(tree)

    if args.write:
        out = ROOT / "STRUCTURE.md"
        total_units = sum(1 for p in ROOT.rglob("_index.md")
                          if any(part in SKIP for part in p.parts) is False
                          and re.search(r"^type:\s*unit\s*$",
                                        p.read_text(encoding="utf-8"), re.M))
        cats = sum(1 for d in ROOT.iterdir()
                   if d.is_dir() and d.name not in SKIP and (d / "_index.md").exists())
        total_notes = sum(1 for p in ROOT.rglob("*.md")
                          if not p.name.startswith("_") and not any(part in SKIP for part in p.parts))
        content = f"""---
title: 知识库结构
type: doc
tags: [structure, index]
---

# 知识库结构

> 本文件由 `scripts/tree.py --write` 自动生成，**请勿手动编辑**。

- 顶层分类：**{cats}**
- 知识单元：**{total_units}**
- 内容文件：**{total_notes}**

## 设计原则

1. **位置即含义**——数字编号承担语义（`10-` 前端工程 / `20-` 后端 / `70-` 客户端 …），
   看到路径就知道知识属于哪一类，不依赖记忆。
2. **三层检索**——`index.md`（去哪一类）→ `<分类>/_index.md`（去哪一单元）→
   `<单元>/_index.md`（读哪一篇）。每层都带 `tags` 与 `keywords`，Agent 逐层收敛、不读全库。
3. **最小单元**——一个单元 = 一个可独立理解与复用的知识主题（如 `11-react-patterns`）；
   单元内可继续细分，超过 12 篇会由健康度检查提示拆分。
4. **横向关系**——单元与笔记可声明 5 类关系（`requires` / `relates_to` / `supersedes` /
   `contradicts` / `used_in`），由 `_map.md` 汇总成跨目录引用地图。
5. **结构自检**——`_health.md` 监控 8 项结构指标（单元膨胀、孤儿单元、时效过期、草稿积压等）。

## 目录树（到最小单元的索引为止）

```text
{tree}
```

## 每个单元里的 `_index.md` 长什么样

```yaml
---
title: MySQL
type: unit
category: 后端开发
tags: [mysql, index, transaction, mvcc, optimization, interview]
keywords: [B+树, 聚簇索引, 回表, 覆盖索引, MVCC, 隔离级别, 间隙锁, 死锁, 慢SQL]
summary: MySQL 索引结构、事务与锁机制、性能优化实践；含八股要点与面试真题
status: active
created: 2026-09-17
last_reviewed: 2026-09-17
relations:
  - type: relates_to
    target: 10-frontend/11-react-patterns
---

# MySQL

> MySQL 索引结构、事务与锁机制、性能优化实践；含八股要点与面试真题

## 本单元包含          ← 由脚本自动生成的文件清单（文件 / 主题 / 摘要）

## 相关单元            ← 从 relations 自动生成

## 待解决问题          ← 开放问题，供后续补充
```

**关键字段的作用**：

| 字段 | 作用 |
|---|---|
| `keywords` | Agent 快速判断"这个单元是不是我要找的" |
| `summary` | 一句话说明单元内容边界 |
| `relations` | 声明跨单元关系，汇聚到 `_map.md` |
| `status` | 生命周期（`active` / `archived`） |
| `last_reviewed` | 时效锚点，超过 180 天未复核会被健康度报告标黄 |

---

_由 `scripts/tree.py` 生成_
"""
        out.write_text(content, encoding="utf-8")
        print(f"\n✓ 已写入 {out}")


if __name__ == "__main__":
    main()
