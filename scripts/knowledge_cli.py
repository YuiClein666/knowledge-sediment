#!/usr/bin/env python3
# -*- coding: utf-8 -*-
r"""
knowledge_cli.py —— 个人知识库管理工具（插件核心）

用法：
    python knowledge_cli.py index     # 重建所有 _index.md 的"本单元包含"表
    python knowledge_cli.py map       # 从 relations 生成 _map.md 引用地图
    python knowledge_cli.py health    # 生成 _health.md 结构健康度报告
    python knowledge_cli.py stats     # 打印统计概览
    python knowledge_cli.py capture --from <文件> --tag <标签>   # 沉淀内容到 inbox
    python knowledge_cli.py sync [--push]                        # git 同步

设计原则：
- 纯标准库，无第三方依赖（可在任意环境跑）
- 幂等：重复运行结果一致
- 只读扫描 + 定点写入，不破坏手工内容
"""
import argparse
import re
import subprocess
import sys
from datetime import datetime, timedelta
from pathlib import Path

# 共享配置模块（同目录）——让"知识库在哪、有哪些分类"都不写死
sys.path.insert(0, str(Path(__file__).resolve().parent))
try:
    import config as ksconfig
except Exception:  # 极端情况下退化为旧行为，不阻塞
    ksconfig = None


def _resolve_root(explicit=""):
    """知识库根目录：显式参数 / 环境变量 / 配置文件优先，
    回退到"工具与数据同目录"的仓库根（用于自托管场景）。"""
    if ksconfig is not None:
        return ksconfig.resolve_kb(explicit or None, script_file=__file__)
    return Path(__file__).resolve().parent.parent


ROOT = _resolve_root()
SKIP_DIRS = {"scripts", ".git", "__pycache__", "private"}


# ---------------- frontmatter 解析 ----------------

def parse_frontmatter(text):
    """极简 YAML frontmatter 解析（只支持本项目用到的形式）"""
    m = re.match(r"^---\s*\n(.*?)\n---\s*\n", text, re.S)
    if not m:
        return {}, text
    raw = m.group(1)
    body = text[m.end():]
    fm = {}
    current_key = None
    list_items = []

    for line in raw.split("\n"):
        if re.match(r"^\s*#", line):
            continue
        # 列表项
        li = re.match(r"^\s+-\s+(.*)$", line)
        if li and current_key:
            list_items.append(li.group(1).strip())
            continue
        # 键值
        kv = re.match(r"^([A-Za-z_][A-Za-z0-9_]*)\s*:\s*(.*)$", line)
        if kv:
            if current_key and list_items:
                fm[current_key] = list_items
                list_items = []
            current_key = kv.group(1)
            val = kv.group(2).strip()
            if val == "":
                fm[current_key] = []
            elif val.startswith("[") and val.endswith("]"):
                inner = val[1:-1].strip()
                fm[current_key] = [x.strip().strip('"\'') for x in inner.split(",") if x.strip()]
            else:
                fm[current_key] = val.strip('"\'')
    if current_key and list_items:
        fm[current_key] = list_items
    return fm, body


def parse_relations(text):
    """从 frontmatter 提取 relations（type + target）"""
    m = re.match(r"^---\s*\n(.*?)\n---\s*\n", text, re.S)
    if not m:
        return []
    raw = m.group(1)
    rels = []
    cur = {}
    in_rels = False
    for line in raw.split("\n"):
        if re.match(r"^relations\s*:", line):
            in_rels = True
            continue
        if in_rels:
            if re.match(r"^[A-Za-z_]", line) and not line.strip().startswith("-"):
                break  # 离开 relations 区块
            t = re.match(r"^\s+-\s*type\s*:\s*(\S+)", line)
            if t:
                if cur.get("type"):
                    rels.append(cur)
                cur = {"type": t.group(1)}
                continue
            tg = re.match(r"^\s+target\s*:\s*(\S+)", line)
            if tg:
                cur["target"] = tg.group(1)
    if cur.get("type"):
        rels.append(cur)
    return rels


# ---------------- 扫描 ----------------

def find_units():
    """返回所有单元目录（含 _index.md 且 type: unit）"""
    units = []
    for p in sorted(ROOT.rglob("_index.md")):
        if any(part in SKIP_DIRS for part in p.parts):
            continue
        fm, _ = parse_frontmatter(p.read_text(encoding="utf-8"))
        if fm.get("type") == "unit":
            units.append(p.parent)
    return units


