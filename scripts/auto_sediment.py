#!/usr/bin/env python3
# -*- coding: utf-8 -*-
r"""
auto_sediment.py —— Stop hook 兜底脚本（静默优先版）

设计目标：**默默工作，不打扰主线**
  1. **默认零输出**——stdout 为空，不向对话上下文注入任何内容
  2. **可验证**——每轮写一行心跳日志，随时能确认"它真的在跑"
  3. **极克制**——确有价值时最多输出 1 行，且同一工作区同一天最多 1 次
  4. **绝不失败**——所有异常吞掉并记日志，始终 exit 0，不阻塞会话

用法（由 hook 调用，通常不需要手动运行）：
    python auto_sediment.py --mode remind     # hook 模式：静默 + 心跳
    python auto_sediment.py --mode check      # 人工排查：打印完整状态
    python auto_sediment.py --mode log        # 打印最近心跳日志

工作区解析顺序：
    --workdir 参数 > $CODEBUDDY_PROJECT_DIR > $CLAUDE_PROJECT_DIR > $KNOWLEDGE_WORKDIR > 当前目录

开关：
    KNOWLEDGE_SEDIMENT_ENABLE=0     关闭本插件（默认开启）
    KNOWLEDGE_SEDIMENT_VERBOSE=1    把心跳也打到 stdout（仅调试）
"""
import argparse
import json
import os
import sys
from datetime import datetime
from pathlib import Path

# ---------------- 常量 ----------------

HOME = Path(os.path.expanduser("~"))
LOG_DIR = HOME / ".workbuddy" / "logs"
LOG_FILE = LOG_DIR / "knowledge-sediment.log"
STATE_FILE = HOME / ".workbuddy" / "knowledge-sediment-state.json"
LOG_MAX_LINES = 3000

SEDIMENT_DIR = ".knowledge"
WATCH_EXT = {".md", ".py", ".java", ".kt", ".kts", ".swift", ".ts", ".tsx", ".js",
             ".gd", ".sql", ".json", ".yaml", ".yml", ".xml", ".gradle", ".rs", ".go"}
IGNORE_DIRS = {".git", "node_modules", "__pycache__", ".venv", "venv", "dist", "build",
               ".idea", ".vscode", ".gradle", ".knowledge", "target", ".next", "out"}
RECENT_MINUTES = 30
# 变更文件数量达到这个值，才认为"这一轮确实产出了东西"
CHANGE_HINT_THRESHOLD = 5


# ---------------- 基础设施（全部安全兜底） ----------------

