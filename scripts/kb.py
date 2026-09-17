#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
kb.py — knowledge-sediment 统一命令入口

一条命令完成安装 / 初始化 / 更新 / 体检，不依赖任何特定 Agent 的交互约定：

    python kb.py init                     在当前目录（或 --workdir）开启知识沉淀（创建 .knowledge/）
    python kb.py install --target X       把插件装进某个 agent
                                          （workbuddy / codebuddy / claude / codex / cursor）
    python kb.py update [--dry-run]       自更新：git pull 本工具仓库；hooks 变更时提示重启
    python kb.py doctor                   体检：配置 / 知识库 / 链接 / hook 注册是否健康

设计原则：
- 纯标准库，零第三方依赖
- skill 一律链接（junction），不复制——更新源仓库即全端生效
- 装不了的（agent 未安装 / 无 hook 能力）明确告知并降级，绝不静默失败
"""
import argparse
import json
import os
import subprocess
import sys
import time
from pathlib import Path

TOOL_ROOT = Path(__file__).resolve().parent.parent
SCRIPTS = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPTS))

import config as cfg  # noqa: E402

HOME = Path.home()
CONFIG_PATH = HOME / ".knowledge-sediment" / "config.json"
MARKER_START = "<!-- knowledge-sediment:start -->"
MARKER_END = "<!-- knowledge-sediment:end -->"


# ---------------------------------------------------------------- helpers

def git(args, cwd=None):
    return subprocess.run(
        ["git"] + args, cwd=str(cwd or TOOL_ROOT),
        capture_output=True, text=True, encoding="utf-8", errors="replace",
    )


def is_junction_to(link: Path, target: Path) -> bool:
    try:
        return os.path.realpath(link).lower() == os.path.realpath(target).lower()
    except OSError:
        return False


def make_junction(link: Path, target: Path) -> str:
    """返回 'ok' / 'exists' / 'fail'。已有真实目录时先备份再替换。"""
    if link.exists() or link.is_symlink():
        if is_junction_to(link, target):
            return "exists"
        bak = link.with_name(link.name + ".bak-" + time.strftime("%Y%m%d%H%M%S"))
        print(f"    · 已有同名目录，备份为 {bak.name}")
        os.rename(link, bak)
    link.parent.mkdir(parents=True, exist_ok=True)
    r = subprocess.run(["cmd", "/c", "mklink", "/J", str(link), str(target)],
                       capture_output=True)
    return "ok" if os.path.isdir(link) else "fail"


def backup(p: Path):
    if p.exists():
        bak = p.with_name(p.name + ".bak-" + time.strftime("%Y%m%d%H%M%S"))
        shutil_copy2 = __import__("shutil").copy2
        bak.parent.mkdir(parents=True, exist_ok=True)
        shutil_copy2(p, bak)
        print(f"    · 已备份原文件为 {bak.name}")


def rules_block(skill_md: Path) -> str:
    return (
        f"{MARKER_START}\n"
        f"## 知识沉淀（knowledge-sediment）\n\n"
        f"在本工作区产生可复用知识（方案/踩坑/方法/要点）时，读取并遵循：\n"
        f"`{skill_md}`\n\n"
        f"触发：用户说「沉淀一下：…」时，按该文件的流程执行"
        f"（做功课 → 判断归属 → 写入知识库 → 记录事件 → git sync）。\n"
        f"{MARKER_END}\n"
    )


# ---------------------------------------------------------------- targets

# 每个 agent 一份声明：skill 链接位置 + hook/规则能力。
# hook 能力为 None 时诚实降级为"规则层 + 手动触发"。
TARGETS = {
    "workbuddy": {"family": "codebuddy"},
    "codebuddy": {"family": "codebuddy"},
    "claude": {
        "home": ".claude",
        "skill_link": ".claude/skills/knowledge-sediment",
        "hooks_file": ".claude/settings.json",
        "hook_events": ["SessionStart", "Stop"],
        "note": "hook 写入为实验性（Claude Code 配置格式可能随版本变化）；装完请说一句「沉淀一下」验证",
    },
    "codex": {
        "home": ".codex",
        "skill_link": ".agents/skills/knowledge-sediment",
        "rules_append": ".codex/AGENTS.md",
        "note": "Codex 的 hooks 需 feature flag，本次只装规则层；触发靠说「沉淀一下」",
    },
    "cursor": {
        "home": ".cursor",
        "rules_file": ".cursor/rules/knowledge-sediment.mdc",
        "note": "Cursor 无 hooks，只能规则层 + 手动触发",
    },
}


def install_codebuddy_family(target: str, archive_root: str) -> int:
    """workbuddy / codebuddy 走既有安装器（市场注册 + 双 hook）。"""
    cmd = [sys.executable, str(SCRIPTS / "install_plugin.py"), "--target", target]
    if archive_root:
        cmd += ["--archive-root", archive_root]
    r = subprocess.run(cmd)
    return r.returncode


def install_generic(target: str) -> int:
    """claude / codex / cursor：junction skill + 写规则/hook，装不了就明说。"""
    spec = TARGETS[target]
    home = HOME / spec["home"]
    if not home.is_dir():
        print(f"  ✗ 未检测到 {target} 的安装目录（{home}），跳过——装好 {target} 后再运行本命令")
        return 1

    skill_md_src = TOOL_ROOT / "skills" / "knowledge-sediment" / "SKILL.md"
    print(f"  [1/2] skill 链接（更新源仓库即生效，不复制）")
    link = HOME / spec["skill_link"]
    res = make_junction(link, TOOL_ROOT / "skills" / "knowledge-sediment")
    print(f"    {'✓' if res in ('ok', 'exists') else '✗'} {link}"
          + ("（已存在）" if res == "exists" else ""))

    print(f"  [2/2] hook / 规则层")
    automatic = []
    if spec.get("hooks_file"):
        hf = HOME / spec["hooks_file"]
        backup(hf)
        try:
            data = json.loads(hf.read_text(encoding="utf-8")) if hf.exists() else {}
        except Exception:
            data = {}
        data.setdefault("hooks", {})
        root_posix = str(TOOL_ROOT).replace("\\", "/")
        cmd = f'bash "{root_posix}/hooks/run.sh" --silent'
        for ev in spec["hook_events"]:
            lst = data["hooks"].setdefault(ev, [])
            exists = any(
                isinstance(e, dict)
                and any(h.get("command") == cmd for h in e.get("hooks", []))
                for e in lst
            )
            if not exists:
                lst.append({"matcher": "", "hooks": [{"type": "command", "command": cmd}]})
        hf.parent.mkdir(parents=True, exist_ok=True)
        hf.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        automatic += spec["hook_events"]
        print(f"    ✓ 已注册 hook 事件：{', '.join(spec['hook_events'])}（实验性）")
    if spec.get("rules_append"):
        rf = HOME / spec["rules_append"]
        backup(rf)
        old = rf.read_text(encoding="utf-8") if rf.exists() else ""
        if MARKER_START in old:
            print(f"    – 规则节已存在，跳过：{rf}")
        else:
            rf.parent.mkdir(parents=True, exist_ok=True)
            rf.write_text(old.rstrip() + "\n\n" + rules_block(skill_md_src), encoding="utf-8")
            print(f"    ✓ 已追加规则节：{rf}")
    if spec.get("rules_file"):
        rf = HOME / spec["rules_file"]
        rf.parent.mkdir(parents=True, exist_ok=True)
        rf.write_text(
            "---\ndescription: 知识沉淀（knowledge-sediment）\nalwaysApply: true\n---\n"
            + rules_block(skill_md_src),
            encoding="utf-8",
        )
        print(f"    ✓ 已写入规则文件：{rf}")
    if not automatic:
        print(f"    – 该 agent 无 hook 能力：自动提醒不可用，触发靠说「沉淀一下」")

    print(f"\n  说明：{spec['note']}")
    return 0


# ---------------------------------------------------------------- commands

def cmd_init(args):
    workdir = Path(args.workdir).resolve() if args.workdir else Path.cwd()
    conf = cfg.load_config()
    kb = conf.get("kb") or (args.kb if args.kb else "")
    if not kb:
        print("✗ 未配置知识库路径（~/.knowledge-sediment/config.json 的 kb 字段），"
              "请先完成知识库初始化，或用 --kb 指定")
        return 1
    cmd = [sys.executable, str(SCRIPTS / "init_workspace.py"),
           "--workdir", str(workdir), "--kb", kb]
    print(f"在工作区 {workdir} 开启知识沉淀（知识库：{kb}）")
    r = subprocess.run(cmd)
    return r.returncode


def cmd_install(args):
    target = args.target
    if target not in TARGETS:
        print(f"✗ 未知 target：{target}（可选：{', '.join(TARGETS)}）")
        return 1
    print(f"=== 安装到 {target} ===")
    if TARGETS[target].get("family") == "codebuddy":
        conf = cfg.load_config()
        return install_codebuddy_family(target, conf.get("archive_root", ""))
    return install_generic(target)


def cmd_update(args):
    print("=== 自更新 ===")
    r = git(["rev-parse", "HEAD"])
    before = r.stdout.strip()
    if args.dry_run:
        print("（--dry-run）将执行：git pull --ff-only")
        return 0
    r = git(["pull", "--ff-only"])
    print(r.stdout.strip() or r.stderr.strip())
    if r.returncode != 0:
        print("✗ pull 失败（有本地改动？先 commit 或 stash）")
        return 1
    after = git(["rev-parse", "HEAD"]).stdout.strip()
    if before == after:
        print("已是最新版本。")
        return 0
    changed = git(["diff", "--name-only", f"{before}", f"{after}"]).stdout.split()
    if "hooks/hooks.json" in changed:
        print("\n⚠️ hooks/hooks.json 有变更——需要重启各 Agent 才会生效（脚本与 skill 已即时生效）")
    else:
        print("\n✓ 脚本与 skill 已即时生效（hooks 配置未变，无需重启）")
    return 0


def cmd_doctor(args):
    print("=== kb doctor ===")
    ok = True
    conf = cfg.load_config()
    kb = conf.get("kb", "")
    checks = [
        ("运行时配置", CONFIG_PATH.exists() or bool(conf)),
        ("知识库路径", bool(kb) and Path(kb).is_dir()),
        ("知识库是 git 仓库", bool(kb) and (Path(kb) / ".git").exists()),
        ("python 可用", bool(sys.executable)),
    ]
    for name, passed in checks:
        print(f"  {'✓' if passed else '✗'} {name}"
              + (f"：{kb}" if name.startswith("知识库路径") and passed else ""))
        ok = ok and passed

    for agent, base in [("workbuddy", HOME / ".workbuddy"),
                        ("codebuddy", HOME / ".codebuddy")]:
        skill = base / "skills" / "knowledge-sediment"
        if skill.exists():
            src = Path(os.path.realpath(skill))
            linked = "knowledge-sediment" in str(src) and src.is_dir()
            print(f"  {'✓' if linked else '⚠'} {agent} skill → {src}")
        else:
            print(f"  – {agent} skill 未安装")
    try:
        json.loads((TOOL_ROOT / "hooks" / "hooks.json").read_text(encoding="utf-8"))
        print("  ✓ hooks.json 合法")
    except Exception as e:
        print(f"  ✗ hooks.json 异常：{e}")
        ok = False
    print(f"\n结论：{'健康 ✓' if ok else '存在问题 ✗'}")
    return 0 if ok else 1


def main():
    ap = argparse.ArgumentParser(prog="kb", description="knowledge-sediment 统一命令入口")
    sub = ap.add_subparsers(dest="cmd")

    pi = sub.add_parser("init", help="在当前工作区开启知识沉淀（创建 .knowledge/）")
    pi.add_argument("--workdir", default="", help="工作区路径（默认当前目录）")
    pi.add_argument("--kb", default="", help="知识库路径（默认读配置）")
    pi.set_defaults(func=cmd_init)

    pn = sub.add_parser("install", help="把插件装进某个 agent")
    pn.add_argument("--target", required=True, choices=sorted(TARGETS))
    pn.set_defaults(func=cmd_install)

    pu = sub.add_parser("update", help="自更新工具仓库")
    pu.add_argument("--dry-run", action="store_true")
    pu.set_defaults(func=cmd_update)

    pd = sub.add_parser("doctor", help="安装/配置体检")
    pd.set_defaults(func=cmd_doctor)

    args = ap.parse_args()
    if not args.cmd:
        ap.print_help()
        return 0
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
