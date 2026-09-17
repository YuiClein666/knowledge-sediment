#!/usr/bin/env python3
# -*- coding: utf-8 -*-
r"""
install_plugin.py —— 把 knowledge-sediment 插件安装到 Agent

安装内容（分两路，互为补充）：
  A. **Skill**（立即生效，无需重启）
     复制到 <base>/skills/knowledge-sediment/  → 任何工作区都能说"沉淀一下"
  B. **Plugin + Hooks**（需重启 Agent 生效）
     1) 建本地插件市场 <base>/plugins/cache/personal-local/
     2) 在市场里挂载本仓库为插件（Windows 用目录联接，其余用软链/复制）
     3) 注册市场到 known_marketplaces.json（先备份）
     4) 在 settings.json 的 enabledPlugins 打开本插件（先备份）

用法：
    python install_plugin.py --target workbuddy          # 默认
    python install_plugin.py --target codebuddy
    python install_plugin.py --mode copy                 # 不用链接，直接复制
    python install_plugin.py --uninstall                 # 卸载（移除注册，保留数据）
    python install_plugin.py --verify                    # 只检查安装状态
"""
import argparse
import json
import os
import shutil
import subprocess
import sys
from datetime import datetime
from pathlib import Path

HOME = Path(os.path.expanduser("~"))
PLUGIN_NAME = "knowledge-sediment"
MARKETPLACE = "personal-local"

TARGETS = {
    "workbuddy": HOME / ".workbuddy",
    "codebuddy": HOME / ".codebuddy",
}


def find_plugin_root() -> Path:
    """本脚本位于 <plugin_root>/scripts/install_plugin.py"""
    return Path(__file__).resolve().parent.parent


def read_version(root: Path) -> str:
    try:
        d = json.loads((root / ".codebuddy-plugin" / "plugin.json").read_text(encoding="utf-8"))
        return d.get("version", "0.0.0")
    except Exception:
        return "0.0.0"


def load_json(p: Path, default):
    try:
        if p.exists():
            return json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        pass
    return default


def save_json(p: Path, data):
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def backup(p: Path):
    if p.exists():
        b = p.with_suffix(p.suffix + ".bak-knowledge-sediment")
        try:
            shutil.copy2(p, b)
            print(f"  · 已备份 {p.name} → {b.name}")
        except Exception as e:
            print(f"  ! 备份失败（继续）：{e}")


def make_link(link: Path, target: Path) -> bool:
    """优先建立目录联接/软链，失败返回 False"""
    if link.exists():
        return True
    try:
        if os.name == "nt":
            r = subprocess.run(["cmd", "/c", "mklink", "/J", str(link), str(target)],
                               capture_output=True, text=True,
                               encoding="utf-8", errors="replace")
            if r.returncode == 0:
                print(f"  · 已创建目录联接：{link} → {target}")
                return True
            print(f"  ! 联接失败：{(r.stderr or r.stdout).strip()}")
        else:
            os.symlink(target, link, target_is_directory=True)
            print(f"  · 已创建软链接：{link} → {target}")
            return True
    except Exception as e:
        print(f"  ! 链接异常：{e}")
    return False


def install_skill(root: Path, base: Path):
    """A 路：装成 user-level skill（立即生效）"""
    src = root / "skills" / PLUGIN_NAME
    dst = base / "skills" / PLUGIN_NAME
    if not src.is_dir():
        print(f"  ! 找不到 skill 源目录：{src}")
        return
    dst.mkdir(parents=True, exist_ok=True)
    for item in src.rglob("*"):
        if item.is_dir():
            continue
        rel = item.relative_to(src)
        out = dst / rel
        out.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(item, out)
    print(f"  ✓ skill 已安装：{dst}")


