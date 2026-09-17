# hooks · 触发层的设计说明

> 本目录提供"会话轮次结束时自动执行沉淀检查"的能力。
> **注意：`hooks.json` 里不能写注释**——平台的配置校验会遍历所有顶层键，
> 遇到非数组的值会判定整个配置非法并整体丢弃，所以说明文档放在这里。

## 一、为什么需要启动器（`run.sh` / `run.ps1`）

hook 的执行环境**不保证 `python` 在 PATH 里**（平台自己的插件也刻意只依赖 bash /
PowerShell，见 `financial-analysis` 的 hook 注释："纯 bash 实现，不依赖 node/python"）。

所以 hook 命令不直接调 python，而是调启动器，由启动器按优先级寻找解释器：

```
1. ~/.workbuddy/knowledge-sediment.json 里的 python 字段（安装时写入，最可靠）
2. 环境变量 KNOWLEDGE_SEDIMENT_PYTHON
3. WorkBuddy 托管 Python（venv → versions/* 取最高版本）
4. PATH 上的 python3 / python / py
```

找不到就**静默退出**，不做任何事。

## 二、事件选择

| 事件 | 在本平台的含义 | 我们的用法 |
|---|---|---|
| **`FinalStop`** | **一轮回复真正结束**（`executeFinalStopHooks`，`reason=completed`） | ✅ **主入口**，允许输出提示 |
| `Stop` | 会话级"目标条件"hook，其输出会被当作"是否继续对话"的判据 | 只跑后台工作，**强制 `-Silent`**，绝不输出 |
| `SessionEnd` | 会话关闭 | 兜底心跳，**强制 `-Silent`** |

> 踩坑记录：最初只注册了 `Stop`，结果 hook 加载成功（日志显示 `1 hook(s)`）却从不触发——
> 因为本平台"一轮结束"发的是 `FinalStop` 事件。诊断方法见第六节。

## 三、入口选择：只注册 POSIX shell 一个入口（重要）

**结论：只注册 `bash run.sh`，不要注册 PowerShell 入口。**

原因是本平台的一个行为：`${CODEBUDDY_PLUGIN_ROOT}` **会被展开成 POSIX 风格路径**
（`/c/Users/xxx/.workbuddy/...`）。于是：

| 入口 | 结果 |
|---|---|
| `bash "${CODEBUDDY_PLUGIN_ROOT}/hooks/run.sh"` | ✅ 正常（bash 认这个路径） |
| `powershell.exe -File "${CODEBUDDY_PLUGIN_ROOT}/hooks/run.ps1"` | ❌ **失败**：`-File 格式不正确`，实际收到 `/c/Users/...` |

实测日志（"hook 明明执行了却毫无效果"时抓到的真凶）：

```text
[HookExecutor] abnormal exit pid=8476 code=4294770688 elapsed=136ms
  cmd=powershell.exe -NoProfile ... -File "/c/Users/123/.../hooks/run.ps1"
Hook exited with non-blocking error code 4294770688:
  -File 格式不正确: 实际参数"/c/Users/123/.workbuddy/.../hooks/run.ps1"
```

> 平台自带插件 `financial-analysis` 的 PowerShell 入口**在同一台机器上有完全相同的故障**——
> 这不是我们的写法问题，而是"把 POSIX 路径交给 Windows 程序"的通用坑。
> 它同时提供了 bash 入口，实际生效的是那一个。

`run.ps1` 保留在仓库里，作为 **bash 不可用环境**的备用入口。若要启用它，
**必须先把 `${CODEBUDDY_PLUGIN_ROOT}` 转成 Windows 路径**（`/c/x → C:/x`）再传给 `-File`。

### 3.1 同理：脚本路径也不能直接喂给 Windows 版 python

`run.sh` 找到的可能是 Windows 版解释器（`python.exe`）。此时**脚本路径也必须转成
Windows 格式**，否则 python 会把 `/c/Users/...` 理解成 `C:\c\Users\...` → 报"文件不存在"。

这个失败的**表现极具欺骗性**：`run.sh` 里 `2>/dev/null` 吞掉了 stderr，
于是"找不到脚本"和"静默成功"看起来一模一样（现象是心跳不增长但退出码为 0）。

**所以现在启动器会把错误写进诊断日志** `~/.workbuddy/logs/knowledge-sediment-hook.err`，
不再无痕。这一条通用原则值得记住：**静默设计必须配一个"失败可见"的出口**，
否则静默会把 bug 一起藏起来。

## 四、铁律（保证"不影响主线工作"）

1. **永远 `exit 0`**——hook 的任何失败都不得阻塞会话
2. **正常情况零输出**——不向对话上下文注入任何内容
3. **找不到解释器就静默跳过**——不报错、不提示
4. **静默但可诊断**——失败必须留痕（见 3.1），否则无法排障
5. **超时 20 秒**——脚本自身只做只读扫描，实测毫秒级返回

## 五、怎么验证它真的在工作

三层递进，**只有第三层能证明"跑起来了"**：

```bash
# 第一层：启动器本身（隔离测试）
bash hooks/run.sh          # 期望 exit=0、stdout 0 字节
#   ⚠️ 这一层光看 exit 码不够：脚本路径错时也是 0 / 零输出
#   → 必须同时确认心跳行数 +1，或看 knowledge-sediment-hook.err

# 第二层：平台是否加载并派发了 hook（看应用日志）
#   期望出现：HookExtensionLoader  Loaded hooks configuration from extension: ...
#             [FinalStop] executeFinalStopHooks entry ... reason=completed
#             [HookManager] event=FinalStop matched N distinct hook entries
#   若 matched 到了但心跳不涨 → 问题在启动器
#   若根本没有 matched → 问题在事件名

# 第三层：★唯一可信判据——心跳日志
python scripts/auto_sediment.py --mode log
#   期望：每次对话轮次结束后新增一行
```


