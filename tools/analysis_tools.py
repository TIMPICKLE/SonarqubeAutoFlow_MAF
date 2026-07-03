"""
分析类工具 - MAF FunctionTool 形式
异味分类与复杂度评估，供 Agent 辅助理解异味上下文。
"""
import re
from typing import Annotated, List
from pydantic import Field

TYPE_RULES = {
    "naming": ["naming", "name", "identifier", "convention", "rename", "s101", "s100"],
    "duplication": ["duplicate", "duplication", "copy", "identical", "s1192"],
    "complexity": ["complexity", "cognitive", "nested", "cyclomatic", "s1541", "s3776", "s1066"],
    "unused": ["unused", "dead", "unreachable", "redundant", "s1144", "s1481", "s125"],
    "style": ["format", "indent", "whitespace", "brace", "s1105", "s3626"],
}


def analyze_smell_type(
    rule: Annotated[str, Field(description="SonarQube 规则标识，如 csharpsquid:S101")],
    message: Annotated[str, Field(description="SonarQube 异味消息描述")],
) -> str:
    """分析 SonarQube 异味的类型和修复难度。
    返回异味分类、推荐的工具调用链和预估难度，帮助了解异味上下文。"""
    combined = (rule + " " + message).lower()
    best_type, best_score = "unknown", 0
    for smell_type, keywords in TYPE_RULES.items():
        score = sum(1 for kw in keywords if kw.lower() in combined)
        if score > best_score:
            best_score, best_type = score, smell_type
    chains = {
        "naming": ["claude_code_fix"],
        "unused": ["read_source_code", "claude_code_fix"],
        "style": ["read_source_code", "claude_code_fix"],
        "complexity": ["read_full_file", "analyze_complexity", "claude_code_fix"],
        "duplication": ["search_similar_patterns", "read_full_file", "claude_code_fix"],
    }
    difficulty = {"naming": "low", "style": "low", "unused": "medium", "complexity": "high", "duplication": "high"}
    import json
    return json.dumps({
        "type": best_type,
        "recommended_tools": chains.get(best_type, ["read_source_code", "claude_code_fix"]),
        "estimated_difficulty": difficulty.get(best_type, "medium"),
    }, ensure_ascii=False)


def analyze_complexity(
    file_path: Annotated[str, Field(description="目标文件的完整路径")],
    line: Annotated[int, Field(description="异味所在行号")],
    smell_rule: Annotated[str, Field(description="SonarQube 规则标识")] = "",
) -> str:
    """分析指定文件和行号附近代码的复杂度，返回复杂度评分和建议的修复策略。"""
    try:
        with open(file_path, "r", encoding="utf-8") as f:
            lines = f.readlines()
        start, end = max(0, line - 16), min(len(lines), line + 15)
        snippet = "".join(lines[start:end])
    except Exception:
        import json
        return json.dumps({"complexity_score": 0, "suggestion": "quick_fix", "error": "无法读取文件"}, ensure_ascii=False)

    nesting, depth, current = 0, 0, 0
    for ch in snippet:
        if ch == "{":
            current += 1; depth = max(depth, current)
        elif ch == "}":
            current = max(0, current - 1)
    method_lines = len([l for l in snippet.splitlines() if l.strip()])
    complex_logic = sum(1 for ind in ["&&", "||", "? ", "switch", "case "] if ind.lower() in snippet.lower()) >= 2
    score = 1
    score += 3 if method_lines > 50 else (2 if method_lines > 30 else (1 if method_lines > 15 else 0))
    score += 3 if depth > 4 else (2 if depth > 2 else (1 if depth > 1 else 0))
    import json
    return json.dumps({
        "complexity_score": min(score, 10),
        "metrics": {"lines_in_method": method_lines, "nesting_depth": depth, "has_complex_logic": complex_logic},
        "suggestion": "quick_fix" if score <= 4 else "deep_analysis",
        "code_snippet": snippet[:2000],
    }, ensure_ascii=False)
