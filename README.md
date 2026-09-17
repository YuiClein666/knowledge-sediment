# knowledge-sediment · 知识沉淀

> **让 Agent 把你在任何工作区产生的可复用知识，自动沉淀成一座会长大的知识库。**
> 装一次，之后你在哪台机器、哪个目录干活，知识都往同一个地方汇。

---

## 它解决什么问题

用过笔记软件的人大多经历过同一件事：**建了 12 个文件夹，三个月后 11 个是空的。**

原因不是懒，是**记录的成本高于收益**：
- 你得先停下手上的活，想"这条该放哪"，然后打开另一个软件、新建文件、复制粘贴
- 而收益要几个月后才出现——那时候你早就不用这个软件了

于是知识就散落在：聊天记录里、某个项目的 README 里、上次那个 prompt 里、
你自己的脑子里（但会忘）。

**这个插件把顺序反过来**：记录由 Agent 顺手完成，你只负责干活。

---

## 三步开始

### 1. 克隆

```bash
git clone https://github.com/<你的账号>/knowledge-sediment.git
```

### 2. 让 Agent 初始化

用你的 AI 工具（WorkBuddy / CodeBuddy 等）**打开这个文件夹作为工作区**，然后说：

```
帮我初始化知识库
```

Agent 会读 [`INIT.md`](./INIT.md) 并带你走完：
投喂素材 → 分析你的领域 → **提议分类方案给你改** → 生成骨架 → 装好插件 → 教你怎么用。

> 关于"投喂素材"：给它你的简历、项目文档、在学的技术栈、论文方向——
> **有什么给什么，不用整理**。分类就是从这些素材里长出来的，所以每个人的知识库长得都不一样。

### 3. 之后正常干活

| 你说 | 发生什么 |
|---|---|
| **"沉淀一下"** | 把当前讨论里可复用的部分收进知识库 |
| **"查一下 XX"** | 按分类和关键词去知识库找 |
| 正常聊 | Agent 自动判断，有价值的顺手记 |

---

## 它怎么工作

### 三层索引（这是能被 AI 快速检索的关键）

```
index.md                     ← 第一入口：去哪一类
  └─ <分类>/_index.md        ← 第二入口：去哪一单元
       └─ <单元>/_index.md   ← 第三入口：读哪一篇
            └─ <主题>.md     ← 具体内容
```

每一层的 `_index.md` 都带 `tags` / `keywords` / `summary`。
所以 Agent 检索时**不需要通读全库**——按层往下走，三步就能定位。
这也是它比"把所有笔记塞给 AI"更省 token 的原因。

### 三个让它"活得住"的机制

| 机制 | 作用 |
|---|---|
| **引用地图** `_map.md` | 自动扫描笔记之间的关系（依赖 / 相关 / 取代 / 矛盾），生成关系网——检索时能顺着关系跳转，而不只是按目录找 |
| **健康度报告** `_health.md` | 监控 8 项结构指标。最有用的一项：**某个单元文件数超阈值 → 提示"该拆了"并给出拆分建议** |
| **晋升制** | `draft`（草稿，只在 inbox）→ `promoted`（被复用/引用过）→ `deprecated`。**晋升依据是可观测的使用信号，不是主观打分** |

### 沉淀的触发（不依赖你记得）

| 触发方式 | 可靠性 |
|---|---|
| 你说"沉淀一下" | 手动，最可控 |
| Agent 任务中自主判断 | 靠提示词，**会忘**（长任务里注意力被挤走） |
| **轮次结束 hook 兜底** | 机制保证，不依赖任何人记得 |

第三种是设计重点：**"系统提示是请求，hook 是保证。"**
不过 hook 需要 Agent 支持——不支持也能用，只是少一层自动性（见下）。

---

## 支持哪些 Agent

| 能力 | 说明 |
|---|---|
| **声明层**（`SKILL.md` + `AGENTS.md`） | ✅ 跨平台通用——`AGENTS.md` 已被 20+ 工具原生读取 |
| **执行层**（Python 脚本） | ✅ 纯标准库，0 第三方依赖，有 Python 就能跑 |
| **触发层**（`hooks/`） | ⚠️ **各 Agent 事件名与配置位置不同，需要适配** |

