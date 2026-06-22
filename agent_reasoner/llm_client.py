import json
import os
import re
import time

import requests


class LLMClient:
    """DeepSeek API 封装，兼容 OpenAI chat completions 格式。"""

    DEFAULT_BASE_URL = "https://api.deepseek.com/chat/completions"
    DEFAULT_MODEL = "deepseek-chat"

    def __init__(
        self,
        api_key: str | None = None,
        base_url: str | None = None,
        model: str | None = None,
    ):
        self.api_key = api_key or os.getenv("DEEPSEEK_API_KEY", "")
        self.base_url = base_url or self.DEFAULT_BASE_URL
        self.model = model or self.DEFAULT_MODEL

        if not self.api_key:
            raise ValueError(
                "DeepSeek API key 未设置。请设置环境变量 DEEPSEEK_API_KEY 或传入 api_key 参数。"
            )

    def chat(
        self,
        messages: list[dict],
        temperature: float = 0.7,
        max_tokens: int = 2048,
        max_retries: int = 3,
    ) -> str:
        """发送聊天请求，返回助手回复文本。遇到 429 自动指数退避重试。"""
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }
        payload = {
            "model": self.model,
            "messages": messages,
            "temperature": temperature,
            "max_tokens": max_tokens,
        }

        for attempt in range(max_retries):
            resp = requests.post(self.base_url, headers=headers, json=payload, timeout=60)
            if resp.status_code == 429:
                wait = 2 ** attempt
                print(f"⏳ 请求限流，{wait}秒后重试（{attempt + 1}/{max_retries}）...")
                time.sleep(wait)
                continue
            resp.raise_for_status()
            data = resp.json()
            return data["choices"][0]["message"]["content"]

        resp.raise_for_status()

    def chat_json(
        self,
        messages: list[dict],
        temperature: float = 0.3,
        max_tokens: int = 2048,
    ) -> dict:
        """发送聊天请求并解析 JSON 响应。自动从 markdown 代码块中提取 JSON。"""
        text = self.chat(messages, temperature=temperature, max_tokens=max_tokens)
        return self._extract_json(text)

    @staticmethod
    def _extract_json(text: str) -> dict:
        """从 LLM 回复中提取 JSON，兼容多种格式。"""
        text = text.strip()

        # 处理 LLM 返回双花括号 {{ }} 的情况（学样了 prompt 模板中的转义）
        if text.startswith("{{") and "}}" in text:
            text = text.replace("{{", "{", 1)
            last_brace = text.rfind("}}")
            if last_brace >= 0:
                text = text[:last_brace] + "}" + text[last_brace + 2:]

        # 尝试1：直接解析
        try:
            return json.loads(text)
        except json.JSONDecodeError:
            pass

        # 尝试2：去掉 ```json ... ``` 包裹
        if text.startswith("```"):
            lines = text.split("\n")
            lines = lines[1:]  # 去掉 ```json
            if lines and lines[-1].strip() == "```":
                lines = lines[:-1]
            inner = "\n".join(lines)
            try:
                return json.loads(inner)
            except json.JSONDecodeError:
                pass

        # 尝试3：用正则从文本中提取最外层 { ... }
        match = re.search(r'\{[\s\S]*\}', text)
        if match:
            try:
                return json.loads(match.group())
            except json.JSONDecodeError:
                pass

        raise ValueError(f"无法从 LLM 回复中解析 JSON。原始回复：\n{text}")