def find_categories():
    """返回所有父级目录（含 _index.md 且 type: category）"""
    cats = []
    for p in sorted(ROOT.rglob("_index.md")):
        if any(part in SKIP_DIRS for part in p.parts):
            continue
        fm, _ = parse_frontmatter(p.read_text(encoding="utf-8"))
        if fm.get("type") == "category":
            cats.append(p.parent)
    return cats


def scan_notes(unit_dir):
    """扫描单元内的内容文件（排除 _index.md）"""
    notes = []
    for p in sorted(unit_dir.rglob("*.md")):
        if p.name.startswith("_"):
            continue
        fm, _ = parse_frontmatter(p.read_text(encoding="utf-8"))
        notes.append({"path": p, "fm": fm})
    return notes


def rel_path(p, base=None):
    """相对路径（用于打印）。base 必须是运行时求值——写成 `base=ROOT` 会绑死导入时的值。"""
    base = base if base is not None else ROOT
    try:
        return str(Path(p).relative_to(base)).replace("\\", "/")
    except ValueError:
        return str(p)


# ---------------- index ----------------

def _replace_section(text, heading, table):
    """把 `## <heading>` 与下一个二级标题之间的内容替换为 table。

    用"下一个 `##` 标题"作边界（而非固定标题名），
    这样对不同人自定义的 _index.md 模板都能工作。
    """
    pat = rf"(##\s*{re.escape(heading)}\s*\n)(.*?)(?=\n##\s|\Z)"
    out = re.sub(pat, lambda m: m.group(1) + "\n" + table + "\n", text, flags=re.S)
    return out


def _unit_row(u):
    """一个单元在父级表格里的一行"""
    fm, _ = parse_frontmatter((u / "_index.md").read_text(encoding="utf-8"))
    title = fm.get("title", u.name)
    kw = fm.get("keywords") or fm.get("tags") or []
    if isinstance(kw, str):
        kw = [kw]
    return f"| [`{u.name}/`](./{u.name}/_index.md) | {title} | {', '.join(str(k) for k in kw)} |"


def cmd_index(args):
    """重建三层索引：顶层分类表 → 分类层单元表 → 单元层文件表"""
    units = find_units()
    cats = find_categories()
    updated = 0

    # ---------- 1) 单元层：文件表 ----------
    for unit in units:
        idx = unit / "_index.md"
        text = idx.read_text(encoding="utf-8")
        notes = scan_notes(unit)
        if not notes:
            continue
        rows = []
        for n in notes:
            title = n["fm"].get("title", n["path"].stem)
            tags = n["fm"].get("tags", [])
            if isinstance(tags, str):
                tags = [tags]
            brief = title if title != n["path"].stem else "（无标题）"
            # 摘要：取正文第一条非空、非标题、非代码块的内容行
            _, body = parse_frontmatter(n["path"].read_text(encoding="utf-8"))
            lines = []
            in_fence = False
            for l in body.split("\n"):
                s = l.strip()
                if s.startswith("```") or s.startswith("~~~"):
                    in_fence = not in_fence
                    continue
                if in_fence or not s or s.startswith("#") or s.startswith("|"):
                    continue
                if s.startswith(">") or s.startswith("---") or s.startswith("_"):
                    continue
                lines.append(s)
            summary = lines[0][:60] if lines else ""
            rows.append(f"| [{n['path'].name}](./{n['path'].name}) | {brief} | {summary} |")

        table = "| 文件 | 主题 | 摘要 |\n|---|---|---|\n" + "\n".join(rows)
        new_text = _replace_section(text, "本单元包含", table)
        if new_text != text:
            idx.write_text(new_text, encoding="utf-8")
            updated += 1
            print(f"  ✓ {rel_path(idx)}  ({len(notes)} 篇)")

    # ---------- 2) 分类层：单元表 ----------
    for cat in sorted(cats, key=lambda x: x.name):
        subs = sorted([u for u in units if u.parent == cat], key=lambda x: x.name)
        table = ("| 单元 | 主题 | 检索词 |\n|---|---|---|\n"
                 + ("\n".join(_unit_row(u) for u in subs) if subs else "| （待添加） | | |"))
        idx = cat / "_index.md"
        text = idx.read_text(encoding="utf-8")
        new_text = _replace_section(text, "单元列表", table)
        if new_text != text:
            idx.write_text(new_text, encoding="utf-8")
            updated += 1
            print(f"  ✓ {rel_path(idx)}  ({len(subs)} 个单元)")

    # ---------- 3) 顶层：分类导航表 ----------
    ridx = ROOT / "index.md"
    if ridx.exists() and cats:
        rows = []
        for c in sorted(cats, key=lambda x: x.name):
            fm, _ = parse_frontmatter((c / "_index.md").read_text(encoding="utf-8"))
            title = fm.get("title", c.name)
            tags = fm.get("tags", [])
            if isinstance(tags, str):
                tags = [tags]
            rows.append(f"| [`{c.name}/`](./{c.name}/_index.md) | {title} "
                        f"| {', '.join(str(t) for t in tags[:5])} |")
        table = "| 分类 | 收什么 | 检索词 |\n|---|---|---|\n" + "\n".join(rows)
        text = ridx.read_text(encoding="utf-8")
        new_text = _replace_section(text, "分类导航", table)
        if new_text != text:
            ridx.write_text(new_text, encoding="utf-8")
            updated += 1
            print(f"  ✓ {rel_path(ridx)}  ({len(cats)} 个分类)")

    print(f"\n索引重建完成：{updated} 处更新")


