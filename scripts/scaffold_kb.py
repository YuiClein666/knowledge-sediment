#!/usr/bin/env python3
# -*- coding: utf-8 -*-
r"""scaffold_kb.py —— 按 taxonomy 生成知识库骨架

把一份"分类方案"变成实际的目录结构 + 各层索引文件。

用法：
    # 按方案生成（★ 初始化主路径）
    python scaffold_kb.py --taxonomy taxonomy.json --kb <知识库路径>

    # 不指定方案：从现有目录反推，只补缺失的索引文件
    python scaffold_kb.py --kb <知识库路径>

    # 先看看会建什么，不落盘
    python scaffold_kb.py --taxonomy taxonomy.json --kb <路径> --dry-run

    # 覆盖已存在的索引（危险：会丢掉手工写的内容）
    python scaffold_kb.py --taxonomy taxonomy.json --kb <路径> --force

设计原则：
- **幂等**：默认不覆盖已存在的文件——你的内容永远优先于模板
- **纯标准库**：任何有 Python 的环境都能跑
- **索引是给 Agent 看的**：`type` / `title` / `tags` / `keywords` / `summary`
  一个都不能少——`type` 尤其关键，工具链靠它区分"分类 / 单元 / 草稿"
"""
import argparse
import json
import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
try:
    import config as ksconfig
except Exception:
    ksconfig = None

TODAY = datetime.now().strftime("%Y-%m-%d")

# 知识库必备的保留目录（不是分类，但与检索/归档有关）
RESERVED_DIRS = {
    "00-inbox": ("待整理草稿（Inbox）",
                 "还没归类的内容先放这里。定期清理：归入单元、或删掉。",
                 ["inbox", "draft", "待整理"]),
    "90-archive": ("归档",
                   "过时但仍想留底的内容。不进检索主路径。",
                   ["archive", "deprecated", "归档"]),
}


def fmt_list(items):
    return ", ".join(str(x) for x in (items or []))


def root_index(tax):
    """顶层 index.md —— Agent 的第一入口：决定「去哪一类」

    注意：表格区块由 knowledge_cli.py index 自动维护，
    锚点是 `## 分类导航` … `## 全局检索词`，不要改这两个标题。
    """
    rows = "\n".join(
        f"| [`{c.get('id')}/`](./{c.get('id')}/_index.md) | {c.get('title', '')} "
        f"| {fmt_list((c.get('keywords') or [])[:5])} |"
        for c in tax
    ) or "| （待添加） | | |"
    return f"""---
title: 知识库索引
type: root-index
tags: [index, knowledge-base, 索引]
last_updated: {TODAY}
---

# 知识库索引

> 这是 Agent 检索的第一入口。**不要一次读完所有文件**——
> 先在这里定位分类，再看分类的 `_index.md` 定位单元，最后才读具体内容。

## 分类导航

| 分类 | 收什么 | 检索词 |
|---|---|---|
{rows}

## 全局检索词

（由 `knowledge_cli.py index` 从各单元的关键词聚合生成）

## 三个派生文件

| 文件 | 作用 | 生成方式 |
|---|---|---|
| `_map.md` | 引用地图——单元之间的依赖与关联 | `knowledge_cli.py map` |
| `_health.md` | 结构健康度——哪里膨胀了、哪里该拆 | `knowledge_cli.py health` |
| `README.md` | 给人类看的使用说明 | 初始化时生成 |

---

_索引由 `knowledge_cli.py index` 维护，不要手改上面的表格。_
"""


def category_index(cat):
    """分类层 _index.md —— Agent 靠它决定「去哪个单元找」

    表格区块锚点：`## 单元列表` … `## 本分类的检索词`
    """
    units = cat.get("units") or []
    rows = "\n".join(
        f"| [`{u.get('id')}/`](./{u.get('id')}/_index.md) | {u.get('title', '')} "
        f"| {fmt_list(u.get('keywords'))} |"
        for u in units
    ) or "| （待添加） | | |"
    return f"""---
title: {cat.get('title', '')}
type: category
tags: [{fmt_list(cat.get('keywords'))}]
summary: {cat.get('summary', '')}
last_updated: {TODAY}
---

# {cat.get('title', '')}

> {cat.get('summary', '')}

## 单元列表

| 单元 | 主题 | 检索词 |
|---|---|---|
{rows}

## 本分类的检索词

**{fmt_list(cat.get('keywords'))}**

---

_索引由 `knowledge_cli.py index` 维护，不要手改表格。_
"""


def unit_index(unit, cat_title="", cat_id=""):
    """单元层 _index.md —— Agent 靠它决定「读哪一篇」

    表格区块锚点：`## 本单元包含` … `## 相关单元`

    `type: unit` 是**必需**的——工具链靠它把所有单元目录找出来。
    """
    kw = fmt_list(unit.get("keywords"))
    return f"""---
title: {unit.get('title', '')}
type: unit
category: {cat_title}
tags: [{kw}]
keywords: [{kw}]
summary: {unit.get('summary', '')}
status: active
created: {TODAY}
last_reviewed: {TODAY}
relations: []
---

# {unit.get('title', '')}

> {unit.get('summary', '')}

## 本单元包含

| 文件 | 主题 | 摘要 |
|---|---|---|
| （待沉淀） | | |

## 相关单元

（沉淀后用 `knowledge_cli.py map` 自动填充）

## 待解决

（这个单元里还没搞明白的问题——写在这里，下次沉淀时优先处理）
"""


