"""
SmellFixAgent - MAF 版本

原始项目在 tools/smell_fix_agent.py 中手写了 200+ 行的 ReAct 循环：
  LLM 调用 -> JSON 解析 -> 工具路由 -> 结果反馈 -> 重试

MAF 的 Agent + Tool loop 是框架内置的，只需声明 Agent 和 Tools，
框架通过 function calling 自动处理整个 ReAct 循环——无需手写 JSON 解析器、
无需手写迭代控制、无需手写工具路由。

GLM 支持 OpenAI 兼容的 function calling 接口，MAF 的 OpenAIChatClient 可直接触发工具调用。
"""
import json
import asyncio
import shutil
from pathlib import Path

from agent_framework import Agent, AgentResponse
from agent_framework.openai import OpenAIChatClient
from rich.console import Console
from rich.panel import Panel

from config import Config
from tools.fix_tools import claude_code_fix
from tools.analysis_tools import analyze_smell_type, analyze_complexity
from tools.code_tools import read_source_code, read_full_file, search_similar_patterns

console = Console()

AGENT_SYSTEM_PROMPT = """你是一个 SonarQube 代码异味自动修复 Agent。

## 工作流程
1. （可选）使用 analyze_smell_type 判断异味类型和难度
2. （可选）使用 read_source_code / read_full_file / search_similar_patterns 了解代码上下文
3. **调用 claude_code_fix 执行修复**——无论异味简单还是复杂、单文件还是多文件，一律使用 claude_code_fix。
   它会自主浏览代码库、理解上下文、修改所有相关文件，并自动完成 git add / commit / push
4. 确认 claude_code_fix 返回成功后，用一句话总结修复结果

## 关键原则
- 所有修复任务一律通过 claude_code_fix 完成，不要使用其他方式修改代码
- claude_code_fix 会自动处理 git 提交和推送，无需额外操作
- 分析类工具仅用于辅助理解，不是必须的
- 每次只处理一个异味
"""


class SmellFixAgent:
    """代码异味修复 Agent - 基于 MAF Agent 的声明式实现（替代手写 ReAct 循环）"""

    def __init__(self, glm_client: OpenAIChatClient):
        self._agent = Agent(
            client=glm_client,
            name="SmellFixAgent",
            instructions=AGENT_SYSTEM_PROMPT,
            tools=[claude_code_fix, analyze_smell_type, analyze_complexity,
                   read_source_code, read_full_file, search_similar_patterns],
        )
        console.print("[green]SmellFixAgent (MAF) 初始化完成，已注册 6 个 FunctionTool[/green]")

    def run(self, state: dict) -> dict:
        """Agent 主入口——作为工作流节点运行。原始项目此处有 200+ 行 _react_loop，现在由 MAF Agent 内置的 tool loop 取代。"""
        try:
            console.print(Panel("[bold blue]SmellFixAgent (MAF) 开始自主修复[/bold blue]"))

            smell_data = state.get("smell_data")
            if not smell_data:
                state["error_info"] = "缺少异味数据，无法执行修复"
                return state

            branch_name = state.get("branch_name", "")
            email_to_guid = self._load_email_to_guid()
            assignee_guid = email_to_guid.get(smell_data.get("author", ""), "")

            component = smell_data.get("component", "")
            file_path = component.replace(f"{Config.SONARQUBE_PROJECT_KEY}:", "")
            repo_path = Config.GIT_REPO_PATH
            full_file_path = str((Path(repo_path) / file_path).resolve())

            smell_info = json.dumps({
                "key": smell_data.get("key"), "rule": smell_data.get("rule"),
                "message": smell_data.get("message"), "type": smell_data.get("type"),
                "line": smell_data.get("line"), "file_path": full_file_path,
                "effort": smell_data.get("effort"),
            }, ensure_ascii=False)

            cli_available = shutil.which("claude") is not None
            cli_hint = ("Claude Code CLI 已确认可用，请直接调用 claude_code_fix。" if cli_available
                        else "警告：当前环境未检测到 Claude Code CLI。")
            user_msg = (f"{cli_hint}\n\n请处理以下代码异味：\n{smell_info}\n\n"
                        f"文件完整路径: {full_file_path}\nGit仓库路径: {repo_path}\n"
                        f"分支名: {branch_name}\n负责人GUID: {assignee_guid}")

            response: AgentResponse = asyncio.run(self._agent.run(user_msg))
            result_text = response.text or str(response)
            fix_result = self._extract_result(result_text)

            if fix_result.get("success"):
                state["fix_solution"] = {
                    "filePath": fix_result.get("file_path", file_path),
                    "assignee": assignee_guid, "codeDiff": "",
                    "smellKey": smell_data.get("key"),
                    "description": fix_result.get("summary", "Agent 自主修复完成"),
                    "line": smell_data.get("line"), "effort": smell_data.get("effort"),
                    "executionSummary": fix_result.get("summary", ""),
                }
                state["current_step"] = "pr_creation"
                state["completed_steps"].append("agent_fix")
                console.print(f"[green]SmellFixAgent 修复成功: {fix_result.get('summary', '')}[/green]")
            else:
                error_msg = fix_result.get("summary", "Agent 修复失败")
                state["error_info"] = error_msg
                state["fix_solution"] = {
                    "filePath": file_path, "assignee": assignee_guid, "codeDiff": "",
                    "smellKey": smell_data.get("key"), "description": error_msg,
                    "line": smell_data.get("line"), "effort": smell_data.get("effort"),
                }
                console.print(f"[red]SmellFixAgent 修复失败: {error_msg}[/red]")
            return state

        except Exception as e:
            error_msg = f"SmellFixAgent 执行异常: {e}"
            console.print(f"[red]{error_msg}[/red]")
            state["error_info"] = error_msg
            return state

    def _extract_result(self, text: str) -> dict:
        text_lower = text.lower()
        if "success" in text_lower and ("commit" in text_lower or "修复成功" in text_lower or "修改了" in text_lower):
            return {"success": True, "summary": text[:600], "file_path": ""}
        if "失败" in text_lower or "failed" in text_lower:
            return {"success": False, "summary": text[:600]}
        return {"success": True, "summary": text[:600], "file_path": ""}

    def _load_email_to_guid(self) -> dict:
        try:
            with open(Config.EMAIL_TO_GUID_PATH, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            return {}