# ---------------- map ----------------

def cmd_map(args):
    """从所有单元/笔记的 relations 生成引用地图"""
    edges = []
    units = find_units()
    for unit in units:
        idx = unit / "_index.md"
        text = idx.read_text(encoding="utf-8")
        rels = parse_relations(text)
        for r in rels:
            edges.append((rel_path(unit), r.get("type", "?"), r.get("target", "?"), "单元"))
        for n in scan_notes(unit):
            ntext = n["path"].read_text(encoding="utf-8")
            for r in parse_relations(ntext):
                src = rel_path(n["path"])
                edges.append((src, r.get("type", "?"), r.get("target", "?"), "笔记"))

    ts = datetime.now().strftime("%Y-%m-%d %H:%M")
    mermaid_lines = []
    for src, typ, tgt, kind in edges:
        s = src.replace("/", "_").replace(".md", "").replace(".", "")
        t = str(tgt).replace("/", "_").replace(".md", "").replace(".", "")
        mermaid_lines.append(f"  {s} -->|{typ}| {t}")

    table_rows = "\n".join(f"| {s} | {t} | {g} | {k} |" for s, t, g, k in edges)

    content = f"""---
title: 引用地图
type: map
tags: [map, relations, cross-reference]
generated_by: knowledge_cli map
generated_at: {ts}
---

# 引用地图（Cross-Reference Map）

> 本文件由 `knowledge_cli map` 自动生成，**请勿手动编辑**。
> 展示知识单元之间的横向关系（跨目录引用）。

## 关系类型

| 类型 | 含义 |
|---|---|
| `requires` | 前置依赖——理解本内容前建议先读目标 |
| `relates_to` | 主题相关 |
| `supersedes` | 取代——本内容是更新版 |
| `contradicts` | 结论矛盾（需人工裁决） |
| `used_in` | 被某项目/主题采用 |

## 全局关系图

```mermaid
graph LR
{chr(10).join(mermaid_lines) if mermaid_lines else '  %% 暂无关系'}
```

## 关系索引表

| 源 | 关系 | 目标 | 类型 |
|---|---|---|---|
{table_rows if edges else '| （暂无） | | | |'}

## 统计

- 关系总数：**{len(edges)}**
- 覆盖单元：**{len(set(e[0].split('/')[0] for e in edges))}** 个顶层分类

---

_最后生成：{ts}_
"""
    (ROOT / "_map.md").write_text(content, encoding="utf-8")
    print(f"✓ 引用地图已生成（{len(edges)} 条关系）")


# ---------------- health ----------------

EXPAND_THRESHOLD = 12
STALE_DAYS = 180
INBOX_DAYS = 30


