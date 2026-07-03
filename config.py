"""配置文件 - MAF 版本"""
import os, json
from typing import Dict, Any
from dotenv import load_dotenv
load_dotenv(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".env"))

class Config:
    PROJECT_ROOT = os.path.dirname(os.path.abspath(__file__))
    MCP_CONFIG_PATH = os.path.join(PROJECT_ROOT, "localJSON", "mcp.json")
    CODE_SMELL_LIST_PATH = os.path.join(PROJECT_ROOT, "localJSON", "codeSmallList.json")
    EMAIL_TO_GUID_PATH = os.path.join(PROJECT_ROOT, "localJSON", "emailToGuid.json")
    EMAIL_TO_OPEN_ID_PATH = os.path.join(PROJECT_ROOT, "localJSON", "emialtoOpenId.json")
    TOTAL_EFFORT_STATE_PATH = os.path.join(PROJECT_ROOT, "localJSON", "effort_state.json")
    total_Effort_time = 0
    GLM_BASE_URL = os.environ.get("GLM_BASE_URL", "https://ai-infra.united-imaging.com")
    GLM_API_KEY = os.environ.get("GLM_API_KEY", "YOUR_GLM_API_KEY")
    GLM_MODEL = os.environ.get("GLM_MODEL", "glm-5")
    GLM_TEMPERATURE = float(os.environ.get("GLM_TEMPERATURE", "0.3"))
    SONARQUBE_PROJECT_KEY = "WebOIS_wemr-host-csharp"
    SONARQUBE_BRANCH = "master"
    SONARQUBE_SEVERITIES = ["CRITICAL"]
    SONARQUBE_TYPES = ["CODE_SMELL"]
    AZURE_DEVOPS_TARGET_BRANCH = "refs/heads/master"
    AZURE_DEVOPS_TASK_ID = "283356"
    AZURE_DEVOPS_PROJECT = "WebOIS"
    AZURE_DEVOPS_REPOSITORY = "WebOIS"
    FEISHU_APP_ID = os.environ.get("FEISHU_APP_ID", "YOUR_FEISHU_APP_ID")
    FEISHU_APP_SECRET = os.environ.get("FEISHU_APP_SECRET", "YOUR_FEISHU_APP_SECRET")
    GIT_REPO_URL = "https://navi.united-imaging.com/RT/WebOIS/_git/WebOIS"
    GIT_COMMIT_MESSAGE_TEMPLATE = "fix: 解决SonarQube异味 {smell_key} - {description}"
    GIT_BRANCH_NAME_TEMPLATE = "fix-sonar-{smell_key}"
    GIT_REPO_PATH = os.path.join(PROJECT_ROOT, "WebOIS")
    PR_TITLE_TEMPLATE = "fix: 解决SonarQube异味 {smell_key}"
    PR_PREVIEW_URL_PREFIX = "https://navi.united-imaging.com/RT/WebOIS/_git/WebOIS/pullrequest/"
    DEFAULT_REVIEWER = "a31b511e-6b0f-4894-9c33-c5df5c98608f"
    PR_DESCRIPTION_TEMPLATE = "## SonarQube代码异味修复\n\n**异味Key:** {smell_key}\n**修复描述:** {description}\n**修复文件:** {file_path}\n\n### 相关信息\n- Task ID: {task_id}\n- 自动化修复系统生成\n\n### 检查清单\n- [x] 代码修复已应用\n- [x] 修复逻辑已验证\n- [ ] 人工审核通过\n"
    LOG_LEVEL = "INFO"

    @classmethod
    def load_total_Effort_time(cls):
        try:
            with open(cls.TOTAL_EFFORT_STATE_PATH, "r", encoding="utf-8") as f:
                cls.total_Effort_time = int(json.load(f).get("total_Effort_time", 0))
        except Exception:
            cls.total_Effort_time = 0

    @classmethod
    def save_total_Effort_time(cls):
        os.makedirs(os.path.dirname(cls.TOTAL_EFFORT_STATE_PATH), exist_ok=True)
        with open(cls.TOTAL_EFFORT_STATE_PATH, "w", encoding="utf-8") as f:
            json.dump({"total_Effort_time": int(cls.total_Effort_time)}, f, ensure_ascii=False, indent=2)

    @classmethod
    def get_sonarqube_params(cls) -> Dict[str, Any]:
        params = {"project_key": cls.SONARQUBE_PROJECT_KEY, "branch": cls.SONARQUBE_BRANCH, "severities": cls.SONARQUBE_SEVERITIES, "types": cls.SONARQUBE_TYPES, "s": "CREATION_DATE", "asc": False, "page": "1", "page_size": "50", "status": "OPEN"}
        return {k: v for k, v in params.items() if v is not None}

    @classmethod
    def get_pr_labels(cls) -> list:
        return ["bug-fix", "sonarqube", "automated"]

    @classmethod
    def load_mcp_config(cls) -> Dict[str, Any]:
        try:
            with open(cls.MCP_CONFIG_PATH, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            return {"mcpServers": {}}
