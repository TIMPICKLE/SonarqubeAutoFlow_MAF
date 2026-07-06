# MAF 架构面试问答（Q&A）

> **文档性质**：面试式问答文档，基于本项目（SonarQube AutoFlow MAF 版）的实际代码与 Microsoft Agent Framework 1.10.0 的真实 API 编写
> **配套文档**：[技术文档.md](技术文档.md)、[迁移实现说明.md](迁移实现说明.md)
> **编写日期**：2026-07-06

---

## 目录

- [Q1：技术文档说"MAF 框架内置 ReAct 循环"，具体怎么用的？举例说明](#q1maf-react)
- [Q2：如果想用 Multi-Agent Workflow 等其他 Agent 模式，在 MAF 里怎么做？](#q2multi-agent-workflow)
- [Q3：能否用 Skill 替代一部分 MCP？两者到底是什么关系？](#q3skillmcp)
- [Q4：为什么确定性节点不交给 Agent，而是直接编程式调用 MCP？](#q4确定性节点)
- [Q5：function calling 比 prompt 工程可靠在哪里？什么时候必须回退到 prompt 工程？](#q5function-calling)
- [Q6：MAF 的 WorkflowBuilder 和手写线性编排比，什么时候该用哪个？](#q6workflowbuilder)
- [Q7：Agent 的工具调用如果失败了，框架怎么处理？需要自己写重试吗？](#q7工具失败重试)
- [Q8：如果把 GLM 换成不支持 function calling 的小模型，这套架构还能跑吗？](#q8不支持fc)
- [Q9：MAF 里 Agent、Workflow、Skill、MCP 四者的边界是什么？](#q9四者边界)
- [Q10：如果要扩展成"多个 Agent 协作修复多个异味"，怎么改最小？](#q10多agent扩展)

---

## 一、ReAct 循环：MAF 内置 vs 原项目手写

<a id="q1maf-react"></a>

### Q1：技术文档说"MAF 框架内置 ReAct 循环"，具体怎么用的？举例说明

**A**：ReAct（Reason + Act）的核心是"思考 → 选工具 → 执行 → 观察结果 → 再思考"的循环。原项目在 `tools/smell_fix_agent.py` 的 `_react_loop()` 里手写了 200+ 行来实现它：调用 LLM、自己写 JSON 解析器解析 LLM 输出的 action、手动路由到对应工具、把工具结果拼回 messages、控制最大迭代次数。

MAF 把这个循环变成了框架内置能力。本项目里它被压缩成了三步声明：

**第一步：创建支持 function calling 的 ChatClient**

```python
# APIs/glm_client.py（实际代码，~20 行）
from agent_framework.openai import OpenAIChatClient

def create_glm_client() -> OpenAIChatClient:
    return OpenAIChatClient(
        model=Config.GLM_MODEL,        # "glm-5" / "glm-5.2"
        api_key=Config.GLM_API_KEY,
        base_url=Config.GLM_BASE_URL,  # GLM 的 OpenAI 兼容端点
        instruction_role="system",
    )
```

关键是 GLM 提供 OpenAI 兼容的 `/v1/chat/completions` 接口，所以 `OpenAIChatClient` 能直接复用，不需要写 Custom Provider。

**第二步：声明式创建 Agent，把工具"挂"上去**

```python
# agents/smell_fix_agent.py（实际代码）
from agent_framework import Agent, AgentResponse

class SmellFixAgent:
    def __init__(self, glm_client: OpenAIChatClient):
        self._agent = Agent(
            client=glm_client,
            name="SmellFixAgent",
            instructions=AGENT_SYSTEM_PROMPT,
            tools=[claude_code_fix, analyze_smell_type, analyze_complexity,
                   read_source_code, read_full_file, search_similar_patterns],
        )
```

`tools=` 接收的就是普通 Python 函数（用 `Annotated[..., Field(description=...)]` 标注参数 schema）。MAF 会自动把它们包装成 `FunctionTool`，并生成对应的 JSON Schema 注入给 LLM。

**第三步：一行 `run()` 触发整个循环**

```python
# agents/smell_fix_agent.py（实际代码）
response: AgentResponse = asyncio.run(self._agent.run(user_msg))
result_text = response.text or str(response)
```

这一行背后，框架自动完成的循环是：

```
用户消息 → LLM(system_prompt + 工具 schema)
  ↓ LLM 返回 function_call(analyze_smell_type)
  ↓ 框架自动执行该函数，拿到 {"type":"unused","difficulty":"medium"}
  ↓ 框架把结果作为 tool message 反馈给 LLM
  ↓ LLM 再思考，返回 function_call(claude_code_fix)
  ↓ 框架执行 claude_code_fix → Claude Code CLI 修改代码 + git commit/push
  ↓ 框架把结果反馈给 LLM
  ↓ LLM 返回纯文本总结（无 function_call）→ 循环结束
  ↓ AgentResponse.text = 总结文本
```

**对比原项目手写循环**，被框架取代的具体代码：

| 手写逻辑（原项目） | MAF 内置 |
|------|------|
| `for iteration in range(MAX_ITERATIONS)` | 框架内部循环，`max_iterations` 由 `default_options` 控制 |
| `decision = self._parse_agent_response(response)` 手写 JSON 解析（3 种容错） | function calling 返回结构化 `tool_calls`，无需解析文本 |
| `if action == "FINISH": return` | LLM 不再返回 `function_call` 即视为结束 |
| `tool_result = tool.safe_run(**action_input)` 手动路由 | 框架根据 `tool_call.name` 自动路由到注册的函数 |
| `messages.append({"role":"user","content":f"工具结果:{result}"})` 手动拼回 | 框架自动构造 `tool` role message 反馈 |

**面试要点**：MAF 的 ReAct 循环不是"魔法"，它的本质是**依赖 LLM 的原生 function calling 协议**。框架负责的是协议层的调度（解析 tool_calls、执行、反馈），而"思考"仍然由 LLM 完成。所以这套机制的前提是：接入的 LLM 必须支持 function calling。

---

## 二、Multi-Agent Workflow 与其他 Agent 模式

<a id="q2multi-agent-workflow"></a>

### Q2：如果想用 Multi-Agent Workflow 等其他 Agent 模式，在 MAF 里怎么做？

**A**：MAF 1.10.0 提供了从"单 Agent"到"多 Agent 图编排"的完整谱系。按协作复杂度递增，有四种主要模式：

**模式一：单 Agent + 多工具（本项目当前用的）**

就是一个 `Agent` 挂多个 `FunctionTool`，框架内置 ReAct 循环。适合"一个大脑 + 多只手"的场景。

```python
agent = Agent(client=glm_client, instructions=PROMPT, tools=[tool1, tool2, tool3])
response = await agent.run(user_msg)
```

**模式二：WorkflowBuilder 图编排（替代 LangGraph StateGraph）**

这是 MAF 对标 LangGraph 的能力。`WorkflowBuilder` 支持链式、条件边、扇入扇出、switch-case 分支：

```python
from agent_framework import WorkflowBuilder, AgentExecutor

# 把每个 Agent 包成 Executor
analyzer = AgentExecutor(agent=analyze_agent, id="analyzer")
fixer    = AgentExecutor(agent=fix_agent, id="fixer")
reviewer = AgentExecutor(agent=review_agent, id="reviewer")

builder = WorkflowBuilder(start_executor=analyzer)

# 链式：analyzer → fixer → reviewer
builder.add_chain([analyzer, fixer, reviewer])

# 条件边：修复后根据结果决定走向
builder.add_edge(fixer, reviewer, condition=lambda data: data.get("fix_success"))
builder.add_edge(fixer, failure_handler, condition=lambda data: not data.get("fix_success"))

workflow = builder.build()
result = await workflow.run(input_data)
```

`WorkflowBuilder` 的核心方法（已验证 API 签名）：

| 方法 | 作用 |
|------|------|
| `add_chain([e1, e2, e3])` | 串行链 |
| `add_edge(src, tgt, condition=fn)` | 条件边，`condition` 是 `(data) -> bool` |
| `add_fan_out_edges(src, [t1, t2])` | 扇出（一个节点并行触发多个） |
| `add_fan_in_edges([s1, s2], tgt)` | 扇入（多个汇聚到一个） |
| `add_switch_case_edge_group(src, cases)` | switch-case 多路分支 |
| `add_multi_selection_edge_group(...)` | 多选分支 |
| `build()` | 构建 `Workflow` |

每个节点可以是 `AgentExecutor`（包 Agent）或自定义 `Executor`（用 `@handler` 装饰器定义处理函数）。

**模式三：FunctionalWorkflow（代码式工作流）**

如果你觉得声明式图编排太重，MAF 还提供 `FunctionalWorkflow`，直接用 async 函数写流程：

```python
from agent_framework import FunctionalWorkflow

@FunctionalWorkflow
async def fix_pipeline(data, ctx):
    smell = await analyze_agent.run(data["query"])
    fix = await fix_agent.run(smell)
    if not fix.success:
        await failure_handler.run(fix)
        return
    await review_agent.run(fix)

result = await fix_pipeline.run(input_data)
# 也可以 .as_agent() 把工作流本身当 Agent 用
```

**模式四：WorkflowAgent（把工作流封装成 Agent）**

```python
from agent_framework import WorkflowAgent

# 把上面构建的 workflow 包装成一个可被其他 Agent 调用的"超级 Agent"
wf_agent = WorkflowAgent(workflow=workflow, name="FixPipelineAgent")
# 现在它可以作为另一个 Agent 的工具或子流程被调用
```

**本项目的选择**：当前用的是模式一（单 Agent + 多工具），工作流编排是手写的线性 Python 循环（见 `orchestrator.py` 的 `run()` 方法）。技术文档 6.1 节解释了原因——工作流是简单线性 DAG，条件路由只基于 `error_info`，用 `WorkflowBuilder` 反而引入额外复杂度。

**如果要迁移到 Multi-Agent**，最小改动是：把 `SmellFixAgent` 拆成"分析 Agent"+"修复 Agent"+"审查 Agent"三个，用 `WorkflowBuilder.add_chain` 串起来，`orchestrator.py` 的 `agent_fix` 阶段改为调用这个 workflow。确定性节点（issue_analysis、pr_creation）保持不变。

---

## 三、Skill vs MCP：能互相替代吗

<a id="q3skillmcp"></a>

### Q3：能否用 Skill 替代一部分 MCP？两者到底是什么关系？

**A**：能，而且本项目已经在这么做了——只是用的是"文件级 Skill"而非 MAF 的 Skill API。要讲清楚这个问题，得先分清三件事：Skill 是什么、MCP 是什么、它们各自解决什么问题。

**Skill 是什么**：Skill 是"给 LLM 的知识/指令包"。它本质上是一段 Markdown 文档（`SKILL.md`），告诉 Agent "遇到某类任务该怎么做"。MAF 1.10.0 有完整的 Skill 体系（已验证 API）：

```python
from agent_framework import FileSkillsSource, FileSkill, SkillFrontmatter

# 从目录加载所有 SKILL.md
skills_source = FileSkillsSource(skill_paths=[".claude/skills"])
# Skill 会被注入到 Agent 的 context 中，影响 LLM 的行为
```

MAF 的 Skill 类型有四种：`FileSkill`（Markdown 文件）、`ClassSkill`（Python 类）、`InlineSkill`（内联代码）、`MCPSkill`（从 MCP 服务器动态获取的 Skill）。

**MCP 是什么**：MCP（Model Context Protocol）是"连接外部系统执行真实操作"的协议。它提供的是**可调用的工具**（查 SonarQube、创建 PR），每次调用都有副作用或返回动态数据。

**本项目已经在用 Skill**：看 `tools/fix_tools.py` 的 `_get_skill_for_file()` 和 `_load_skill()` 函数——它会根据文件扩展名（`.cs` → `abp-net-backend`，`.ts` → `angular-frontend`）加载 `.claude/skills/` 下的 Markdown，拼进 Claude Code CLI 的 prompt 里。这就是 Skill 的用法，只是手工加载而非走 MAF Skill API。

**所以答案是：Skill 和 MCP 解决不同问题，是互补而非替代关系。**

| 维度 | Skill | MCP |
|------|-------|-----|
| 本质 | 静态知识/指令（Markdown） | 动态工具/操作（可执行函数） |
| 提供方 | 本地文件 | 外部 MCP Server（stdio/HTTP） |
| 何时用 | "怎么修"的知识（ABP 框架规范、Angular 最佳实践） | "去哪查/做什么"的操作（查 SonarQube、建 PR） |
| 有无副作用 | 无（只影响 LLM 决策） | 有（查数据库、创建资源、改代码） |
| 数据是否动态 | 否（写死的文档） | 是（实时查询结果） |

**能替代的场景**：如果某个 MCP 工具只是"返回一段固定说明"（比如查某个 API 文档），完全可以用 Skill 替代——省掉 MCP Server 的启动开销。本项目里 `.claude/skills/abp-net-backend.md` 就是这种思路：与其让 Agent 调工具查"ABP 项目怎么组织代码"，不如直接把规范喂给它。

**不能替代的场景**：查询 SonarQube issues（数据实时变化）、创建 Azure DevOps PR（有副作用）——这些必须用 MCP，因为结果不是静态文档能覆盖的。

**面试要点**：一句话总结——Skill 管"知识"，MCP 管"操作"。本项目用文件 Skill 提供框架规范知识，用 MCP 连接 SonarQube/Azure DevOps 执行动态操作，两者各司其职。

---

## 四、确定性节点 vs LLM 节点

<a id="q4确定性节点"></a>

### Q4：为什么确定性节点不交给 Agent，而是直接编程式调用 MCP？

**A**：这是本项目的核心设计决策之一。工作流 5 个阶段里，只有 `agent_fix` 走 MAF Agent，其余 4 个（issue_analysis、workspace_setup、pr_creation、record_keeping）都是直接 Python 代码 + MCPManager 调用。

原因有三：

**1. 成本**：把"查询 SonarQube 分页获取 issues"交给 LLM 决策，意味着每次都要消耗 token 让 LLM"思考"该不该翻下一页。这完全是浪费——分页逻辑是确定的，`while` 循环就能搞定。

**2. 可靠性**：创建 PR 的参数（`sourceRefName`、`targetRefName`、`reviewers`、`workItemRefs`）有严格的格式要求。交给 LLM 填写，它可能漏字段、拼错 ref 名、把 GUID 写成邮箱。直接构造 dict 比让 LLM 生成 JSON 可靠得多。

**3. 延迟**：每多一轮 LLM 调用就多几秒延迟。确定性操作直接执行是毫秒级。

**那为什么 agent_fix 要交给 LLM？** 因为修复代码异味需要"理解上下文 → 判断修复策略 → 可能需要先读代码再改"——这是非确定性的，没有固定的 if-else 能覆盖所有异味类型。LLM 的价值在这里：它能根据 `rule`（如 `csharpsquid:S1481`）和 `message`（如"Remove this unused private method"）自主决定是直接删代码还是重构。

**这个决策的边界**：如果一个节点的逻辑能写成确定的算法（分页、Git 操作、JSON 构造），就不该交给 LLM。如果需要"理解语义后做判断"，才值得用 Agent。本项目把这个边界划得很清楚——`orchestrator.py` 处理确定性流程，`SmellFixAgent` 只管需要智能的修复环节。

---

## 五、function calling 的可靠性边界

<a id="q5function-calling"></a>

### Q5：function calling 比 prompt 工程可靠在哪里？什么时候必须回退到 prompt 工程？

**A**：

**function calling 可靠在哪**：

原项目用 prompt 工程让 GLM-5 输出 JSON，然后手写解析器解析。这有三个脆弱点：

1. **格式不稳定**：LLM 可能在 JSON 外面加解释文字、用单引号代替双引号、多输出逗号、把 JSON 包在 markdown 代码块里。原项目为此写了 3 种容错解析策略。
2. **幻觉工具名**：LLM 可能输出一个不存在的工具名，需要手动检查和报错。
3. **参数类型错误**：LLM 可能把 `line: 42` 写成 `line: "42"`，需要手动 coerce。

function calling 解决了这些，因为它是**协议层的约定**：LLM 返回的是结构化的 `tool_calls` 对象（`name` + `arguments` 的 JSON Schema 校验过的值），不是需要解析的自由文本。框架拿到 `tool_calls` 后直接按 `name` 路由到注册的函数，参数已经过 schema 校验。

**什么时候必须回退到 prompt 工程**：

当接入的 LLM **不支持 function calling** 时。这就是原项目的处境——GLM-5 不支持 function calling，所以被迫用 prompt 工程。MAF 的 Agent + tool loop 依赖 function calling，如果模型不支持，`Agent.run()` 不会触发工具调用循环。

回退方案是：用 `ChatClient` 直接调 `get_response()`，在 prompt 里要求 LLM 输出 JSON，自己解析路由——也就是原项目的做法。但这意味着你放弃了 MAF 的核心价值（内置 ReAct 循环），只用了它的 ChatClient 层。

**本项目的现状**：`glm_client.py` 用 `OpenAIChatClient` 接入 GLM。如果 GLM 版本支持 function calling（如 glm-5.2），MAF 的 tool loop 原生工作；如果不支持，需要降级。技术文档 2.2 节的"重要"注释已经标注了这一点。

---

## 六、WorkflowBuilder 的适用边界

<a id="q6workflowbuilder"></a>

### Q6：MAF 的 WorkflowBuilder 和手写线性编排比，什么时候该用哪个？

**A**：

**用手写线性编排（本项目当前做法）的情况**：

- 工作流是简单线性序列：A → B → C → D → E
- 唯一的分支是"出错时走失败路径"
- 不需要持久化/恢复（checkpoint）
- 不需要可视化工作流图

本项目的 `orchestrator.py` 就是这么做的——一个 `for` 循环遍历步骤列表，`if state.error_info` 触发失败路径。代码直观、无框架开销。

**用 WorkflowBuilder 的情况**：

- 有并行分支（fan-out：一个节点同时触发多个 Agent）
- 有汇聚点（fan-in：多个 Agent 的结果合并）
- 有复杂的 switch-case 路由（根据异味类型走不同修复 Agent）
- 需要 checkpoint 持久化（工作流跑到一半挂了能恢复）
- 需要把工作流本身当 Agent 用（`WorkflowAgent`）
- 需要工作流可视化（`WorkflowViz`）

**代码对比**：

```python
# 手写线性（本项目 orchestrator.py）
for step_name, step_fn in steps:
    if state.error_info:
        if state.smell_data:
            state = self.failure_record(state)
        break
    state = step_fn(state)

# WorkflowBuilder 版（如果迁移）
builder = WorkflowBuilder(start_executor=issue_executor)
builder.add_edge(issue_executor, workspace_executor)
builder.add_edge(workspace_executor, agent_executor)
builder.add_edge(agent_executor, pr_executor,
                condition=lambda d: d.get("fix_success"))
builder.add_edge(agent_executor, failure_executor,
                condition=lambda d: not d.get("fix_success"))
builder.add_edge(pr_executor, record_executor)
workflow = builder.build()
result = await workflow.run(state)
```

**面试要点**：WorkflowBuilder 不是"更先进"，而是"更重"。它的价值在于复杂拓扑和持久化。简单线性流程用它，等于用大炮打蚊子——多了 Executor 定义、Edge 配置、状态序列化的认知成本，但没换来任何好处。本项目的技术文档 6.1 节明确记录了这个决策。

---

## 七、工具失败的错误处理

<a id="q7工具失败重试"></a>

### Q7：Agent 的工具调用如果失败了，框架怎么处理？需要自己写重试吗？

**A**：分两个层面：

**框架层面**：MAF 的 tool loop 在工具执行抛异常时，会把异常信息作为 tool message 反馈给 LLM，让 LLM 决定下一步——可能是换一个工具、修改参数重试、或者宣布失败。这是 ReAct 循环的天然容错：工具失败不是终止条件，而是新的"观察"输入。

**本项目层面**：`claude_code_fix` 工具内部做了自己的错误处理——它不会抛异常，而是返回 JSON `{"success": false, "error": "..."}`。这样 Agent 拿到的是结构化的失败信息，能据此决策。同时 `SmellFixAgent.run()` 外层包了 `try/except`，兜底捕获所有异常写入 `state.error_info`，触发工作流的失败路径。

```python
# agents/smell_fix_agent.py（实际代码）
try:
    response: AgentResponse = asyncio.run(self._agent.run(user_msg))
    ...
except Exception as e:
    state["error_info"] = f"SmellFixAgent 执行异常: {e}"
    return state
```

**需要自己写重试吗**：

- **工具内部的瞬时错误**（网络超时、CLI 偶发失败）：应该在工具函数内部重试，因为 LLM 不懂"重试 3 次每次间隔 1 秒"这种策略。`claude_code_fix` 的 `subprocess.run` 有 300 秒超时，超时后直接返回失败让 Agent 决策。
- **工具选择的错误**（LLM 选错工具、参数填错）：不需要自己写重试，框架的 ReAct 循环会自动处理——LLM 看到"工具失败"的反馈后，通常会自己调整策略。
- **不可恢复的错误**（CLI 未安装、仓库不存在）：不重试，直接失败走 failure_record。

---

## 八、模型能力降级

<a id="q8不支持fc"></a>

### Q8：如果把 GLM 换成不支持 function calling 的小模型，这套架构还能跑吗？

**A**：能跑，但 MAF 的核心价值（内置 ReAct 循环）会失效，需要降级到原项目的做法。

**降级路径**：

1. **ChatClient 层不变**：`OpenAIChatClient` 仍然能用，它只是发 chat completion 请求，不依赖 function calling。
2. **Agent 层降级**：不能再用 `Agent(tools=[...]).run()`，因为 tool loop 依赖 function calling。改为直接调 `client.get_response(messages)`，在 prompt 里要求输出 JSON。
3. **工具路由手写**：自己解析 LLM 输出的 JSON，手动路由到工具——就是原项目 `_react_loop` 的做法。
4. **Skill 更重要**：小模型推理能力弱，更需要 Skill 提供明确的操作指引来弥补。

**但更合理的做法**：如果模型不支持 function calling，与其在 MAF 里硬降级，不如直接用原项目的 LangGraph 版本——它本身就是为"无 function calling"设计的（prompt 工程 + 手写路由）。MAF 的价值建立在 function calling 之上，强行降级等于放弃它的核心优势。

**本项目的弹性设计**：`glm_client.py` 通过 `Config.GLM_MODEL` 配置模型名。如果升级到支持 function calling 的 GLM 版本，只需改配置；`OpenAIChatClient` 和 Agent 代码完全不动。这就是用 MAF 的好处——模型升级时框架层零改动。

---

## 九、Agent / Workflow / Skill / MCP 的边界

<a id="q9四者边界"></a>

### Q9：MAF 里 Agent、Workflow、Skill、MCP 四者的边界是什么？

**A**：这是理解 MAF 架构的核心问题。用一张表说清楚：

| 概念 | 是什么 | 解决什么问题 | 本项目的对应物 |
|------|--------|-------------|---------------|
| **Agent** | 一个有 instructions + tools 的 LLM 实体 | 需要智能决策的任务（理解语义后行动） | `SmellFixAgent` |
| **Workflow** | 多个执行器的图编排（DAG） | 多步骤流程编排、并行/条件分支 | 手写线性循环（未用 WorkflowBuilder） |
| **Skill** | 给 LLM 的知识/指令包（Markdown） | "怎么做"的领域知识 | `.claude/skills/*.md`（手工加载） |
| **MCP** | 连接外部系统的工具协议 | "去哪查/做什么"的动态操作 | SonarQube MCP、Azure DevOps MCP |

**四个概念的协作关系**：

```
Workflow 编排多个 Agent 的执行顺序
  └─ Agent 通过 function calling 调用 MCP 工具（执行操作）
  └─ Agent 通过 context 加载 Skill（获取知识）
```

**一个任务该归到哪个概念**，判断标准：

- 有固定算法步骤？→ Workflow 的确定性节点（Executor）
- 需要理解语义后决策？→ Agent
- 是"怎么做"的静态知识？→ Skill
- 是"去哪查/做什么"的动态操作？→ MCP 工具

**容易混淆的点**：MCP 也能提供 Skill（`MCPSkill`），Skill 也能带脚本（`SkillScript`）。但在本项目里两者泾渭分明——Skill 是纯 Markdown 知识（ABP/Angular 规范），MCP 是有副作用的工具（查 issues、建 PR）。

---

## 十、扩展为多 Agent 协作

<a id="q10多agent扩展"></a>

### Q10：如果要扩展成"多个 Agent 协作修复多个异味"，怎么改最小？

**A**：当前架构是"单 Agent 串行处理一个异味"。要扩展成多 Agent 并行处理多个异味，最小改动方案：

**方案 A：多 Workflow 实例并行（改动最小）**

`orchestrator.py` 的 `issue_analysis` 改为一次取 N 个未处理异味，然后用 `asyncio.gather` 并行启动 N 个 `SmellFixAgent.run()`：

```python
async def run_batch(self, smells: list[dict]):
    tasks = [self.smell_fix_agent.run({"smell_data": s, ...}) for s in smells]
    results = await asyncio.gather(*tasks, return_exceptions=True)
    return results
```

改动只在 orchestrator 层，Agent 代码完全不动。风险是 Git 工作区冲突——多个异味可能改同一个文件，需要给每个 Agent 独立的 worktree（`git worktree add`）。

**方案 B：分工式多 Agent（改动中等）**

把 `SmellFixAgent` 拆成三个专职 Agent，用 `WorkflowBuilder` 编排：

```
AnalyzerAgent（判断异味类型+难度）
  → FixerAgent（调用 claude_code_fix 修复）
  → ReviewerAgent（检查修复是否正确，不通过则打回 FixerAgent）
```

```python
from agent_framework import WorkflowBuilder, AgentExecutor

analyzer = AgentExecutor(agent=AnalyzerAgent(...), id="analyzer")
fixer    = AgentExecutor(agent=FixerAgent(...), id="fixer")
reviewer = AgentExecutor(agent=ReviewerAgent(...), id="reviewer")

builder = WorkflowBuilder(start_executor=analyzer)
builder.add_edge(analyzer, fixer)
builder.add_edge(fixer, reviewer)
# 审查不通过 → 回到 fixer 重修（条件边）
builder.add_edge(reviewer, fixer, condition=lambda d: not d["review_passed"])
builder.add_edge(reviewer, output, condition=lambda d: d["review_passed"])
workflow = builder.build()
```

这引入了"审查-反馈"循环，修复质量更高，但增加了 LLM 调用成本。

**方案 C：Orchestrator-Agent 模式（改动较大）**

加一个"调度 Agent"，它不直接修复，而是决定"这个异味该交给哪个专职修复 Agent"。适合异味类型多样、需要不同修复策略的场景（比如 C# 异味和 TypeScript 异味走不同 Agent）。

**本项目的建议**：如果只是想提升吞吐量，方案 A 最小代价。如果想提升修复质量，方案 B 值得做（引入 Reviewer 能显著降低错误修复率）。方案 C 除非异味类型极度多样，否则过度设计。

**面试要点**：MAF 的扩展性体现在——从单 Agent 到多 Agent，框架的 Agent/Workflow/Executor 抽象是连贯的，不需要换技术栈。`AgentExecutor` 把 Agent 包成 Workflow 节点，`WorkflowAgent` 把 Workflow 包成 Agent，两者可任意嵌套。

---

> **文档结束** — 本文档以面试问答形式覆盖了 MAF ReAct 循环用法、Multi-Agent Workflow 模式、Skill 与 MCP 的关系、确定性节点设计、function calling 可靠性、WorkflowBuilder 选型、错误处理、模型降级、四概念边界、多 Agent 扩展十个主题。所有 API 签名基于 agent-framework 1.10.0 实际验证，代码示例取自本项目真实实现。
