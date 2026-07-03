"""
修复类工具 - MAF FunctionTool 形式

将原始项目的 ClaudeCodeFixTool（调用本机 Claude Code CLI）封装为 MAF 可识别的工具。
原始 BaseTool 体系被 MAF 原生 FunctionTool 取代，无需 ToolRegistry 两阶段选择。
"""
import json
import os
import shutil
import subprocess
from datetime import datetime
from pathlib import Path
from typing import Annotated, Any, Dict, List
from pydantic import Field
from rich.console import Console

console = Console()
TEMP_LOG_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "TempLog")
os.makedirs(TEMP_LOG_DIR, exist_ok=True)
SKILLS_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), ".claude", "skills")


def _get_skill_for_file(file_path: str) -> str:
    ext = os.path.splitext(file_path)[1].lower()
    if ext == ".cs":
        return "abp-net-backend"
    if ext in {".ts", ".tsx", ".html", ".less", ".scss", ".css"}:
        fname = os.path.basename(file_path).lower()
        if any(p in fname for p in ["component", "service", "module", "directive", "pipe", "guard", "interceptor"]):
            return "angular-frontend"
        return "typescript-common"
    return ""


def _load_skill(name: str) -> str:
    if not name:
        return ""
    p = os.path.join(SKILLS_DIR, f"{name}.md")
    if os.path.exists(p):
        try:
            with open(p, "r", encoding="utf-8") as f:
                return f.read()
        except Exception:
            pass
    return ""


def _build_prompt(smell_description, file_path, line, rule, repo_path, extra_context):
    try:
        rel = Path(file_path).relative_to(Path(repo_path)).as_posix()
    except ValueError:
        rel = file_path.replace("\\", "/")
    skill = _load_skill(_get_skill_for_file(file_path))
    parts = [
        "请修复以下 SonarQube 代码异味。**不要创建新分支**，直接在当前分支修改文件。",
        "修复完成后**不要执行 git commit**，由调用方统一提交。",
        "",
        f"**文件**：{rel}",
    ]
    if line:
        parts.append(f"**行号**：{line}")
    if rule:
        parts.append(f"**规则 ID**：{rule}")
    parts += [f"**问题描述**：{smell_description}", "", "**修复要求**：",
        "1. 仔细阅读相关代码，确认问题根因",
        "2. 按照 SonarQube 规则的定义进行修复",
        "3. 确保修复后不破坏现有功能",
        "4. 如需同时修改多个文件，请一并处理",
        "5. 保持代码风格与项目一致"]
    if extra_context:
        parts += ["", f"**补充背景**：{extra_context}"]
    if skill:
        parts += ["", "---", f"**参考 Skill ({_get_skill_for_file(file_path)})**：", "", skill]
    return "\n".join(parts)


def _get_modified_files(repo_path: str) -> List[str]:
    try:
        import git as gitpython
        repo = gitpython.Repo(repo_path)
        changed = [item.a_path for item in repo.index.diff("HEAD")]
        changed += [item.a_path for item in repo.index.diff(None) if item.a_path not in changed]
        changed += [f for f in repo.untracked_files if f not in changed]
        return changed
    except Exception as e:
        console.print(f"[yellow]git diff 异常: {e}[/yellow]")
        return []


def _git_commit_and_push(repo_path, branch_name, commit_message):
    try:
        import git as gitpython
        repo = gitpython.Repo(repo_path)
        repo.git.add("-A")
        commit = repo.index.commit(commit_message)
        repo.git.push("origin", branch_name)
        return {"success": True, "commit_sha": commit.hexsha[:8]}
    except Exception as e:
        return {"success": False, "error": f"git 提交/推送失败: {e}"}


def claude_code_fix(
    smell_description: Annotated[str, Field(description="SonarQube 异味的完整描述（message + rule），越详细越好")],
    file_path: Annotated[str, Field(description="异味所在文件的完整路径")],
    repo_path: Annotated[str, Field(description="Git 仓库根目录路径")],
    branch_name: Annotated[str, Field(description="当前工作分支名（用于 git push）")],
    commit_message: Annotated[str, Field(description="Git 提交消息")],
    line: Annotated[int, Field(description="异味所在行号，0 表示未知")] = 0,
    rule: Annotated[str, Field(description="SonarQube 规则 ID，如 csharpsquid:S1481")] = "",
    extra_context: Annotated[str, Field(description="额外背景信息（可选）")] = "",
    max_turns: Annotated[int, Field(description="Claude Code 最大迭代轮数，默认 100")] = 100,
) -> str:
    """调用本机 Claude Code CLI 修复代码异味（支持多文件修改）。
    修复完成后自动执行 git add -A、commit 和 push。
    适用于所有类型的异味修复——无论简单还是复杂、单文件还是多文件。"""
    claude_path = shutil.which("claude")
    if not claude_path:
        return json.dumps({"success": False, "error": "未找到 claude CLI，请先安装并登录 Claude Code"}, ensure_ascii=False)

    prompt = _build_prompt(smell_description, file_path, line, rule, repo_path, extra_context)
    cmd = [claude_path, "-p", "--dangerously-skip-permissions", "--max-turns", str(max_turns)]
    console.print(f"[cyan]claude_code_fix 开始执行，文件: {file_path}[/cyan]")

    log_entry = {"timestamp": datetime.now().isoformat(), "input": {"file_path": file_path, "branch": branch_name}, "steps": []}
    try:
        result = subprocess.run(cmd, cwd=repo_path, input=prompt, capture_output=True, text=True, timeout=300, encoding="utf-8", errors="replace")
    except subprocess.TimeoutExpired:
        return json.dumps({"success": False, "error": "Claude Code 执行超时（300秒）"}, ensure_ascii=False)
    except Exception as e:
        return json.dumps({"success": False, "error": f"调用失败: {e}"}, ensure_ascii=False)

    if result.returncode != 0:
        return json.dumps({"success": False, "error": f"claude CLI 返回码 {result.returncode}", "output": result.stdout[:400]}, ensure_ascii=False)

    modified = _get_modified_files(repo_path)
    if not modified:
        return json.dumps({"success": False, "error": "未检测到文件变更", "output": result.stdout[:800]}, ensure_ascii=False)

    commit_result = _git_commit_and_push(repo_path, branch_name, commit_message)
    if not commit_result["success"]:
        return json.dumps(commit_result, ensure_ascii=False)

    final = {"success": True, "files_modified": modified, "commit_sha": commit_result.get("commit_sha", ""),
             "summary": result.stdout[:600],
             "message": f"Claude Code 修复成功：修改了 {len(modified)} 个文件，已提交 {commit_result.get('commit_sha', '')}"}
    log_entry["final_result"] = final
    try:
        with open(os.path.join(TEMP_LOG_DIR, f"claude_fix_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"), "w", encoding="utf-8") as f:
            json.dump(log_entry, f, ensure_ascii=False, indent=2, default=str)
    except Exception:
        pass
    return json.dumps(final, ensure_ascii=False)
