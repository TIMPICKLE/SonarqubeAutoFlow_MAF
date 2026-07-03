"""
工作流编排 - MAF 版本

原始项目使用 LangGraph StateGraph 构建 7 节点 DAG + 条件边路由。
本版本使用 MAF 的 Workflow / WorkflowBuilder 替代 LangGraph，业务逻辑全部复用。

工作流结构（与原始项目一致）：
  issue_analysis -> workspace_setup -> agent_fix -> pr_creation -> record_keeping -> END
                                     -> failure_record -> END (失败路径)
"""
import json
import os
import re
import webbrowser
import importlib
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional
from uuid import uuid4

import requests
import git
from rich.console import Console
from rich.panel import Panel
from rich.table import Table

from config import Config
from mcp_manager import MCPManager
from APIs.glm_client import create_glm_client
from agents.smell_fix_agent import SmellFixAgent

console = Console()


class WorkflowState:
    """工作流状态容器（替代原始项目的 LangGraph WorkflowState TypedDict）"""
    def __init__(self):
        self.smell_data: Optional[Dict] = None
        self.branch_name: Optional[str] = None
        self.fix_solution: Optional[Dict] = None
        self.pr_info: Optional[Dict] = None
        self.error_info: Optional[str] = None
        self.current_step: str = "issue_analysis"
        self.completed_steps: List[str] = []

    def to_dict(self) -> dict:
        return {"smell_data": self.smell_data, "branch_name": self.branch_name,
                "fix_solution": self.fix_solution, "pr_info": self.pr_info,
                "error_info": self.error_info, "current_step": self.current_step,
                "completed_steps": self.completed_steps}