def cmd_health(args):
    """生成结构健康度报告"""
    units = find_units()
    all_edges = []
    for unit in units:
        idx = unit / "_index.md"
        for r in parse_relations(idx.read_text(encoding="utf-8")):
            all_edges.append(r.get("target", ""))
        for n in scan_notes(unit):
            for r in parse_relations(n["path"].read_text(encoding="utf-8")):
                all_edges.append(r.get("target", ""))

    red, yellow, green = [], [], []
    total_files = 0
    today = datetime.now()

    for unit in units:
        notes = scan_notes(unit)
        n = len(notes)
        total_files += n
        rel = rel_path(unit)

        # 🔴 单元膨胀
        if n > EXPAND_THRESHOLD:
            red.append((rel, f"{n} 个文件，超出阈值 {EXPAND_THRESHOLD}", "建议拆分单元"))

        # 🟢 无内容的单元
        if n == 0:
            green.append((rel, "空单元", "暂无内容，可忽略或删除"))

        # 🟡 时效过期
        idx_fm, _ = parse_frontmatter((unit / "_index.md").read_text(encoding="utf-8"))
        lr = idx_fm.get("last_reviewed", "")
        if lr:
            try:
                d = datetime.strptime(str(lr), "%Y-%m-%d")
                if (today - d).days > STALE_DAYS:
                    yellow.append((rel, f"超过 {STALE_DAYS} 天未复核（{lr}）", "提示复核"))
            except ValueError:
                pass

    # 🟡 inbox 积压
    inbox = ROOT / "00-inbox"
    if inbox.exists():
        drafts = [p for p in inbox.glob("*.md") if not p.name.startswith("_")]
        for d in drafts:
            age = (today - datetime.fromtimestamp(d.stat().st_mtime)).days
            if age > INBOX_DAYS:
                yellow.append((rel_path(d), f"草稿停留 {age} 天", "处理或丢弃"))

    ts = datetime.now().strftime("%Y-%m-%d %H:%M")

    def table(items):
        if not items:
            return "| — | — | — |\n"
        return "\n".join(f"| {a} | {b} | {c} |" for a, b, c in items)

    content = f"""---
title: 结构健康度报告
type: health-report
tags: [health, monitoring, maintenance]
generated_by: knowledge_cli health
generated_at: {ts}
---

# 知识库结构健康度报告

> 本文件由 `knowledge_cli health` 自动生成，**请勿手动编辑**。

## 总览

| 指标 | 数值 |
|---|---|
| 单元总数 | {len(units)} |
| 文件总数 | {total_files} |
| 平均单元文件数 | {round(total_files / len(units), 1) if units else 0} |
| 🔴 需处理 | {len(red)} |
| 🟡 建议处理 | {len(yellow)} |
| 🟢 可选优化 | {len(green)} |

## 🔴 需处理

| 对象 | 问题 | 建议 |
|---|---|---|
{table(red)}
## 🟡 建议处理

| 对象 | 问题 | 建议 |
|---|---|---|
{table(yellow)}
## 🟢 可选优化

| 对象 | 问题 | 建议 |
|---|---|---|
{table(green)}
## 监控指标定义

| 指标 | 规则 | 严重度 |
|---|---|---|
| 单元膨胀 | 单元内文件数 > {EXPAND_THRESHOLD} | 🔴 |
| 单元复杂度 | 文件数 × 平均字数 > 阈值 | 🔴 |
| 孤儿单元 | 无 relations 且无被引用 | 🟡 |
| 时效过期 | last_reviewed 超过 {STALE_DAYS} 天 | 🟡 |
| inbox 积压 | 草稿停留 > {INBOX_DAYS} 天 | 🟡 |
| tag 漂移 | 只出现 1 次的 tag / 同义 tag 并存 | 🟢 |
| 索引失同步 | _index.md 与目录实际内容不一致 | 🟢 |
| 标题非断言 | 标题是主题词而非断言句 | 🟢 |

---

_最后生成：{ts}_
"""
    (ROOT / "_health.md").write_text(content, encoding="utf-8")
    print(f"✓ 健康度报告已生成：🔴{len(red)} 🟡{len(yellow)} 🟢{len(green)}")


# ---------------- stats ----------------

def cmd_stats(args):
    units = find_units()
    cats = find_categories()
    total = sum(len(scan_notes(u)) for u in units)
    print("知识库统计")
    print("=" * 40)
    print(f"顶层分类：{len([c for c in cats if c.parent == ROOT])}")
    print(f"单元总数：{len(units)}")
    print(f"内容文件：{total}")
    print()
    print("分类分布：")
    for cat in sorted([c for c in cats if c.parent == ROOT], key=lambda x: x.name):
        sub = [u for u in units if u.parent == cat]
        n = sum(len(scan_notes(u)) for u in sub)
        print(f"  {cat.name}/  →  {len(sub)} 单元 / {n} 篇")


# ---------------- capture ----------------