def kb_readme(kb_name="我的知识库"):
    return f"""# {kb_name}

> 记录**我会什么**，不是**我是谁**。

## 怎么用

| 我说 | 发生什么 |
|---|---|
| "沉淀一下" | Agent 把当前讨论里可复用的部分收进知识库 |
| "查一下 XX" | Agent 按分类和关键词去找 |
| 正常聊 | Agent 自动判断，有价值的顺手记 |

## 结构（三层索引）

```
index.md                       ← 第一入口：去哪一类
<分类>/_index.md               ← 第二入口：去哪一单元
<分类>/<单元>/_index.md        ← 第三入口：读哪一篇（含 tags/keywords/summary）
<分类>/<单元>/<主题>.md        ← 具体内容
```

每层都带检索词，所以 Agent 能从任意一层快速定位，不用通读全库。

## 内容状态

每篇内容的 `status` 字段：

| 状态 | 含义 |
|---|---|
| `draft` | 刚沉淀，还没验证 |
| `promoted` | 被复用或引用过，可信 |
| `deprecated` | 过时了，留底但别用 |

## 维护命令

```bash
python <工具库>/scripts/knowledge_cli.py index --kb "{'<本库路径>'}"   # 重建三层索引
python <工具库>/scripts/knowledge_cli.py map   --kb "..."          # 引用地图
python <工具库>/scripts/knowledge_cli.py health --kb "..."          # 结构健康度
python <工具库>/scripts/knowledge_cli.py stats --kb "..."           # 统计概览
```

（`--kb` 可省略——装了插件后配置里已经记着本库位置。）

---

_由 knowledge-sediment 生成于 {TODAY}_
"""


GITIGNORE = """# 私有内容本地保留、不上传（目录保留、内容忽略）
private/*
!private/.gitkeep

# Agent 在工作区里的临时沉淀区
.knowledge/
*.log

# 系统文件
.DS_Store
Thumbs.db
"""


def write(path: Path, content: str, force: bool, dry: bool, stats: dict):
    """写文件：默认不覆盖已有内容（保护用户手工成果）"""
    if path.exists() and not force:
        stats["skipped"] += 1
        return False
    if dry:
        stats["created"] += 1
        return True
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    stats["created"] += 1
    return True


def main():
    ap = argparse.ArgumentParser(description="按 taxonomy 生成知识库骨架")
    ap.add_argument("--taxonomy", default="", help="分类方案 JSON（省略则从现有目录反推）")
    ap.add_argument("--kb", required=True, help="知识库根目录（绝对路径）")
    ap.add_argument("--name", default="我的知识库", help="知识库名称（写进 README）")
    ap.add_argument("--dry-run", action="store_true", help="只预览，不落盘")
    ap.add_argument("--force", action="store_true", help="覆盖已存在的索引（会丢手工内容）")
    args = ap.parse_args()

    kb = Path(args.kb).expanduser().resolve()
    stats = {"created": 0, "skipped": 0}

    # 取分类方案
    if args.taxonomy:
        raw = json.loads(Path(args.taxonomy).expanduser().read_text(encoding="utf-8"))
        tax = raw.get("categories") if isinstance(raw, dict) else raw
        if not tax:
            print("✗ taxonomy 里没有 categories")
            return 1
    elif ksconfig is not None:
        tax = ksconfig.scan_taxonomy(kb)
        if not tax:
            print("✗ 知识库为空且未提供 --taxonomy，无事可做")
            return 1
        print(f"（未提供 --taxonomy，从现有目录反推：{len(tax)} 个分类）")
    else:
        print("✗ 需要 --taxonomy")
        return 1

    print(f"知识库：{kb}")
    print(f"分类数：{len(tax)}")
    print()

    if not args.dry_run:
        kb.mkdir(parents=True, exist_ok=True)

    # 1) 顶层入口
    print("[顶层]")
    for name, content in [
        ("index.md", root_index(tax)),
        ("README.md", kb_readme(args.name)),
        (".gitignore", GITIGNORE),
    ]:
        if write(kb / name, content, args.force, args.dry_run, stats):
            print(f"  ✓ {name}")

    # 2) 保留目录（不在 taxonomy 里就补上）
    have = {c.get("id") for c in tax}
    print("\n[保留目录]")
    for d, (title, summary, kw) in RESERVED_DIRS.items():
        if d in have:
            continue
        cat = {"id": d, "title": title, "summary": summary, "keywords": kw, "units": []}
        if write(kb / d / "_index.md", category_index(cat), args.force, args.dry_run, stats):
            print(f"  ✓ {d}/")

    # private 目录（内容不进 git，只留目录占位）
    if not args.dry_run:
        (kb / "private").mkdir(exist_ok=True)
        gk = kb / "private" / ".gitkeep"
        if not gk.exists():
            gk.write_text("", encoding="utf-8")
    print("  ✓ private/（内容不进 git）")

    # 3) 分类与单元
    for c in tax:
        cid = c.get("id")
        if not cid:
            continue
        print(f"\n[{cid}]  {c.get('title', '')}")
        if write(kb / cid / "_index.md", category_index(c), args.force, args.dry_run, stats):
            print(f"  ✓ {cid}/_index.md")
        for u in (c.get("units") or []):
            uid = u.get("id")
            if not uid:
                continue
            content = unit_index(u, c.get("title", ""), cid)
            if write(kb / cid / uid / "_index.md", content, args.force, args.dry_run, stats):
                print(f"  ✓ {cid}/{uid}/_index.md")

    print()
    print("=" * 52)
    print(f"{'（预览）' if args.dry_run else ''}新建 {stats['created']} 个文件，"
          f"跳过已存在 {stats['skipped']} 个")
    if stats["skipped"] and not args.force:
        print("（跳过是正常的——你的内容优先于模板。需要覆盖加 --force）")
    print()
    print("下一步：重建三层索引")
    print(f"  python \"<工具库>/scripts/knowledge_cli.py\" index --kb \"{kb}\"")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
