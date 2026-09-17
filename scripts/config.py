#!/usr/bin/env python3
# -*- coding: utf-8 -*-
r"""knowledge-sediment · 运行时配置（共享模块）

所有脚本通过它回答两个问题，从而**不依赖任何写死的路径或分类名**：

  1. 知识库在哪？
  2. 知识库的分类体系是什么？

从而让同一份工具能服务任何人的知识库——包括分类完全不同的人
（做前端的人不会关心 MySQL，做数据的人不会关心 CSS 布局）。

## 配置查找顺序（先找到先用）

1. 环境变量 `KNOWLEDGE_SEDIMENT_CONFIG` 指向的文件
2. `~/.knowledge-sediment/config.json`      ← 标准位置（与 Agent 无关，换工具不用重配）
3. `~/.workbuddy/knowledge-sediment.json`   ← 兼容旧版

## 配置结构

```json
{
  "kb": "C:/Users/you/my-knowledge",
  "python": "C:/path/to/python.exe",
  "taxonomy": {
    "version": 1,
    "categories": [
      {
        "id": "10-ai-engineering",
        "title": "AI 工程",
        "keywords": ["agent", "prompt", "rag"],
        "units": [
          {
            "id": "11-agent-architecture",
            "title": "Agent 架构",
            "keywords": ["multi-agent", "工作流"],
            "summary": "一句话说明这个单元收什么"
          }
        ]
      }
    ]
  }
}
```

`taxonomy` 由初始化流程（`INIT.md`）根据使用者投喂的素材生成——
不是预置模板，所以每个人的分类可以完全不同。
"""
import json
import os
import re
from pathlib import Path

HOME = Path(os.path.expanduser("~"))
KNOWLEDGE_DIR = "knowledge-base"  # 知识库根目录的默认名（可用 --kb 覆盖）

# 知识库内的保留目录（不是分类，扫描时应跳过）
RESERVED = {"00-inbox", "99-journal", "private", "90-archive"}

# 反推分类时要跳过的目录
_SKIP_TOP = {"scripts", "skills", "hooks", "node_modules", "__pycache__", "private",
             ".git", ".codebuddy-plugin", ".knowledge", ".github", "template"}


def config_paths():
    """返回候选配置路径（按优先级）"""
    out = []
    env = os.environ.get("KNOWLEDGE_SEDIMENT_CONFIG", "").strip()
    if env:
        out.append(Path(env).expanduser())
    out.append(HOME / ".knowledge-sediment" / "config.json")
    out.append(HOME / ".workbuddy" / "knowledge-sediment.json")
    return out


def find_config():
    """返回第一个存在的配置文件路径；都不存在返回标准位置（供写入用）"""
    for p in config_paths():
        if p.is_file():
            return p
    return config_paths()[1] if len(config_paths()) > 1 else config_paths()[-1]


def load_config():
    """读取配置；任何异常都返回空 dict（永不阻塞调用方）"""
    p = find_config()
    try:
        if p.is_file():
            return json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        pass
    return {}


def save_config(cfg, path=None):
    """写入配置（默认写标准位置），返回实际路径"""
    p = Path(path) if path else config_paths()[0]
    if not path:
        # 无环境变量时用标准位置
        p = HOME / ".knowledge-sediment" / "config.json"
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(cfg, ensure_ascii=False, indent=2), encoding="utf-8")
    return p


def resolve_kb(explicit=None, script_file=None):
    """定位知识库根目录。

    优先级：
      1. 显式传入（命令行 --kb）
      2. 环境变量 KNOWLEDGE_SEDIMENT_KB
      3. 配置文件里的 kb 字段
      4. 回退：脚本所在仓库根目录（适用于"工具与数据同目录"的用法）
    """
    if explicit:
        return Path(explicit).expanduser().resolve()
    env = os.environ.get("KNOWLEDGE_SEDIMENT_KB", "").strip()
    if env:
        return Path(env).expanduser().resolve()
    cfg_kb = (load_config().get("kb") or "").strip()
    if cfg_kb:
        return Path(cfg_kb).expanduser().resolve()
    if script_file:
        p = Path(script_file).resolve()
        if p.name == "scripts" or p.parent.name == "scripts":
            return p.parent.parent if p.parent.name == "scripts" else p.parent
        return p.parent
    return Path.cwd()