`install_plugin.py` 会自动跑第一层；第二、三层需要重启 Agent 后观察。

## 六、诊断"hook 加载了但没触发 / 触发了但没效果"

按顺序排查，**每一步的结论都能定位到不同的层**：

1. 打开当前工作区的会话日志（`~/.workbuddy/logs/<日期>/<workspace>__*.log`）
2. 搜 `HookExtensionLoader` → 确认插件配置被加载；若出现 `Invalid hooks configuration`，
   说明 `hooks.json` 格式被判定非法（**注意：顶层不能写注释键**，非数组值会让整份配置被丢弃）
3. 搜 `executeFinalStopHooks entry` → 确认"一轮结束"事件确实派发了
4. 搜 `event=FinalStop matched N distinct hook entries` → 确认我们的命令被匹配到
5. 搜 `HookExecutor` / `abnormal exit` → 确认命令执行是否报错（**步骤 4、5 是本次抓出
   PowerShell 路径故障的关键**）
6. 都没问题但心跳不涨 → 看 `~/.workbuddy/logs/knowledge-sediment-hook.err`
   （启动器把解释器/路径信息写在这里）

| 现象 | 病因所在层 |
|---|---|
| 没有 `Load hooks configuration` | 插件注册 / 市场 |
| 有加载，但没有 `matched N hook entries` | **事件名**（本次踩过：`Stop` → `FinalStop`） |
| 有 matched，但 `abnormal exit` | **命令能否执行**（本次踩过：POSIX 路径 → PowerShell） |
| 命令正常退出但心跳不涨 | **启动器内部**（本次踩过：POSIX 路径 → Windows python） |
| 心跳涨了但没提醒 | 提示条件未满足（按日节流 / 改动数不够）——属正常 |

---

## 七、实测记录（2026-09-17，WorkBuddy 5.3.8）

**结论：链路已打通。** 关键日志：

```text
[HookExecutor] spawn pid=20868 shell=C:\Users\123\.workbuddy\vendor\PortableGit\bin\bash.exe
  timeout=20000ms cmd=bash "/c/Users/123/.workbuddy/plugins/cache/personal-local/
  knowledge-sediment/0.1.0/hooks/run.sh"
[FinalStop] FinalStop hooks completed successfully durationMs=634
```

心跳日志同步新增记录 → **脚本确实执行了**。

### 三条实测发现（都影响后续设计）

**1. 平台用自带的 PortableGit bash 执行 hook**（`vendor\PortableGit\bin\bash.exe`）

这解释了为什么 `${CODEBUDDY_PLUGIN_ROOT}` 是 POSIX 风格路径——因为它就是被一个
Git Bash 子进程展开的。所以：

- ✅ `bash` 在此环境**永远可用**，POSIX 入口是可靠路径
- ❌ 不要依赖任何 Windows 形态的路径或程序（这正是之前 PowerShell 入口失败的根本原因）

**2. `Stop` 和 `FinalStop` 在一次轮次结束时会「双双触发」**

```text
[SessionHookManager] executeStopHooks ... stopReason=completed     ← Stop
[FinalStop] executeFinalStopHooks entry ... reason=completed       ← FinalStop
```

→ 两个事件都注册的话，**同一轮会跑两次**（心跳出现同一秒两条）。
**建议只注册 `FinalStop`**（语义就是"一轮结束"）；不要为"保险"两个都注册，那只会让每轮工作翻倍。

**3. `FinalStop` 的 hook 输出会被丢弃 → 提醒不能走这个事件**

从平台代码看：`FinalStop` 执行后只记日志，**不解析 hook 输出**；
而 `Stop` 的输出会被解析成 `allowed` / `continueRequest` / `preventContinuation`
（即"是否让 Agent 继续"），语义完全不同。

| 想要的效果 | 应该用的事件 |
|---|---|
| 后台静默工作 + 心跳留痕 | ✅ `FinalStop` |
| **把提醒注入对话上下文** | ✅ **`UserPromptSubmit`**（支持 `hookSpecificOutput.additionalContext`） |
| 记录会话关闭 | `SessionEnd` |

→ "提醒用户去沉淀"这类能力**必须单独注册 `UserPromptSubmit`**，
不能指望 `FinalStop` 的输出被 Agent 看到。

### 当前配置（2026-09-17 更新完成）

```jsonc
"FinalStop"        → bash run.sh --silent      // 后台静默工作 + 心跳留痕
"UserPromptSubmit" → bash run.sh --emit-json   // 提醒通道（additionalContext 注入）
```

**去掉了两件事**：

- `Stop` —— 与 `FinalStop` 在同一轮次结束**重复触发**，留着只会让每轮工作翻倍
- `SessionEnd` —— 实际用途有限，且会增加无谓执行

配套改动：`auto_sediment.py` 新增 `--emit json --event UserPromptSubmit`
（把提示包成 hook 信封），`run.sh` 新增 `--emit-json`。

---

_相关文件：`run.sh`、`run.ps1`、`../scripts/auto_sediment.py`、`../scripts/install_plugin.py`_