def install_plugin(root: Path, base: Path, version: str, use_link: bool,
                   extra: list | None = None) -> list:
    """B 路：本地市场 + 插件挂载

    extra: [(name, root, version, description), ...] 额外要注册的插件
           （例如私有档案库里的 personal-kb-guard）。
           放进**同一个市场** → 一次重启即可全部生效（避免为每个插件反复重启）。

    返回已启用的插件引用名列表。
    """
    mkt = base / "plugins" / "cache" / MARKETPLACE
    mkt.mkdir(parents=True, exist_ok=True)

    specs = [(PLUGIN_NAME, root, version,
              "个人知识沉淀——在任意工作区自动沉淀可复用知识并同步到知识库")]
    specs += list(extra or [])

    # 1) 市场清单
    manifest = {
        "name": MARKETPLACE,
        "description": "本地个人插件市场（自建）",
        "owner": {"name": "local"},
        "metadata": {"version": "1.0.0"},
        "plugins": [
            {
                "name": name,
                "description": desc,
                "source": f"./{name}/{ver}",
                "version": ver,
                "author": {"name": "local"},
                "category": "知识管理",
            }
            for name, _r, ver, desc in specs
        ],
    }
    save_json(mkt / ".codebuddy-plugin" / "marketplace.json", manifest)
    print(f"  ✓ 市场清单（{len(specs)} 个插件）：{mkt / '.codebuddy-plugin' / 'marketplace.json'}")

    # 2) 逐个挂载
    for name, proot, ver, _desc in specs:
        link = mkt / name / ver
        link.parent.mkdir(parents=True, exist_ok=True)
        if use_link and make_link(link, proot):
            print(f"  ✓ 插件挂载：{name} → {proot}")
            continue
        dst = mkt / name / ver
        if dst.exists() and not dst.is_symlink():
            shutil.rmtree(dst, ignore_errors=True)
        ignore = shutil.ignore_patterns(".git", "__pycache__", "*.pyc")
        shutil.copytree(proot, dst, ignore=ignore, dirs_exist_ok=True)
        print(f"  · 已复制插件 {name} → {dst}")

    # 3) 注册市场
    km_path = base / "plugins" / "known_marketplaces.json"
    km = load_json(km_path, {})
    if MARKETPLACE not in km:
        backup(km_path)
    km[MARKETPLACE] = {
        "type": "directory",
        "source": {"source": "directory", "path": str(mkt)},
        "installLocation": str(mkt),
        "autoUpdate": False,
        "description": "本地个人插件市场（自建）",
    }
    save_json(km_path, km)
    print(f"  ✓ 已注册市场 '{MARKETPLACE}' 到 known_marketplaces.json")

    # 4) 启用插件
    st_path = base / "settings.json"
    st = load_json(st_path, {})
    refs = []
    for name, _p, _v, _d in specs:
        ref = f"{name}@{MARKETPLACE}"
        if st.get("enabledPlugins", {}).get(ref) is not True:
            backup(st_path)
        st.setdefault("enabledPlugins", {})[ref] = True
        refs.append(ref)
    save_json(st_path, st)
    for ref in refs:
        print(f"  ✓ 已在 settings.json 启用 '{ref}'")
    return refs


def uninstall(base: Path, purge: bool = False):
    km_path = base / "plugins" / "known_marketplaces.json"
    km = load_json(km_path, {})
    if MARKETPLACE in km:
        backup(km_path)
        km.pop(MARKETPLACE, None)
        save_json(km_path, km)
        print(f"  ✓ 已移除市场注册 '{MARKETPLACE}'")

    st_path = base / "settings.json"
    st = load_json(st_path, {})
    ref = f"{PLUGIN_NAME}@{MARKETPLACE}"
    if ref in st.get("enabledPlugins", {}):
        backup(st_path)
        st["enabledPlugins"].pop(ref, None)
        save_json(st_path, st)
        print(f"  ✓ 已取消启用 '{ref}'")

    sk = base / "skills" / PLUGIN_NAME
    if purge and sk.exists():
        shutil.rmtree(sk, ignore_errors=True)
        print(f"  ✓ 已删除 skill：{sk}")
    else:
        print(f"  · skill 保留：{sk}（如需删除加 --purge）")


