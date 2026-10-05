# Spec Kit 使用方法总结

## 一、什么是 Spec Kit

Spec Kit 是 GitHub 推出的开源工具包，用于实践**规格驱动开发（SDD）**。核心思路：先用 Markdown 文件把"做什么"和"为什么做"说清楚，再让 AI 编码助手按这些规格去规划和实现，避免模糊需求导致的反复返工。

## 二、安装与初始化

前置要求：Python 3.11+ 和 uv

```bash
# 安装
uv tool install specify-cli

# 新建项目（以 Copilot 为例）
specify init my-project --integration copilot
cd my-project
```

对已有项目，在当前目录初始化，不会动现有代码：

```bash
specify init --here --integration copilot
```

> **注意**：新版本已用 `--integration` 替代旧的 `--ai` 参数，旧教程里的 `--ai` 会报错。

## 三、核心工作流

Spec Kit 的工作流由终端命令和 AI 聊天中的斜杠命令两部分组成。推荐完整链路如下（Copilot 的 skills 模式用 `/speckit-*`）：

### 1. `/speckit-constitution` — 确立项目原则

整个项目周期只跑一次。定义技术栈约束、安全要求、编码规范等不可协商的规则，后续所有计划和代码都要以此为准。

### 2. `/speckit-specify` — 生成需求规格

用自然语言描述要构建的功能，**聚焦"做什么"和"为什么"，不要提技术栈**。AI 会生成包含用户故事、验收标准、功能需求和非功能需求的 `spec.md`。

### 3. `/speckit-clarify` — 澄清模糊点

可选质量门禁。AI 针对规格中不明确的区域提出最多 5 个问题，回答后直接写回 `spec.md`。在规划前跑这一步，能避免在歧义之上做设计。

### 4. `/speckit-plan` — 制定技术方案

根据规格生成实现计划，此时才引入技术栈、架构、数据模型等"怎么做"的内容，产出 `plan.md`。

### 5. `/speckit-tasks` — 拆解任务

把计划拆成可执行、带依赖关系的任务清单，产出 `tasks.md`。标有 `[P]` 的任务可以并行执行。

### 6. `/speckit-analyze` — 一致性检查

可选质量门禁。在实现前检查规格、计划、任务三者之间是否一致，有无遗漏或矛盾。

### 7. `/speckit-implement` — 执行实现

按 `tasks.md` 中的顺序执行，逐个勾选完成的任务。失败的顺序任务会停下来报错，修复后重新运行会从断点继续。

### 8. `/speckit-converge` — 收敛检查

实现完成后，检查代码是否真正符合规格，把剩余未完成的工作补录进去。

## 四、精简与完整的选择

| 场景 | 推荐路径 |
| --- | --- |
| 探索性 Demo / 一次性小工具 | `specify → plan → tasks → implement` |
| 生产级功能 | 全量执行（含 clarify、checklist、analyze、converge） |

## 五、产物与目录结构

所有规格工件都是普通 Markdown 文件，存放在仓库中，可纳入 Git 版本控制：

```text
my-project/
├── .specify/
│   ├── memory/constitution.md    # 项目原则
│   └── templates/                 # 命令模板
└── specs/
    └── 001-feature-name/
        ├── spec.md               # 需求规格
        ├── plan.md               # 技术计划
        └── tasks.md              # 任务清单
```

## 六、实用技巧

**现有项目改造**：在 `constitution` 中明确描述现有架构和必须遵循的模式，在 `specify` 中只描述这次要改什么，不要让 AI 重新设计整个系统。

**环境变量追踪功能**：Spec Kit 默认从 Git 分支名推断当前功能。非 Git 工作流可手动设置：

```bash
$env:SPECIFY_FEATURE = "001-document-upload"
```

**命令调用语法因 Agent 而异**：Copilot 用 `/speckit-*`，Claude Code 旧版用 `/speckit.*`，Codex 可能用 `$speckit-*`。以实际使用的 Agent 文档为准。
