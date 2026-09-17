#!/usr/bin/env python3
# -*- coding: utf-8 -*-
r"""
init_workspace.py —— 在任意工作区初始化知识沉淀目录

在目标工作区创建 .knowledge/ 目录，包含：
    .knowledge/
    ├── README.md          # 沉淀说明（给人看）
    ├── inbox/             # 待整理草稿（Agent 自动沉淀的第一站）
    └── config.yaml        # 配置（指向知识库仓库路径）

并在工作区根目录的 AGENTS.md / CODEBUDDY.md 中追加一行引用（如已有文件）。

用法：
    python init_workspace.py --workdir <工作区路径> [--kb <知识库仓库路径>]
"""
import argparse
from datetime import datetime
from pathlib import Path

README = """# .knowledge · 本工作区的知识沉淀目录

> 本目录由 `knowledge-sediment` 插件创建，用于沉淀本工作区工作中产生的**可复用知识**。

## 目录说明

```
.knowledge/
├── README.md      # 本文件
├── config.yaml    # 配置（指向知识库仓库）
└── inbox/         # 待整理草稿（沉淀的第一站）
```

## 怎么用

| 想做什么 | 怎么做 |
|---|---|
| 沉淀一条知识 | 对 Agent 说"沉淀一下"，或直接往 `inbox/` 写 md |
| 整理草稿 | 说"整理知识库"，Agent 会把 inbox 内容归类到知识库对应单元 |
| 同步到知识库 | 运行知识库仓库的 `scripts/knowledge_cli.py sync --push` |

## 沉淀规范

每条内容请带 frontmatter：

```yaml
---
title: "<断言式标题>"
type: note
tags: [标签]
source: <来源>
created: YYYY-MM-DD
status: draft
---
```

**红线**：绝不沉淀密钥、密码、Token、个人隐私。

---

_创建于 {date}_
"""

CONFIG = """# 知识沉淀配置
# 本工作区的沉淀内容最终会同步到下面的知识库仓库
kb_repo: "{kb_path}"
created_at: "{date}"
"""

REF_LINE = "\n<!-- knowledge-sediment -->\n## 知识沉淀\n\n本工作区已启用知识沉淀（`.knowledge/`）。沉淀规则见 `.knowledge/README.md`。\n"

# 目标项目的 git 不应被 Agent 的沉淀工作区污染：只保留 README 与 config
KIGNORE = """# .knowledge 是 Agent 的沉淀工作区，不纳入本项目的 git
# （知识最终归档到独立的知识库仓库，而不是这里）
sessions.log
inbox/
"""


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--workdir", default=".", help="目标工作区路径")
    ap.add_argument("--kb", default="", help="知识库仓库路径（可选）")
    args = ap.parse_args()

    workdir = Path(args.workdir).resolve()
    if not workdir.exists():
        print(f"✗ 工作区不存在：{workdir}")
        return 1

    kdir = workdir / ".knowledge"
    inbox = kdir / "inbox"
    kdir.mkdir(exist_ok=True)
    inbox.mkdir(exist_ok=True)

    date = datetime.now().strftime("%Y-%m-%d %H:%M")

    readme = kdir / "README.md"
    if not readme.exists():
        readme.write_text(README.format(date=date), encoding="utf-8")
        print(f"  ✓ 创建 {readme.relative_to(workdir)}")

    (inbox / ".gitkeep").touch()

    kignore = kdir / ".gitignore"
    if not kignore.exists():
        kignore.write_text(KIGNORE, encoding="utf-8")
        print(f"  ✓ 创建 {kignore.relative_to(workdir)}（避免污染项目 git）")

    cfg = kdir / "config.yaml"
    if not cfg.exists():
        cfg.write_text(CONFIG.format(kb_path=args.kb or "(未配置)", date=date), encoding="utf-8")
        print(f"  ✓ 创建 {cfg.relative_to(workdir)}")

    # 追加引用到常驻指令文件（幂等）
    for fname in ("AGENTS.md", "CODEBUDDY.md"):
        f = workdir / fname
        if f.exists():
            text = f.read_text(encoding="utf-8")
            if "knowledge-sediment" not in text:
                f.write_text(text + REF_LINE, encoding="utf-8")
                print(f"  ✓ 追加引用到 {fname}")

    print(f"\n✓ 沉淀目录已就绪：{kdir}")
    print("  下一步：对 Agent 说'沉淀一下'即可开始沉淀知识")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