def rotate_log():
    """日志超长时截断，避免无限增长"""
    try:
        if not LOG_FILE.exists():
            return
        with LOG_FILE.open("r", encoding="utf-8", errors="replace") as f:
            lines = f.readlines()
        if len(lines) > LOG_MAX_LINES:
            keep = lines[-LOG_MAX_LINES // 2:]
            LOG_FILE.write_text("".join(keep), encoding="utf-8")
    except Exception:
        pass


def write_log(line: str):
    """写心跳日志（失败也绝不抛出）"""
    try:
        LOG_DIR.mkdir(parents=True, exist_ok=True)
        rotate_log()
        with LOG_FILE.open("a", encoding="utf-8") as f:
            f.write(line + "\n")
    except Exception:
        pass


def load_state() -> dict:
    try:
        if STATE_FILE.exists():
            return json.loads(STATE_FILE.read_text(encoding="utf-8"))
    except Exception:
        pass
    return {}


def save_state(state: dict):
    try:
        STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
        STATE_FILE.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")
    except Exception:
        pass


def resolve_workdir(cli_value: str) -> Path:
    for candidate in (
        cli_value,
        os.environ.get("CODEBUDDY_PROJECT_DIR", ""),
        os.environ.get("CLAUDE_PROJECT_DIR", ""),
        os.environ.get("KNOWLEDGE_WORKDIR", ""),
    ):
        if candidate and candidate.strip():
            p = Path(candidate.strip().strip('"')).expanduser()
            try:
                if p.is_dir():
                    return p.resolve()
            except Exception:
                continue
    try:
        return Path.cwd().resolve()
    except Exception:
        return Path(".")


def count_recent_changes(workdir: Path):
    """统计最近 N 分钟内修改过的、可能含知识的文件"""
    now = datetime.now().timestamp()
    cutoff = now - RECENT_MINUTES * 60
    changed = []
    try:
        for root, dirs, files in os.walk(workdir):
            dirs[:] = [d for d in dirs if d not in IGNORE_DIRS and not d.startswith(".git")]
            # 防止在大目录里耗时过久
            if len(changed) > 400:
                break
            for f in files:
                p = Path(root) / f
                if p.suffix.lower() not in WATCH_EXT:
                    continue
                try:
                    if p.stat().st_mtime > cutoff:
                        changed.append(str(p.relative_to(workdir)).replace("\\", "/"))
                except OSError:
                    continue
    except Exception:
        pass
    return changed


def kb_root_from_config(workdir: Path) -> str:
    """从 .knowledge/config.yaml 读取 kb_repo"""
    cfg = workdir / SEDIMENT_DIR / "config.yaml"
    try:
        if cfg.exists():
            for line in cfg.read_text(encoding="utf-8").split("\n"):
                if line.strip().startswith("kb_repo:"):
                    v = line.split(":", 1)[1].strip().strip('"').strip("'")
                    return "" if v.startswith("(") else v
    except Exception:
        pass
    return ""


# ---------------- 主逻辑 ----------------

def collect(workdir: Path) -> dict:
    """收集本轮状态（只读，零副作用）"""
    kdir = workdir / SEDIMENT_DIR
    inbox = kdir / "inbox"
    drafts = []
    try:
        if inbox.is_dir():
            drafts = [p.name for p in inbox.glob("*.md") if not p.name.startswith("_")]
    except Exception:
        pass

    changed = count_recent_changes(workdir)
    is_kb_repo = (workdir / "_map.md").exists() and (workdir / "00-inbox").is_dir()

    return {
        "workdir": str(workdir),
        "initialized": kdir.is_dir(),
        "is_kb_repo": is_kb_repo,
        "drafts": drafts,
        "changed": changed,
        "kb_root": kb_root_from_config(workdir) or os.environ.get("KNOWLEDGE_KB", ""),
    }


def quiet_work(info: dict):
    """插件的"默默工作"——append-only 记录，不写进任何 git 仓库"""
    # 1) 若工作区已初始化，把本轮活动追加到 .knowledge/sessions.log（本地留痕，不参与 git）
    if info["initialized"] and info["changed"]:
        try:
            slog = Path(info["workdir"]) / SEDIMENT_DIR / "sessions.log"
            preview = ", ".join(info["changed"][:8])
            with slog.open("a", encoding="utf-8") as f:
                f.write(f"{datetime.now():%Y-%m-%d %H:%M:%S}\t{len(info['changed'])} files\t{preview}\n")
        except Exception:
            pass


def decide_hint(info: dict) -> str:
    """决定是否输出提示（极克制：同工作区同一天最多 1 条）"""
    state = load_state()
    key = str(info["workdir"]).lower()
    today = datetime.now().strftime("%Y-%m-%d")
    rec = state.get(key, {})

    if rec.get("last_hint_date") == today:
        return ""          # 今天已经提示过，闭嘴

    hint = ""
    if info["is_kb_repo"]:
        # 知识库仓库自身：只提示待整理草稿
        if info["drafts"]:
            n = len(info["drafts"])
            hint = f"[knowledge-sediment] inbox 有 {n} 条草稿待整理（说\"整理知识库\"可归类）。"
    elif not info["initialized"]:
        if len(info["changed"]) >= CHANGE_HINT_THRESHOLD:
            hint = ("[knowledge-sediment] 本工作区尚未初始化知识沉淀目录"
                    f"（本轮改动 {len(info['changed'])} 个文件）。如需启用，说\"初始化知识沉淀\"。")
    else:
        if info["drafts"]:
            n = len(info["drafts"])
            hint = (f"[knowledge-sediment] .knowledge/inbox 有 {n} 条草稿。"
                    "若有可复用知识，说\"沉淀一下\"归档到知识库。")
        elif len(info["changed"]) >= CHANGE_HINT_THRESHOLD:
            hint = (f"[knowledge-sediment] 本轮改动了 {len(info['changed'])} 个文件；"
                    "若有可复用结论/踩坑，说\"沉淀一下\"即可归档。")

    if hint:
        rec["last_hint_date"] = today
        rec["last_hint"] = hint
        state[key] = rec
        save_state(state)
    return hint


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--workdir", default="", help="工作区路径（省略则自动推断）")
    ap.add_argument("--kb", default="",
                    help="知识库根目录（记录到心跳便于诊断；也可用 KNOWLEDGE_SEDIMENT_KB）")
    ap.add_argument("--mode", default="remind", choices=["remind", "check", "log"])
    ap.add_argument("--emit", default="text", choices=["text", "json"],
                    help="提示的输出形态：text=裸文本；json=包成 hook 信封（供 UserPromptSubmit 注入上下文）")
    ap.add_argument("--event", default="UserPromptSubmit",
                    help="--emit json 时写进信封的 hookEventName")
    args = ap.parse_args()

    # --mode log：打印最近心跳
    if args.mode == "log":
        try:
            if LOG_FILE.exists():
                lines = LOG_FILE.read_text(encoding="utf-8", errors="replace").split("\n")
                print(f"日志文件：{LOG_FILE}")
                print(f"总行数：{len([l for l in lines if l.strip()])}")
                print("最近 15 条：")
                for l in [x for x in lines if x.strip()][-15:]:
                    print("  " + l)
            else:
                print(f"（暂无日志）{LOG_FILE}")
        except Exception as e:
            print(f"读取日志失败：{e}")
        return 0

    # 开关
    if os.environ.get("KNOWLEDGE_SEDIMENT_ENABLE", "1") == "0":
        return 0

    try:
        workdir = resolve_workdir(args.workdir)
        info = collect(workdir)
    except Exception as e:
        write_log(f"{datetime.now():%Y-%m-%d %H:%M:%S}\tERROR\t{e}")
        return 0

    # 心跳日志（这是"它确实在工作"的证据）
    write_log(
        f"{datetime.now():%Y-%m-%d %H:%M:%S}\t"
        f"workdir={info['workdir']}\t"
        f"initialized={info['initialized']}\t"
        f"kb_repo={info['is_kb_repo']}\t"
        f"changed={len(info['changed'])}\t"
        f"drafts={len(info['drafts'])}"
        + (f"\tkb={args.kb}" if args.kb else "")
    )

    # 默默工作
    try:
        quiet_work(info)
    except Exception:
        pass

    if args.mode == "check":
        print("=== knowledge-sediment 状态 ===")
        for k, v in info.items():
            print(f"  {k}: {v}")
        print(f"  日志: {LOG_FILE}")
        hint = decide_hint(info)
        print(f"  本轮是否会提示: {hint or '(静默)'}")
        return 0

    # remind 模式：绝大多数情况下输出为空
    hint = decide_hint(info)
    if hint:
        if args.emit == "json":
            # ★ 关键：只有 UserPromptSubmit（及 SessionStart）这类事件支持
            #   hookSpecificOutput.additionalContext 注入上下文。
            #   FinalStop 的输出会被平台丢弃，所以"提醒"必须走这里。
            print(json.dumps({
                "suppressOutput": True,
                "hookSpecificOutput": {
                    "hookEventName": args.event,
                    "additionalContext": hint,
                },
            }, ensure_ascii=False))
        else:
            print(hint)
    if os.environ.get("KNOWLEDGE_SEDIMENT_VERBOSE") == "1":
        print(f"[verbose] {info}")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except SystemExit:
        raise
    except Exception:
        # 兜底：hook 绝不能因为我们的 bug 而失败
        raise SystemExit(0)