已实测：
- **WorkBuddy / CodeBuddy**：插件 + hook 全部可用（一轮结束的事件名是 `FinalStop`，不是 `Stop`）
- **其他 Agent**：装 skill 即可用（手动触发），hook 需按 `hooks/README.md` 的思路适配

**不支持 hook 不是阻塞**——功能不缺，只是少了自动触发这一层。

---

## 已知限制（诚实说明）

- **分类质量取决于投喂的素材**。如果你什么都不给，Agent 只能给通用分类——
  它照样能用，但不会"贴合你"。
- **去重不是完美的**。用的是"哈希 + 关键词召回候选 + LLM 判断"的轻量方案，
  没有向量数据库。好处是零依赖、可解释；代价是语义相近但用词差很远的重复可能漏掉。
- **自动沉淀 + 公开仓库是危险组合**。如果知识库要同步到 GitHub，
  **请用私有仓库**——或者先确认你没有把公司内部信息写进去。
- **它管"我会什么"，不管"我是谁"**。个人经历、关系、决策这类内容请另建一座库，
  两者刻意分开（混在一起会让检索变差，也让可见性无法区分）。

---

## 命令参考

脚本都在 `scripts/`，全部支持 `--kb` 显式指定知识库位置。

```bash
# 环境自检：知识库在哪、有哪些分类
python scripts/config.py

# 生成骨架（按分类方案）
python scripts/scaffold_kb.py --taxonomy taxonomy.json --kb "<知识库路径>"

# 重建三层索引
python scripts/knowledge_cli.py index

# 引用地图
python scripts/knowledge_cli.py map

# 结构健康度
python scripts/knowledge_cli.py health

# 统计概览
python scripts/knowledge_cli.py stats

# 沉淀一条到 inbox
python scripts/knowledge_cli.py capture --title "标题" --content "内容" --tag "标签"

# 同步（索引重建 + commit，可选 push）
python scripts/knowledge_cli.py sync --push

# 在任意工作区开启沉淀目录
python scripts/init_workspace.py --workdir "<工作区>" --kb "<知识库>"

# 安装到 Agent
python scripts/install_plugin.py --target workbuddy --kb "<知识库路径>"
```

---

## 目录结构

```
knowledge-sediment/
├── INIT.md                     ← ★ Agent 读的初始化指令（你不需要看）
├── README.md                   ← 本文件
├── .codebuddy-plugin/          ← 插件清单
├── skills/knowledge-sediment/  ← Agent 能力入口（沉淀判断标准与流程）
├── hooks/                      ← 轮次结束的兜底触发
│   ├── run.sh / run.ps1
│   ├── hooks.json
│   └── README.md               ← 各平台事件的适配说明与排障
└── scripts/
    ├── config.py               ← 配置读写（知识库位置 + 分类体系）
    ├── scaffold_kb.py          ← 按分类方案生成骨架
    ├── knowledge_cli.py        ← index / map / health / stats / capture / sync
    ├── init_workspace.py       ← 在任意工作区创建 .knowledge/
    ├── auto_sediment.py        ← hook 调用的兜底脚本
    ├── install_plugin.py       ← 一键安装到 Agent
    └── tree.py                 ← 生成结构树（用于分享/汇报）
```

---

## 设计原则

1. **分类由 Agent 从你的素材推导，不套模板**——所以每个知识库都不一样
2. **位置即含义**——`10-` `20-` `30-` 的编号本身承担语义，也方便插入新分类
3. **索引是为了被检索，不是为了好看**——每层都必须有 `tags` / `keywords` / `summary`
4. **静默设计必须配失败出口**——所有 hook 永远 `exit 0` 不影响会话，
   但错误会写进诊断日志，避免"静默失败看起来像成功"
5. **规则自包含**——所有行为规则都在仓库内，不依赖任何 Agent 的私有配置，
   换工具不会丢规则

---

_由 [INIT.md](./INIT.md) 引导生成的知识库不含任何预置内容——
你拿到的是空骨架，它会长成什么样取决于你往里放什么。_