def categories(cfg=None, auto_scan=True):
    """返回分类列表（每项含 id/title/keywords/units）

    优先用配置里的 taxonomy；没有则从知识库目录结构**反推**——
    这样已有知识库的人不需要手写一份配置才能用工具。
    """
    cfg = cfg if cfg is not None else load_config()
    tax = cfg.get("taxonomy") or {}
    cats = [c for c in (tax.get("categories") or []) if isinstance(c, dict) and c.get("id")]
    if cats:
        return cats
    if auto_scan:
        return scan_taxonomy(resolve_kb())
    return []


def _fm_meta(path):
    """从 _index.md 的 frontmatter 取 title / tags / summary（不依赖 pyyaml）"""
    meta = {}
    try:
        if not path.is_file():
            return meta
        raw_all = path.read_text(encoding="utf-8", errors="replace")
    except Exception:
        return meta
    m = re.match(r"^---\s*\n(.*?)\n---", raw_all, re.S)
    if not m:
        return meta
    raw = m.group(1)
    for key in ("title", "summary"):
        km = re.search(rf"^{key}\s*:\s*(.+)$", raw, re.M)
        if km:
            meta[key] = km.group(1).strip().strip('"').strip("'")
    tm = re.search(r"^tags\s*:\s*\[(.*?)\]", raw, re.M | re.S)
    if tm:
        meta["tags"] = [t.strip().strip('"').strip("'")
                        for t in tm.group(1).split(",") if t.strip()]
    else:
        block = re.search(r"^tags\s*:\s*\n((?:\s+-\s+.+\n?)+)", raw, re.M)
        if block:
            meta["tags"] = [ln.strip().lstrip("- ").strip().strip('"').strip("'")
                            for ln in block.group(1).strip().split("\n") if ln.strip()]
    return meta


def scan_taxonomy(kb):
    """从知识库目录结构反推分类体系。

    约定（由初始化流程生成，人也可以手工建）：
        知识库/<分类目录>/_index.md
        知识库/<分类目录>/<单元目录>/_index.md
    """
    out = []
    if not kb or not Path(kb).is_dir():
        return out
    for d in sorted(Path(kb).iterdir()):
        if not d.is_dir() or d.name.startswith(".") or d.name in _SKIP_TOP:
            continue
        cm = _fm_meta(d / "_index.md")
        units = []
        for u in sorted(d.iterdir()):
            if not u.is_dir() or u.name.startswith(".") or u.name in _SKIP_TOP:
                continue
            um = _fm_meta(u / "_index.md")
            units.append({
                "id": u.name,
                "title": um.get("title", u.name),
                "keywords": um.get("tags", []),
                "summary": um.get("summary", ""),
            })
        out.append({
            "id": d.name,
            "title": cm.get("title", d.name),
            "keywords": cm.get("tags", []),
            "units": units,
        })
    return out


def category_dirs(cfg=None):
    """返回顶层分类目录名列表（用于 git add 白名单等）"""
    return [c["id"] for c in categories(cfg)]


def all_units(cfg=None):
    """返回 [(分类id, 单元id, 单元title, keywords), ...]"""
    out = []
    for c in categories(cfg):
        for u in (c.get("units") or []):
            if isinstance(u, dict) and u.get("id"):
                out.append((c["id"], u["id"], u.get("title", ""), u.get("keywords") or []))
    return out


def has_taxonomy(cfg=None):
    return bool(categories(cfg))


if __name__ == "__main__":
    cfg = load_config()
    print(f"配置文件: {find_config()}")
    print(f"  存在   : {find_config().is_file()}")
    print(f"知识库 : {resolve_kb()}")
    cats = categories(cfg)
    print(f"分类数 : {len(cats)}")
    for c in cats:
        n = len(c.get("units") or [])
        print(f"  {c['id']}  {c.get('title','')}  ({n} 单元)")