def find_python() -> str:
    """探测可用的 Python 解释器（hook 环境不保证 PATH 里有 python）"""
    cands = [
        HOME / ".workbuddy" / "binaries" / "python" / "envs" / "default" / "Scripts" / "python.exe",
        HOME / ".workbuddy" / "binaries" / "python" / "envs" / "default" / "bin" / "python",
    ]
    for p in cands:
        if p.exists():
            return str(p)

    ver = HOME / ".workbuddy" / "binaries" / "python" / "versions"
    if ver.is_dir():
        for d in sorted([x for x in ver.iterdir() if x.is_dir()],
                        key=lambda x: x.name, reverse=True):
            for p in (d / "python.exe", d / "bin" / "python"):
                if p.exists():
                    return str(p)

    for name in ("python", "python3", "py"):
        w = shutil.which(name)
        if w:
            return w
    return ""


def find_archive_root(base: Path) -> Path | None:
    """找出私有档案库插件（personal-kb-guard）的位置

    ★ 刻意**不硬编码任何个人路径**——只读运行时配置里的 archive_root，
      由安装时用 --archive-root 写入。这样本文件可以安全地公开。
    """
    cfg = load_json(base / "knowledge-sediment.json", {})
    cand = cfg.get("archive_root") or ""
    if not cand:
        return None
    p = Path(cand)
    if (p / ".codebuddy-plugin" / "plugin.json").exists():
        return p
    return None


def write_runtime_config(base: Path, kb_root: Path, archive_root: Path | None = None) -> Path:
    """写入运行时配置，供 hook 启动器确定性地找到 python / 知识库 / 分类体系

    写两处：
      · ~/.knowledge-sediment/config.json  ← ★ 标准位置（与 Agent 无关，换工具不用重配）
      · <base>/knowledge-sediment.json     ← 兼容副本（老版本启动器会读这里）
    """
    cfg = load_json(base / "knowledge-sediment.json", {})
    cfg["python"] = find_python()
    cfg["kb"] = str(kb_root)
    if archive_root:
        cfg["archive_root"] = str(archive_root)

    # 顺带把分类体系写进配置：供 Agent 检索定位、以及 sync 的 git 白名单使用。
    # 从知识库目录反推（读各层 _index.md 的 frontmatter），不要求人先手写一份。
    try:
        sys.path.insert(0, str(Path(__file__).resolve().parent))
        import config as ksconfig
        tax = ksconfig.scan_taxonomy(kb_root)
        if tax:
            cfg["taxonomy"] = {"version": 1, "categories": tax}
    except Exception:
        pass

    cfg["updated_at"] = datetime.now().isoformat(timespec="seconds")

    std = HOME / ".knowledge-sediment" / "config.json"
    std.parent.mkdir(parents=True, exist_ok=True)
    save_json(std, cfg)
    save_json(base / "knowledge-sediment.json", cfg)

    print(f"  ✓ 运行时配置（标准位置）：{std}")
    print(f"  ✓ 兼容副本：{base / 'knowledge-sediment.json'}")
    print(f"      python   = {cfg['python'] or '（未找到！hook 将静默跳过）'}")
    print(f"      kb       = {cfg['kb']}")
    n_cat = len((cfg.get("taxonomy") or {}).get("categories") or [])
    print(f"      taxonomy = {n_cat} 个分类" if n_cat else "      taxonomy = （未写入，将在首次索引时反推）")
    if cfg.get("archive_root"):
        print(f"      archive_root = {cfg['archive_root']}")
    return std


