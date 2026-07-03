"""
GLM 客户端 - MAF 版本
通过 Microsoft Agent Framework 的 OpenAIChatClient 接入 GLM (OpenAI 兼容接口)。
GLM 支持 OpenAI 兼容的 /v1/chat/completions 接口，因此可直接复用 OpenAIChatClient，
无需编写 Custom Provider。启用 function calling 后，MAF 的 Agent+Tool loop 可原生工作。
"""
from agent_framework.openai import OpenAIChatClient
from config import Config


def create_glm_client() -> OpenAIChatClient:
    """创建 GLM 的 MAF ChatClient (基于 OpenAI 兼容接口)"""
    return OpenAIChatClient(
        model=Config.GLM_MODEL,
        api_key=Config.GLM_API_KEY,
        base_url=Config.GLM_BASE_URL,
        instruction_role="system",
    )