CAPTURE_TEMPLATE = """---
title: "{title}"
type: note
tags: [{tags}]
source: {source}
created: {date}
updated: {date}
confidence: low
status: draft
---

# {title}

{body}

---

_由 knowledge_cli capture 沉淀，待整理后晋升_
"""


def cmd_capture(args):
    """把一段内容沉淀到 inbox"""
    inbox = ROOT / "00-inbox"
    inbox.mkdir(exist_ok=True)
    date = datetime.now().strftime("%Y-%m-%d")
    slug = re.sub(r"[^\w\u4e00-\u9fff]+", "-", args.title).strip("-")[:40]
    target = inbox / f"{date}-{slug}.md"
    content = CAPTURE_TEMPLATE.format(
        title=args.title,
        tags=args.tag or "draft",
        source=args.source or "对话沉淀",
        date=date,
        body=args.content or "（待补充）",
    )
    target.write_text(content, encoding="utf-8")
    print(f"✓ 已沉淀到 {rel_path(target)}")
    print("  下一步：整理后移入对应单元，或运行 index/map/health 更新索引")


# ---------------- sync ----------------

def cmd_sync(args):
    """git 同步（白名单式：只提交知识内容与派生文件，防误提交）"""
    def run(cmd, check=False):
        r = subprocess.run(cmd, cwd=ROOT, capture_output=True, text=True, shell=True)
        if r.stdout.strip():
            print(r.stdout.strip())
        if r.returncode != 0 and check:
            print(r.stderr.strip(), file=sys.stderr)
        return r.returncode

    print("[1/5] git pull --rebase")
    run("git pull --rebase --autostash", check=False)

    print("[2/5] 重建索引与派生文件")
    cmd_index(args)
    cmd_map(args)
    cmd_health(args)

    print("[3/5] git add（白名单，分类来自配置）")
    dirs = ksconfig.category_dirs() if ksconfig else []
    reserved = sorted(ksconfig.RESERVED) if ksconfig else ["00-inbox", "90-archive"]
    # 白名单而非 `git add .`：防止把工作区里的其他东西误提交
    always = ["index.md", "_map.md", "_health.md", "README.md"]
    targets = always + sorted(set(list(dirs) + list(reserved)))
    # 工具与数据同目录时，顺带带上工具件
    for extra in ("scripts", "skills", "hooks", ".codebuddy-plugin"):
        if (ROOT / extra).exists():
            targets.append(extra)
    run("git add " + " ".join(targets))

    print("[4/5] git commit")
    ts = datetime.now().strftime("%Y-%m-%d %H:%M")
    run(f'git commit -m "sync: 知识库更新 {ts}"', check=False)

    if args.push:
        print("[5/5] git push")
        run("git push", check=False)
    else:
        print("[5/5] 跳过 push（如需推送加 --push）")


# ---------------- main ----------------

def main():
    global ROOT
    # --kb 对每个子命令都可用（覆盖配置里的知识库位置）
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("--kb", default="",
                        help="知识库根目录（覆盖配置；也可用 KNOWLEDGE_SEDIMENT_KB）")

    ap = argparse.ArgumentParser(description="知识库管理工具")
    sub = ap.add_subparsers(dest="cmd")

    sub.add_parser("index", parents=[common], help="重建 _index.md 的内容表格").set_defaults(func=cmd_index)
    sub.add_parser("map", parents=[common], help="生成引用地图 _map.md").set_defaults(func=cmd_map)
    sub.add_parser("health", parents=[common], help="生成健康度报告 _health.md").set_defaults(func=cmd_health)
    sub.add_parser("stats", parents=[common], help="打印统计概览").set_defaults(func=cmd_stats)

    pc = sub.add_parser("capture", parents=[common], help="沉淀内容到 inbox")
    pc.add_argument("--title", required=True, help="标题（断言式更好）")
    pc.add_argument("--content", default="", help="正文")
    pc.add_argument("--tag", default="", help="逗号分隔的标签")
    pc.add_argument("--source", default="对话沉淀", help="来源")
    pc.set_defaults(func=cmd_capture)

    ps = sub.add_parser("sync", parents=[common], help="git 同步")
    ps.add_argument("--push", action="store_true", help="同步后推送远端")
    ps.set_defaults(func=cmd_sync)

    args = ap.parse_args()
    if not args.cmd:
        ap.print_help()
        return
    if getattr(args, "kb", ""):
        ROOT = _resolve_root(args.kb)
    args.func(args)


if __name__ == "__main__":
    main()