def verify_launchers(root: Path, base: Path):
    """按平台的方式实际执行 hook 启动器

    只测 bash 入口——平台把 ${CODEBUDDY_PLUGIN_ROOT} 展开成 POSIX 路径，
    PowerShell 的 -File 会拒绝该路径（详见 hooks/README.md 第三节）。

    ★ 关键断言不只看 exit 码：脚本路径写错时同样是 exit 0 + 零输出，
      所以必须同时确认心跳日志增长，否则会把"静默失败"误判为成功。
    """
    print("\n[D] hook 启动器实测（模拟平台调用）")
    env = dict(os.environ)
    env["CODEBUDDY_PLUGIN_ROOT"] = str(root).replace("\\", "/")
    env.pop("KNOWLEDGE_SEDIMENT_ENABLE", None)

    log_file = HOME / ".workbuddy" / "logs" / "knowledge-sediment.log"

    def heartbeat_lines() -> int:
        try:
            text = log_file.read_text(encoding="utf-8", errors="replace")
            return len([l for l in text.split("\n") if l.strip()])
        except Exception:
            return 0

    trials = [
        ("FinalStop 模式（静默，仅心跳）", ["bash", str(root / "hooks" / "run.sh"), "--silent"]),
        ("UserPromptSubmit 模式（可输出 JSON 信封）",
         ["bash", str(root / "hooks" / "run.sh"), "--emit-json"]),
    ]
    for label, cmd in trials:
        before = heartbeat_lines()
        try:
            r = subprocess.run(cmd, capture_output=True, text=True, env=env,
                               encoding="utf-8", errors="replace", timeout=90)
            out = (r.stdout or "").strip()
            after = heartbeat_lines()
            grew = after > before
            ok = (r.returncode == 0) and grew
            note = "（脚本确实执行）" if grew else "（★脚本未执行！）"
            print(f"  {'✓' if ok else '✗'} {label}：exit={r.returncode}，"
                  f"stdout={len(out)} 字节，心跳 {before}→{after} {note}")
            if out:
                print(f"      输出：{out[:200]}")
            if r.stderr and r.stderr.strip():
                print(f"      stderr：{r.stderr.strip()[:300]}")
        except Exception as e:
            print(f"  ✗ {label}：执行异常 {e}")

    err_log = HOME / ".workbuddy" / "logs" / "knowledge-sediment-hook.err"
    if err_log.exists() and err_log.stat().st_size > 0:
        print(f"  ! 诊断日志非空，请检查：{err_log}")


