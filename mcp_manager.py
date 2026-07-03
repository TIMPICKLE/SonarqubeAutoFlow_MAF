"""
MCP 管理器 - MAF 版本

原始项目在 main.py 中自建了 200+ 行的 MCPClient（event loop / daemon thread / AsyncExitStack）。
MAF 原生提供 MCPStdioTool / MCPStreamableHTTPTool 用于 Agent 工具调用，
但工作流中的确定性节点（issue_analysis / pr_creation）需要直接编程式调用 MCP 工具，
而非经过 LLM Agent 循环。

本模块提供一个轻量同步封装，复用 mcp SDK（MAF 内部同样依赖），
仅保留本项目需要的两个能力：查询 SonarQube issues、创建 Azure DevOps PR。
相比原始 MCPClient，去除了手动 event loop / thread 管理，代码量减少约 70%。
"""
import asyncio
import json
import threading
from typing import Any, Dict, Optional

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client
from config import Config
from rich.console import Console

console = Console()


class _MCPServerConn:
    """单个 MCP 服务器的会话封装"""
    def __init__(self, name: str, cfg: Dict[str, Any]):
        self.name = name
        self.cfg = cfg
        self._session: Optional[ClientSession] = None
        self._stack = None
        self._tool_cache: Dict[str, Dict] = {}

    async def _connect(self):
        from contextlib import AsyncExitStack
        self._stack = AsyncExitStack()
        command = self.cfg.get("command")
        args = self.cfg.get("args", [])
        env = self.cfg.get("env")
        params = StdioServerParameters(command=command, args=args, env=env)
        read_stream, write_stream = await self._stack.enter_async_context(stdio_client(params))
        self._session = await self._stack.enter_async_context(ClientSession(read_stream, write_stream))
        await self._session.initialize()
        console.print(f"[dim]MCP 服务器 {self.name} 已连接[/dim]")

    async def _list_tools(self):
        result = await self._session.list_tools()
        self._tool_cache = {t.name: t.model_dump() for t in result.tools}
        return self._tool_cache

    def _resolve(self, preferred, keywords=None):
        if not self._tool_cache:
            asyncio.get_event_loop().run_until_complete(self._list_tools())
        for c in preferred:
            if c in self._tool_cache:
                return c
        if keywords:
            for n in self._tool_cache:
                if all(k.lower() in n.lower() for k in keywords):
                    return n
        raise RuntimeError(f"未在 {self.name} 找到工具，候选: {list(self._tool_cache.keys())}")

    async def _call(self, tool_name, arguments):
        result = await self._session.call_tool(name=tool_name, arguments=arguments or {})
        if result.isError:
            msg = "".join(c.text for c in result.content if hasattr(c, "text"))
            raise RuntimeError(f"MCP 工具错误: {msg}")
        texts = [c.text for c in result.content if hasattr(c, "text")]
        combined = "\n".join(texts).strip()
        if not combined:
            return {}
        try:
            return json.loads(combined)
        except json.JSONDecodeError:
            return {"text": combined}

    async def _close(self):
        if self._stack:
            await self._stack.aclose()


class MCPManager:
    """轻量级 MCP 同步管理器（单 event loop + daemon thread，但逻辑极简）"""

    def __init__(self):
        config = Config.load_mcp_config()
        raw = config.get("mcpServers", {})
        self._servers = {n: _MCPServerConn(n, c) for n, c in raw.items() if not c.get("disabled")}
        self._loop = asyncio.new_event_loop()
        self._thread = threading.Thread(target=self._loop.run_forever, daemon=True)
        self._thread.start()
        import atexit
        atexit.register(self.close)
        console.print(f"[green]MCPManager 初始化，{len(self._servers)} 个服务器[/green]")

    def _run(self, coro):
        return asyncio.run_coroutine_threadsafe(coro, self._loop).result()

    def _ensure(self, name: str) -> _MCPServerConn:
        srv = self._servers[name]
        if srv._session is None:
            self._run(srv._connect())
        return srv

    def call_sonarqube_api(self, params: Dict[str, Any]) -> Dict[str, Any]:
        srv = self._ensure("sonarqube")
        tool_name = srv._resolve(
            preferred=["issues", "issues/search", "issues.search", "issues_search"],
            keywords=["issues"],
        )
        console.print(f"[cyan]通过 MCP 调用 SonarQube 工具 {tool_name}[/cyan]")
        result = self._run(srv._call(tool_name, params))
        if not isinstance(result, dict):
            raise RuntimeError("SonarQube 返回格式不正确")
        return result

    def call_azure_devops_api(self, action: str, params: Dict[str, Any]) -> Dict[str, Any]:
        if action != "create_pr":
            raise ValueError(f"不支持的 Azure DevOps 操作: {action}")
        srv = self._ensure("azureDevOps")
        tool_name = srv._resolve(
            preferred=["pullRequests/create", "pullrequests/create", "createPullRequest", "create_pull_request"],
            keywords=["pull", "create"],
        )
        console.print(f"[cyan]通过 MCP 调用 Azure DevOps 工具 {tool_name} 创建 PR[/cyan]")
        result = self._run(srv._call(tool_name, params))
        if not isinstance(result, dict):
            raise RuntimeError("Azure DevOps 返回格式不正确")
        return result

    def close(self):
        async def _shutdown():
            for srv in self._servers.values():
                try:
                    await srv._close()
                except Exception:
                    pass
        try:
            self._run(_shutdown())
        except Exception:
            pass
        self._loop.call_soon_threadsafe(self._loop.stop)
        if self._thread.is_alive():
            self._thread.join(timeout=5)
