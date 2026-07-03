# SonarQube AutoFix — Microsoft Agent Framework Edition

> 基于 **Microsoft Agent Framework (MAF)** 的 SonarQube 代码异味自动修复系统。
> AI Agent 自主决策修复方案，Claude Code CLI 统一执行代码修改，自动创建 Pull Request 并通知负责人。

[![Python](https://img.shields.io/badge/Python-3.10+-blue.svg)](https://www.python.org/)
[![MAF](https://img.shields.io/badge/Agent%20Framework-1.10.0-green.svg)](https://github.com/microsoft/agent-framework)
[![License](https://img.shields.io/badge/license-MIT-lightgrey.svg)](#license)

---

## 目录

- [项目简介](#项目简介)
- [系统架构](#系统架构)
- [工作流程](#工作流程)
- [核心特性](#核心特性)
- [技术栈](#技术栈)
- [项目结构](#项目结构)
- [快速开始](#快速开始)
- [配置说明](#配置说明)
- [运行方式](#运行方式)
- [与 LangGraph 版本的对比](#与-langgraph-版本的对比)
- [设计文档](#设计文档)
- [License](#license)

---

## 项目简介

本系统是一条端到端的代码异味自动修复流水线：从 SonarQube 获取未处理的代码异味（Code Smell），通过 AI Agent 自主决策修复方案，调用 Claude Code CLI 执行代码修改，最终在 Azure DevOps 上创建 Pull Request 并通过飞书通知负责人审阅。

本项目是 LangGraph 版本的 Microsoft Agent Framework (MAF) 迁移版。核心业务逻辑完整复用，框架层使用 MAF 重建，将手写的 200+ 行 ReAct 循环替换为框架内置的 Agent + Tool loop。

### 它解决什么问题

- **异味积压**：SonarQube 识别出的代码异味长期无人处理，系统自动逐一修复并创建 PR
- **人工修复成本高**：简单异味（命名、未使用变量、布尔字面量等）占大量重复劳动，Agent 可自主完成
- **多文件修复困难**：复杂异味常涉及多个关联文件，Claude Code CLI 能自主浏览代码库统一处理

---

## 系统架构

```
┌─────────────────────────────────────────────────────────────────┐
│                    SonarQubeAutoFixOrchestrator                  │
│                        (orchestrator.py)                         │
│                                                                  │
│  ┌──────────┐  ┌──────────┐  ┌──────────┐  ┌──────────┐       │
│  │  异味分析  │→│ 工作区设置 │→│ Agent修复 │→│ PR创建    │       │
│  │  (确定)   │  │  (确定)   │  │  (LLM)   │  │  (确定)   │       │
│  └──────────┘  └──────────┘  └──────────┘  └──────────┘       │
│        │             │             │              │              │
│        ▼             ▼             ▼              ▼              │
│  ┌─────────────────────────────────────────────────────────┐    │
│  │              WorkflowState (状态容器)                    │    │
│  └─────────────────────────────────────────────────────────┘    │
│                                                                  │
│  ┌─────────────────┐  ┌──────────────────┐  ┌───────────────┐  │
│  │  MCPManager     │  │  SmellFixAgent   │  │  飞书通知      │  │
│  │  (MCP 同步封装)  │  │  (MAF Agent)     │  │  (lark-oapi)  │  │
│  └────────┬────────┘  └────────┬─────────┘  └───────────────┘  │
└───────────┼────────────────────┼──────────────────────────────────┘
            │                    │
            ▼                    ▼
   ┌─────────────────┐  ┌──────────────────────────┐
   │   MCP Servers    │  │     MAF Agent 内部        │
   │ SonarQube (npx)  │  │  OpenAIChatClient (GLM)  │
   │ Azure DevOps     │  │  + 6 FunctionTools       │
   └─────────────────┘  │  function calling 自动    │
                        │  ReAct 循环               │
                        └───────────┬──────────────┘
                                    │
                                    ▼
                           ┌──────────────────┐
                           │ Claude Code CLI   │
                           │ (统一修复后端)     │
                           └──────────────────┘
```

### 分层设计

| 层级 | 模块 | 职责 |
|------|------|------|
| 编排层 | `orchestrator.py` | 工作流编排、状态管理、确定性节点业务逻辑 |
| Agent 层 | `agents/smell_fix_agent.py` | MAF Agent，通过 function calling 自主修复 |
| 工具层 | `tools/` | 6 个 MAF FunctionTool（修复/分析/代码读取） |
| 集成层 | `mcp_manager.py`, `APIs/glm_client.py` | MCP 连接、GLM 接入、飞书通知 |

---

## 工作流程

```
issue_analysis → workspace_setup → agent_fix (MAF Agent) → pr_creation → record_keeping → END
                                      ↓ (失败)
                               failure_record → END
```

| 阶段 | 类型 | 说明 |
|------|------|------|
| **异味分析** | 确定性 | 通过 MCP 查询 SonarQube，分页获取未处理的 CRITICAL 级别 CODE_SMELL |
| **工作区设置** | 确定性 | Git clone / checkout master / 创建修复分支 |
| **Agent 修复** | LLM | MAF Agent 通过 function calling 自主选择工具、多轮调用完成修复 |
| **PR 创建** | 确定性 | 调用 Azure DevOps MCP 创建 Pull Request |
| **记录保存** | 确定性 | 将处理记录写入 JSON 文件，避免重复处理 |
| **失败记录** | 确定性 | 任意阶段失败时记录，避免重复处理同一异味 |

### Agent 修复阶段详解

MAF Agent 通过内置的 tool loop 自动完成 ReAct 循环（原项目手写 200+ 行）：

```
第 1 轮: Agent 思考 → 调用 analyze_smell_type (判断异味类型)
第 2 轮: Agent 思考 → 调用 claude_code_fix (Claude Code CLI 修复代码)
         ├─ Claude Code 自主浏览代码库
         ├─ 修改相关文件（支持多文件）
         ├─ 自动 git add / commit / push
         └─ 返回 {success, commit_sha, files_modified}
第 3 轮: Agent 思考 → 确认成功，输出总结
```

---

## 核心特性

### 1. MAF Agent 替代手写 ReAct 循环

```python
# 声明式定义 Agent，框架自动处理 ReAct 循环
agent = Agent(
    client=glm_client,
    instructions=AGENT_SYSTEM_PROMPT,
    tools=[claude_code_fix, analyze_smell_type, read_source_code, ...],
)
response = await agent.run("请处理以下代码异味...")
```

无需手写 JSON 解析器、工具路由、迭代控制——MAF 通过 function calling 自动完成。

### 2. GLM 原生接入

GLM 通过 OpenAI 兼容接口直接接入 MAF 的 `OpenAIChatClient`，无需编写 Custom Provider：

```python
client = OpenAIChatClient(
    model="glm-5",
    api_key="...",
    base_url="https://ai-infra.united-imaging.com",
)
```

### 3. MCP 原生集成

通过轻量 `MCPManager` 连接 SonarQube 和 Azure DevOps MCP 服务器（npx stdio 模式），相比原项目减少 30% 代码。

### 4. Claude Code CLI 统一修复

所有异味修复任务统一交给本机 Claude Code CLI 处理——自主浏览代码库、理解上下文、修改任意数量关联文件并自动提交。

### 5. 密钥环境变量化

API Key、飞书 Secret 等敏感信息通过 `.env` 文件管理，不再硬编码在源码中。

---

## 技术栈

| 技术 | 版本 | 用途 |
|------|------|------|
| [Microsoft Agent Framework](https://github.com/microsoft/agent-framework) | 1.10.0 | Agent 抽象 + 内置 tool loop |
| [MCP](https://modelcontextprotocol.io/) | >=1.12.4 | 连接 SonarQube / Azure DevOps |
| [OpenAI Python SDK](https://github.com/openai/openai-python) | >=2.0.0 | GLM OpenAI 兼容接口接入 |
| [Claude Code CLI](https://docs.anthropic.com/en/docs/claude-code) | - | 统一代码修复后端 |
| [GitPython](https://github.com/gitpython-developers/GitPython) | 3.1.43 | Git 仓库操作 |
| [lark-oapi](https://github.com/larksuite/oapi-sdk-python) | >=1.0.28 | 飞书私信通知 |
| [Rich](https://github.com/Textualize/rich) | 13.9.4 | 终端 UI |
| [Pydantic](https://github.com/pydantic/pydantic) | >=2.10.2 | 工具参数 schema |
| GLM (智谱 AI) | glm-5 / glm-5.2 | LLM 后端 |

---

## 项目结构

```
SonarqubeAutoFlow_SingleProject_MAF/
├── orchestrator.py              # 工作流编排 + 确定性节点 + 飞书通知
├── mcp_manager.py               # 轻量 MCP 同步客户端
├── config.py                    # 配置管理（环境变量化）
├── cli.py                       # CLI 入口
├── .env                         # 环境变量（API Key 等）
├── requirements.txt             # Python 依赖
│
├── APIs/
│   ├── __init__.py
│   └── glm_client.py            # GLM 接入（MAF OpenAIChatClient）
│
├── agents/
│   ├── __init__.py
│   └── smell_fix_agent.py       # MAF Agent（替代手写 ReAct 循环）
│
├── tools/
│   ├── __init__.py
│   ├── fix_tools.py             # claude_code_fix（Claude Code CLI 修复）
│   ├── analysis_tools.py        # analyze_smell_type / analyze_complexity
│   └── code_tools.py            # read_source_code / read_full_file / search
│
├── localJSON/                   # 数据文件
│   ├── mcp.json                 # MCP 服务器配置
│   ├── codeSmallList.json       # 已处理异味记录
│   ├── emailToGuid.json         # 邮箱→GUID 映射
│   ├── emialtoOpenId.json       # 邮箱→飞书OpenID 映射
│   └── effort_state.json        # 累计工作量统计
│
├── doc/
│   ├── 技术文档.md               # 教学型技术文档（架构/数据流/设计决策）
│   └── 迁移实现说明.md           # 迁移过程与文档勘误
│
├── TempLog/                     # 运行时日志
└── .claude/                     # Claude Code skills 配置
```

---

## 快速开始

### 前置条件

- Python 3.10+
- Node.js（用于运行 MCP 服务器，`npx` 命令）
- [Claude Code CLI](https://docs.anthropic.com/en/docs/claude-code) 已安装并登录
- Git
- 可访问的 SonarQube 实例
- 可访问的 Azure DevOps 实例
- GLM 模型服务端点（OpenAI 兼容接口）

### 安装

```bash
# 克隆仓库
git clone https://github.com/TIMPICKLE/SonarqubeAutoFlow_MAF.git
cd SonarqubeAutoFlow_MAF

# 安装 Python 依赖
pip install -r requirements.txt
```

### 配置

编辑 `.env` 文件，填入你的配置：

```bash
# GLM 配置
GLM_BASE_URL=https://your-glm-endpoint
GLM_API_KEY=your-api-key
GLM_MODEL=glm-5

# 飞书配置
FEISHU_APP_ID=your-feishu-app-id
FEISHU_APP_SECRET=your-feishu-app-secret
```

编辑 `localJSON/mcp.json`，配置 SonarQube 和 Azure DevOps MCP 服务器：

```json
{
    "mcpServers": {
        "azureDevOps": {
            "command": "npx",
            "args": ["-y", "@tiberriver256/mcp-server-azure-devops"],
            "env": {
                "AZURE_DEVOPS_ORG_URL": "https://your-organization.visualstudio.com",
                "AZURE_DEVOPS_AUTH_METHOD": "pat",
                "AZURE_DEVOPS_PAT": "your-pat",
                "AZURE_DEVOPS_DEFAULT_PROJECT": "your-project"
            }
        },
        "sonarqube": {
            "command": "npx",
            "args": ["--yes", "sonarqube-mcp-server@latest"],
            "env": {
                "SONARQUBE_URL": "http://your-sonarqube:9000",
                "SONARQUBE_USERNAME": "your-username",
                "SONARQUBE_PASSWORD": "your-password"
            }
        }
    }
}
```

编辑 `config.py` 中的项目相关配置（SonarQube project key、Azure DevOps project、Git 仓库地址等）。

---

## 配置说明

### 关键配置项

| 配置项 | 位置 | 说明 |
|--------|------|------|
| `GLM_MODEL` | `.env` | GLM 模型名，支持 function calling 时改为 `glm-5.2` |
| `GLM_BASE_URL` | `.env` | GLM 服务端点（OpenAI 兼容） |
| `SONARQUBE_PROJECT_KEY` | `config.py` | SonarQube 项目 key |
| `SONARQUBE_SEVERITIES` | `config.py` | 处理的严重级别（默认 CRITICAL） |
| `GIT_REPO_PATH` | `config.py` | 本地 Git 仓库路径（不存在会自动 clone） |
| `AZURE_DEVOPS_PROJECT` | `config.py` | Azure DevOps 项目名 |
| `DEFAULT_REVIEWER` | `config.py` | 默认 PR 审查者 GUID |

### 数据文件

| 文件 | 用途 |
|------|------|
| `localJSON/mcp.json` | MCP 服务器配置（SonarQube + Azure DevOps） |
| `localJSON/codeSmallList.json` | 已处理异味记录（自动追加，避免重复处理） |
| `localJSON/emailToGuid.json` | 邮箱→Azure DevOps GUID 映射（用于 PR 审查者分配） |
| `localJSON/emialtoOpenId.json` | 邮箱→飞书 OpenID 映射（用于私信通知） |

---

## 运行方式

```bash
# 执行自动修复流程（处理一条异味）
python cli.py run

# 查看系统状态
python cli.py status
```

### 运行输出示例

```
╭──────────────────────────────────────────╮
│ SonarQube 自动修复系统 (MAF 版) 启动      │
╰──────────────────────────────────────────╯
MCPManager 初始化，2 个服务器
SmellFixAgent (MAF) 初始化完成，已注册 6 个 FunctionTool
总控制器初始化完成

执行阶段: issue_analysis
找到未处理异味: AXh3F4DsmF9pXxY7Z0qL
阶段 issue_analysis 完成 -> workspace_setup

执行阶段: workspace_setup
工作区设置完成，当前分支: fix-sonar-AXh3F4D-20260703143022
阶段 workspace_setup 完成 -> agent_fix

执行阶段: agent_fix
SmellFixAgent (MAF) 开始自主修复
SmellFixAgent 修复成功: Claude Code 修改了 1 个文件，已提交 9a44e78a
阶段 agent_fix 完成 -> pr_creation

执行阶段: pr_creation
PR 创建成功: https://.../pullrequest/12345
阶段 pr_creation 完成 -> record_keeping

╭──────────────────────────────────────────╮
│ ✅ 自动修复流程执行成功！                  │
╰──────────────────────────────────────────╯
```

---

## 与 LangGraph 版本的对比

| 维度 | LangGraph 版 (原项目) | MAF 版 (本项目) |
|------|----------------------|----------------|
| ReAct 循环 | 手写 200+ 行 | MAF Agent 内置 (function calling) |
| LLM 接入 | 自建 GLM API 封装 (prompt 工程) | MAF OpenAIChatClient (原生 function calling) |
| MCP 集成 | 自建 MCPClient (200+ 行) | 轻量 MCPManager (~150 行) |
| 工具体系 | BaseTool + ToolRegistry 两阶段选择 | MAF FunctionTool 声明式注册 |
| 工具选择 | 规则筛选 + LLM 决策 | LLM 原生 function calling 自动选择 |
| 状态管理 | 全局大 WorkflowState (TypedDict) | WorkflowState 类 (作用域隔离) |
| 密钥管理 | 硬编码 | 环境变量 + .env |
| **框架层代码** | **~850 行** | **~180 行 (-79%)** |

详细对比与迁移过程请参阅 [doc/迁移实现说明.md](doc/迁移实现说明.md)。

---

## 设计文档

| 文档 | 说明 |
|------|------|
| [doc/技术文档.md](doc/技术文档.md) | 教学型技术文档：技术栈、解决的问题、架构设计、运行时数据流、设计决策 |
| [doc/迁移实现说明.md](doc/迁移实现说明.md) | 从 LangGraph 迁移到 MAF 的实现细节与原文档勘误 |

---

## License

MIT License - 详见 [LICENSE](LICENSE) 文件。