def verify(base: Path, plugin_names: list | None = None):
    names = [PLUGIN_NAME] + list(plugin_names or [])
    print("=== 安装状态检查 ===")
    km = load_json(base / "plugins" / "known_marketplaces.json", {})
    st = load_json(base / "settings.json", {})
    mkt = base / "plugins" / "cache" / MARKETPLACE

    ok = True
    checks = [
        ("市场已注册", MARKETPLACE in km),
        ("市场目录存在", mkt.is_dir()),
        ("市场清单存在", (mkt / ".codebuddy-plugin" / "marketplace.json").exists()),
        ("skill 已安装", (base / "skills" / PLUGIN_NAME / "SKILL.md").exists()),
    ]
    for label, passed in checks:
        print(f"  {'✓' if passed else '✗'} {label}")
        ok = ok and passed

    for name in names:
        ref = f"{name}@{MARKETPLACE}"
        enabled = st.get("enabledPlugins", {}).get(ref) is True
        dirs = [p for p in (mkt / name).glob("*") if p.is_dir()] if (mkt / name).is_dir() else []
        hooks = (dirs[0] / "hooks" / "hooks.json") if dirs else None
        good = enabled and hooks is not None and hooks.exists()
        print(f"  {'✓' if good else '✗'} 插件 {name}：启用={enabled}，"
              f"hook 配置={'有' if (hooks and hooks.exists()) else '缺失'}")
        ok = ok and good

    print(f"\n结论：{'安装完整 ✓' if ok else '安装不完整 ✗'}")
    return ok


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--target", default="workbuddy", choices=list(TARGETS.keys()))
    ap.add_argument("--mode", default="link", choices=["link", "copy"])
    ap.add_argument("--uninstall", action="store_true")
    ap.add_argument("--purge", action="store_true", help="卸载时一并删除 skill")
    ap.add_argument("--verify", action="store_true")
    ap.add_argument("--kb", default="",
                    help="知识库根目录（默认假定与工具同目录；两者分开部署时请指定）")
    ap.add_argument("--archive-root", default="",
                    help="[可选扩展位] 另一个插件仓库路径（含 .codebuddy-plugin/plugin.json）"
                         "——提供则一并注册到同一市场，共用一次重启")
    args = ap.parse_args()

    root = find_plugin_root()
    base = TARGETS[args.target]
    version = read_version(root)

    print(f"插件根目录：{root}")
    print(f"目标 Agent ：{args.target}  ({base})")
    print(f"插件版本   ：{version}\n")

    if not (root / ".codebuddy-plugin" / "plugin.json").exists():
        print("✗ 未找到 .codebuddy-plugin/plugin.json，本目录不是插件根目录")
        return 1

    if args.verify:
        ar = find_archive_root(base)
        return 0 if verify(base, ["personal-kb-guard"] if ar else []) else 1

    if args.uninstall:
        uninstall(base, purge=args.purge)
        print("\n完成。重启 Agent 后生效。")
        return 0

    base.mkdir(parents=True, exist_ok=True)

    print("[A] 安装 skill（立即生效，无需重启）")
    install_skill(root, base)

    # 私有插件（可选）：档案归档触发器。刻意不硬编码路径，只用 --archive-root 或运行时配置
    if args.archive_root:
        ar_try = Path(args.archive_root).expanduser()
    else:
        ar_try = find_archive_root(base)
    extra = []
    if ar_try and (ar_try / ".codebuddy-plugin" / "plugin.json").exists():
        aver = read_version(ar_try)
        extra.append(("personal-kb-guard", ar_try, aver,
                      "个人档案归档触发器——连续多轮未归档就提醒 Agent 执行归档（只提醒，不自动写入）"))
        archive_root = ar_try
        print(f"\n[·] 检测到私有插件：personal-kb-guard  (v{aver}, {ar_try})")
        print("    将与主插件一起注册到同一市场（共用一次重启）")
    else:
        archive_root = None
        if ar_try:
            print(f"\n[·] --archive-root 指向的目录不是插件：{ar_try}（已跳过）")
        else:
            print("\n[·] 未提供 --archive-root，跳过私有插件"
                  "（如需一并安装：--archive-root <私有档案库路径>）")

    print(f"\n[B] 安装 plugin + hooks（{'链接' if args.mode == 'link' else '复制'}模式，需重启生效）")
    install_plugin(root, base, version, use_link=(args.mode == "link"), extra=extra)

    kb_root = Path(args.kb).expanduser().resolve() if args.kb else root
    print("\n[C] 写入运行时配置（hook 启动器据此找到 python / 知识库，不依赖 PATH）")
    write_runtime_config(base, kb_root, archive_root)

    print("\n[D] 验证安装状态")
    verify(base, [e[0] for e in extra])

    verify_launchers(root, base)

    print("\n" + "=" * 56)
    print("下一步（务必执行）")
    print("=" * 56)
    print(f"1. 重启 {args.target}，让插件与 hook 加载")
    print(f"2. 重启后确认 hook 已在工作：")
    print(f"      python \"{root / 'scripts' / 'auto_sediment.py'}\" --mode log         # 知识沉淀插件")
    if archive_root:
        print(f"      python \"{archive_root / 'scripts' / 'archive_trigger.py'}\" "
              f"--kb \"{archive_root}\" --mode status   # 归档触发器")
    print(f"3. 若 Agent 提示新插件需\"信任/启用\"，点确认即可")
    print(f"4. 关闭插件：KNOWLEDGE_SEDIMENT_ENABLE=0 / PERSONAL_KB_GUARD_ENABLE=0")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