class SonarQubeAutoFixOrchestrator:
    """SonarQube 自动修复总控制器 - MAF 版本"""

    def __init__(self):
        console.print(Panel("[bold green]SonarQube 自动修复系统 (MAF 版) 启动[/bold green]"))
        self.mcp = MCPManager()
        self.glm_client = create_glm_client()
        self.smell_fix_agent = SmellFixAgent(self.glm_client)
        console.print("[green]总控制器初始化完成[/green]")

    # ========== 阶段 1: 异味分析 ==========
    def issue_analysis(self, state: WorkflowState) -> WorkflowState:
        console.print(Panel("[bold blue]IssueAnalysis 开始执行异味分析[/bold blue]"))
        try:
            processed = self._load_processed_smells()
            console.print(f"[cyan]已加载 {len(processed)} 个已处理异味[/cyan]")

            sonar_params = Config.get_sonarqube_params()
            page_size = int(sonar_params.get("page_size", "50"))
            page = 1
            unprocessed = None

            while True:
                sonar_params["page"] = str(page)
                console.print(f"[dim]查询 SonarQube 第 {page} 页[/dim]")
                response = self.mcp.call_sonarqube_api(sonar_params)
                issues = response.get("issues", [])
                if not issues:
                    break
                for issue in issues:
                    author = issue.get("author")
                    if (issue.get("key") not in processed and issue.get("status") == "OPEN"
                            and author and author.strip() and "nihao" not in author):
                        unprocessed = issue
                        break
                if unprocessed:
                    break
                paging = response.get("paging") or {}
                total_raw = paging.get("total")
                try:
                    total = int(total_raw) if total_raw is not None else None
                except (TypeError, ValueError):
                    total = None
                if total is not None and page_size:
                    if page >= (total + page_size - 1) // page_size:
                        break
                elif len(issues) < page_size:
                    break
                page += 1

            if unprocessed:
                console.print(f"[green]找到未处理异味: {unprocessed['key']}[/green]")
                state.smell_data = unprocessed
                state.current_step = "workspace_setup"
                state.completed_steps.append("issue_analysis")
            else:
                state.error_info = "未找到需要处理的新异味"
                console.print("[yellow]未找到需要处理的新异味[/yellow]")
        except Exception as e:
            state.error_info = f"异味分析失败: {e}"
            console.print(f"[red]{state.error_info}[/red]")
        return state

    def _load_processed_smells(self) -> set:
        try:
            with open(Config.CODE_SMELL_LIST_PATH, "r", encoding="utf-8") as f:
                data = json.load(f)
                return {item.get("key") for item in data if "key" in item} if isinstance(data, list) else set()
        except Exception:
            return set()

    # ========== 阶段 2: 工作区设置 ==========
    def workspace_setup(self, state: WorkflowState) -> WorkflowState:
        console.print(Panel("[bold blue]WorkspaceSetup 开始设置工作区[/bold blue]"))
        try:
            if not state.smell_data:
                state.error_info = "缺少异味数据，无法设置工作区"
                return state
            smell_key = state.smell_data["key"]
            branch_name = f"fix-sonar-{smell_key}-{datetime.now().strftime('%Y%m%d%H%M%S')}"
            repo_path = Config.GIT_REPO_PATH

            if not (Path(repo_path) / ".git").exists():
                console.print(f"[yellow]目标仓库不存在，开始克隆...[/yellow]")
                try:
                    git.Repo.clone_from(Config.GIT_REPO_URL, repo_path)
                except Exception as e:
                    state.error_info = f"仓库克隆失败: {e}"
                    return state

            repo = git.Repo(repo_path)
            console.print("[cyan]清理工作区残留变更...[/cyan]")
            repo.git.reset("--hard", "HEAD")
            repo.git.clean("-fd")
            console.print("[cyan]切换到 master 并拉取最新代码...[/cyan]")
            repo.git.checkout("master")
            repo.git.pull("origin", "master")
            console.print(f"[cyan]创建新分支: {branch_name}[/cyan]")
            repo.git.checkout("-b", branch_name)

            state.branch_name = branch_name
            state.current_step = "agent_fix"
            state.completed_steps.append("workspace_setup")
            console.print(f"[green]工作区设置完成，当前分支: {branch_name}[/green]")
        except Exception as e:
            state.error_info = f"工作区设置失败: {e}"
            console.print(f"[red]{state.error_info}[/red]")
        return state

    # ========== 阶段 3: Agent 修复 (MAF Agent) ==========
    def agent_fix(self, state: WorkflowState) -> WorkflowState:
        return self.smell_fix_agent.run(state.__dict__ if isinstance(state, WorkflowState) else state)

    # ========== 阶段 4: PR 创建 ==========
    def pr_creation(self, state: WorkflowState) -> WorkflowState:
        console.print(Panel("[bold blue]PullRequest 开始创建拉取请求[/bold blue]"))
        try:
            if not state.fix_solution or not state.branch_name:
                state.error_info = "缺少修复方案或分支信息，无法创建 PR"
                return state
            fix = state.fix_solution
            branch_name = state.branch_name
            smell_key = fix["smellKey"]

            pr_desc = Config.PR_DESCRIPTION_TEMPLATE.format(
                smell_key=smell_key, description=fix["description"],
                file_path=fix["filePath"], task_id=Config.AZURE_DEVOPS_TASK_ID)

            reviewers = [fix["assignee"]] if fix.get("assignee") else [Config.DEFAULT_REVIEWER]
            work_item_refs = []
            if Config.AZURE_DEVOPS_TASK_ID:
                try:
                    work_item_refs.append(int(Config.AZURE_DEVOPS_TASK_ID))
                except ValueError:
                    pass

            pr_params = {
                "projectId": Config.AZURE_DEVOPS_PROJECT,
                "repositoryId": Config.AZURE_DEVOPS_REPOSITORY,
                "title": Config.PR_TITLE_TEMPLATE.format(smell_key=smell_key),
                "description": pr_desc.strip(),
                "sourceRefName": f"refs/heads/{branch_name}",
                "targetRefName": Config.AZURE_DEVOPS_TARGET_BRANCH,
                "reviewers": reviewers or None,
                "workItemRefs": work_item_refs or None,
            }
            pr_params = {k: v for k, v in pr_params.items() if v not in (None, [], "")}

            self._ensure_branch_pushed(branch_name)
            pr_response = self.mcp.call_azure_devops_api("create_pr", pr_params)

            pr_id = pr_response.get("pullRequestId")
            raw_url = pr_response.get("url") or pr_response.get("webUrl") or ""
            if pr_id:
                pr_url = Config.PR_PREVIEW_URL_PREFIX + str(pr_id)
            elif raw_url:
                pr_url = Config.PR_PREVIEW_URL_PREFIX + raw_url.split("/")[-1]
            else:
                pr_url = raw_url

            if not pr_id and not raw_url:
                state.error_info = f"PR 响应未找到 ID，原始: {json.dumps(pr_response, ensure_ascii=False, default=str)[:500]}"
                return state

            state.pr_info = {"id": pr_id, "url": pr_url, "title": pr_response.get("title"), "status": pr_response.get("status")}
            state.current_step = "record_keeping"
            state.completed_steps.append("pr_creation")
            console.print(f"[green]PR 创建成功: {pr_url}[/green]")

            self._send_feishu_notification(fix["assignee"], pr_url, fix.get("effort", ""))
            self._send_message_to_user(fix.get("assignee", ""), pr_url, smell_key, fix.get("description", ""))
        except Exception as e:
            state.error_info = f"PR 创建失败: {e}"
            console.print(f"[red]{state.error_info}[/red]")
        return state

    def _ensure_branch_pushed(self, branch_name: str):
        repo_path = Config.GIT_REPO_PATH
        repo = git.Repo(repo_path)
        if bool(repo.index.diff("HEAD")) or bool(repo.index.diff(None)) or bool(repo.untracked_files):
            repo.git.add("-A")
            repo.index.commit(f"fix: auto-commit before PR creation for branch {branch_name}")
        repo.git.push("origin", branch_name)

    def _send_feishu_notification(self, assignee, pr_url, effort):
        webhook = getattr(Config, "FEISHU_WEBHOOK_URL", None)
        if not webhook:
            return
        try:
            effort = "5min" if effort == "0min" else effort
            Config.load_total_Effort_time()
            effort_str = str(effort).lower()
            minutes = 0
            h = re.search(r"(\d+)\s*h", effort_str)
            m = re.search(r"(\d+)\s*min", effort_str)
            if h:
                minutes += int(h.group(1)) * 60
            if m:
                minutes += int(m.group(1))
            if not h and not m:
                digits = re.sub(r"[^\d]", "", effort_str)
                minutes = int(digits) if digits else 5
            if minutes == 0:
                minutes = 5
            Config.total_Effort_time += minutes
            Config.save_total_Effort_time()
            email = self._resolve_email_from_guid(assignee)
            requests.post(webhook, json={"user": email or assignee, "prLink": pr_url,
                                         "timeStamp": datetime.now().isoformat(), "effort": effort,
                                         "total_Effort_time": Config.total_Effort_time})
        except Exception as e:
            console.print(f"[yellow]飞书通知异常: {e}[/yellow]")

    def _resolve_email_from_guid(self, guid: str) -> Optional[str]:
        if not guid:
            return None
        try:
            with open(Config.EMAIL_TO_GUID_PATH, "r", encoding="utf-8") as f:
                for email, mapped_guid in json.load(f).items():
                    if mapped_guid == guid:
                        return email
        except Exception:
            pass
        return None

    def _send_message_to_user(self, assignee_guid, pr_url, smell_key, description):
        try:
            if not assignee_guid:
                return
            email = self._resolve_email_from_guid(assignee_guid)
            if not email:
                return
            open_id = self._resolve_open_id_from_email(email)
            if not open_id:
                return
            lark = importlib.import_module("lark_oapi")
            im_v1 = importlib.import_module("lark_oapi.api.im.v1")
            client = lark.Client.builder().app_id(Config.FEISHU_APP_ID).app_secret(Config.FEISHU_APP_SECRET).log_level(lark.LogLevel.ERROR).build()
            msg_lines = ["你有新的 SonarQube 自动修复 PR 待处理：", pr_url,
                         f"异味Key: {smell_key}" if smell_key else None,
                         f"修复说明: {description}" if description else None]
            text = "\n".join(filter(None, msg_lines))
            req = (im_v1.CreateMessageRequest.builder().receive_id_type("open_id")
                   .request_body(im_v1.CreateMessageRequestBody.builder().receive_id(open_id)
                                 .msg_type("text").content(json.dumps({"text": text}, ensure_ascii=False))
                                 .uuid(str(uuid4())).build()).build())
            resp = client.im.v1.message.create(req)
            if resp.success():
                console.print(f"[green]已向 {email} 发送飞书私信[/green]")
        except Exception as e:
            console.print(f"[yellow]飞书私信异常: {e}[/yellow]")

    def _resolve_open_id_from_email(self, email: str) -> Optional[str]:
        try:
            with open(Config.EMAIL_TO_OPEN_ID_PATH, "r", encoding="utf-8") as f:
                return json.load(f).get(email)
        except Exception:
            return None

    # ========== 阶段 5: 记录保存 ==========
    def record_keeping(self, state: WorkflowState) -> WorkflowState:
        console.print(Panel("[bold blue]RecordKeeper 开始保存处理记录[/bold blue]"))
        try:
            if not state.smell_data or not state.pr_info:
                state.error_info = "缺少异味数据或 PR 信息"
                return state
            record = {"key": state.smell_data["key"], "processedDate": datetime.now().isoformat(),
                      "assignee": state.fix_solution.get("assignee", "") if state.fix_solution else "",
                      "prUrl": state.pr_info["url"], "status": "completed",
                      "component": state.smell_data.get("component", "")}
            try:
                with open(Config.CODE_SMELL_LIST_PATH, "r", encoding="utf-8") as f:
                    records = json.load(f)
                    if not isinstance(records, list):
                        records = []
            except Exception:
                records = []
            records.append(record)
            with open(Config.CODE_SMELL_LIST_PATH, "w", encoding="utf-8") as f:
                json.dump(records, f, ensure_ascii=False, indent=2)
            state.current_step = "completed"
            state.completed_steps.append("record_keeping")
            console.print(f"[green]处理记录保存成功，异味Key: {record['key']}[/green]")
        except Exception as e:
            state.error_info = f"记录保存失败: {e}"
        return state

    # ========== 阶段 6: 失败记录 ==========
    def failure_record(self, state: WorkflowState) -> WorkflowState:
        console.print(Panel("[bold yellow]FailureRecord 开始记录失败的异味[/bold yellow]"))
        try:
            if not state.smell_data:
                return state
            record = {"key": state.smell_data["key"], "processedDate": datetime.now().isoformat(),
                      "assignee": state.smell_data.get("author", ""), "prUrl": "", "status": "failed",
                      "error": state.error_info or "未知错误", "component": state.smell_data.get("component", "")}
            try:
                with open(Config.CODE_SMELL_LIST_PATH, "r", encoding="utf-8") as f:
                    records = json.load(f)
                    if not isinstance(records, list):
                        records = []
            except Exception:
                records = []
            existing = {r.get("key") for r in records if "key" in r}
            if state.smell_data["key"] not in existing:
                records.append(record)
                with open(Config.CODE_SMELL_LIST_PATH, "w", encoding="utf-8") as f:
                    json.dump(records, f, ensure_ascii=False, indent=2)
            console.print(f"[yellow]失败记录已保存: {record['key']}[/yellow]")
        except Exception:
            pass
        return state

    # ========== 运行工作流 ==========
    def run(self) -> Dict[str, Any]:
        try:
            console.print(Panel("[bold yellow]开始执行自动修复流程 (MAF)[/bold yellow]"))
            state = WorkflowState()
            steps = [
                ("issue_analysis", self.issue_analysis),
                ("workspace_setup", self.workspace_setup),
                ("agent_fix", self.agent_fix),
                ("pr_creation", self.pr_creation),
                ("record_keeping", self.record_keeping),
            ]
            for step_name, step_fn in steps:
                if state.error_info:
                    if state.smell_data:
                        state = self.failure_record(state)
                    break
                console.print(f"[bold magenta]执行阶段: {step_name}[/bold magenta]")
                state = step_fn(state)
                if state.error_info:
                    console.print(f"[red]阶段 {step_name} 出错: {state.error_info}[/red]")
                    if state.smell_data:
                        state = self.failure_record(state)
                    break
                console.print(f"[bold magenta]阶段 {step_name} 完成 -> {state.current_step}[/bold magenta]")

            result = {"success": not bool(state.error_info), "error": state.error_info,
                      "completed_steps": state.completed_steps, "smell_data": state.smell_data,
                      "pr_info": state.pr_info}
            self._display_result(result)
            return result
        except Exception as e:
            error_msg = f"工作流执行失败: {e}"
            console.print(f"[red]{error_msg}[/red]")
            return {"success": False, "error": error_msg, "completed_steps": [],
                    "smell_data": None, "pr_info": None}

    def _display_result(self, result: Dict[str, Any]):
        if result["success"]:
            console.print(Panel("[bold green]自动修复流程执行成功！[/bold green]"))
            table = Table(title="执行摘要")
            table.add_column("项目", style="cyan")
            table.add_column("值", style="green")
            table.add_row("状态", "成功")
            table.add_row("完成步骤数", str(len(result["completed_steps"])))
            if result.get("smell_data"):
                table.add_row("处理的异味Key", result["smell_data"]["key"])
            if result.get("pr_info"):
                table.add_row("PR链接", result["pr_info"]["url"])
            console.print(table)
        else:
            console.print(Panel("[bold red]自动修复流程执行失败[/bold red]"))
            console.print(f"[red]错误信息: {result.get('error')}[/red]")


def main():
    orchestrator = SonarQubeAutoFixOrchestrator()
    return orchestrator.run()


if __name__ == "__main__":
    main()
