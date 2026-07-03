"""
代码读取类工具 - MAF FunctionTool 形式
源代码片段读取和模式搜索，供 Agent 辅助理解代码上下文。
"""
import os
import re
from pathlib import Path
from typing import Annotated, List
from pydantic import Field
import json


def read_source_code(
    file_path: Annotated[str, Field(description="文件完整路径")],
    line: Annotated[int, Field(description="目标行号（1-based）")],
    radius: Annotated[int, Field(description="上下文半径，默认15")] = 15,
) -> str:
    """读取指定文件中某一行号附近的代码片段。适用于只需查看异味相关的局部代码。"""
    try:
        with open(file_path, "r", encoding="utf-8") as f:
            lines = f.readlines()
        total = len(lines)
        start, end = max(0, line - radius - 1), min(total, line + radius)
        snippet = "".join(lines[start:end])
        lang = Path(file_path).suffix.lstrip(".") or "text"
        return json.dumps({"code": snippet, "start_line": start + 1, "end_line": end, "total_lines": total, "language": lang}, ensure_ascii=False)
    except FileNotFoundError:
        return json.dumps({"error": f"文件不存在: {file_path}", "code": ""}, ensure_ascii=False)
    except Exception as e:
        return json.dumps({"error": str(e), "code": ""}, ensure_ascii=False)


def read_full_file(
    file_path: Annotated[str, Field(description="文件完整路径")],
) -> str:
    """读取整个文件的全部内容。适用于需要理解整个文件上下文的复杂重构场景。"""
    try:
        with open(file_path, "r", encoding="utf-8") as f:
            content = f.read()
        return json.dumps({"content": content, "total_lines": len(content.splitlines()), "language": Path(file_path).suffix.lstrip(".") or "text", "file_size": len(content)}, ensure_ascii=False)
    except FileNotFoundError:
        return json.dumps({"error": f"文件不存在: {file_path}", "content": ""}, ensure_ascii=False)
    except Exception as e:
        return json.dumps({"error": str(e), "content": ""}, ensure_ascii=False)


def search_similar_patterns(
    pattern: Annotated[str, Field(description="要搜索的文本或正则表达式模式")],
    search_path: Annotated[str, Field(description="搜索的目录路径")],
    file_extensions: Annotated[str, Field(description="文件扩展名过滤，多个用逗号分隔，如 .cs,.java")] = "",
    max_results: Annotated[int, Field(description="最大结果数，默认20")] = 20,
) -> str:
    """在指定目录中搜索与给定模式匹配的代码位置。适用于查找重复代码或类似模式。"""
    matches: List[dict] = []
    extensions = [e.strip() for e in file_extensions.split(",") if e.strip()] if file_extensions else []
    try:
        compiled = re.compile(pattern, re.IGNORECASE)
    except re.error:
        compiled = re.compile(re.escape(pattern), re.IGNORECASE)
    try:
        for dirpath, _dirs, files in os.walk(search_path):
            if any(s in dirpath for s in [".git", "node_modules", "bin", "obj", ".vs"]):
                continue
            for fname in files:
                if extensions and not any(fname.endswith(e) for e in extensions):
                    continue
                fpath = os.path.join(dirpath, fname)
                try:
                    with open(fpath, "r", encoding="utf-8", errors="ignore") as f:
                        for lineno, linecontent in enumerate(f, 1):
                            if compiled.search(linecontent):
                                matches.append({"file": fpath, "line": lineno, "content": linecontent.strip()[:200]})
                                if len(matches) >= max_results:
                                    break
                except Exception:
                    continue
                if len(matches) >= max_results:
                    break
            if len(matches) >= max_results:
                break
    except Exception as e:
        return json.dumps({"error": str(e), "matches": [], "count": 0}, ensure_ascii=False)
    return json.dumps({"matches": matches, "count": len(matches), "truncated": len(matches) >= max_results}, ensure_ascii=False)
