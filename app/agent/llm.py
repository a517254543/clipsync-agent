"""LLM 适配器 —— 对接 OpenAI 兼容接口（DeepSeek / Qwen / GLM 等）与本地 Ollama。

对应计划书 5.1 节：基座模型采用国产开源大模型（Qwen2.5 / DeepSeek 等），
支持 Function Calling 与长上下文。无 API Key / 未启动 Ollama 时自动降级为
本地模板模式（5.4 节），保证"断连可用"。
"""
import json
import os
from pathlib import Path

import httpx

from ..paths import data_dir

# 配置查找顺序：exe 同级（用户可改）→ 项目目录 / 打包内置
CONFIG_CANDIDATES = [
    data_dir() / "config.json",
    Path(__file__).resolve().parents[2] / "config.json",
]

# 服务商预设：base_url 填 OpenAI 兼容的 /v1 端点；Ollama 无需 Key。
PROVIDERS = {
    "deepseek": {
        "name": "DeepSeek",
        "base_url": "https://api.deepseek.com/v1",
        "default_model": "deepseek-chat",
        "needs_key": True,
    },
    "qwen": {
        "name": "通义千问 Qwen",
        "base_url": "https://dashscope.aliyuncs.com/compatible-mode/v1",
        "default_model": "qwen-plus",
        "needs_key": True,
    },
    "glm": {
        "name": "智谱 GLM",
        "base_url": "https://open.bigmodel.cn/api/paas/v4",
        "default_model": "glm-4-flash",
        "needs_key": True,
    },
    "ollama": {
        "name": "本地 Ollama",
        "base_url": "http://localhost:11434/v1",
        "default_model": "qwen2.5",
        "needs_key": False,
    },
    "custom": {
        "name": "自定义 OpenAI 兼容",
        "base_url": "",
        "default_model": "",
        "needs_key": True,
    },
}

DEFAULT_CONFIG = {
    "llm": {
        "provider": "deepseek",
        "api_key": "",
        "base_url": "",
        "model": "",
        "timeout": 60,
    }
}


def load_config() -> dict:
    for path in CONFIG_CANDIDATES:
        if path.exists():
            try:
                with open(path, "r", encoding="utf-8") as f:
                    cfg = json.load(f)
                # 融合默认值，保证缺字段不报错
                base = json.loads(json.dumps(DEFAULT_CONFIG))
                if isinstance(cfg, dict):
                    base.update({k: v for k, v in cfg.items() if k != "llm"})
                    if isinstance(cfg.get("llm"), dict):
                        base["llm"].update(cfg["llm"])
                return base
            except Exception:
                break
    return json.loads(json.dumps(DEFAULT_CONFIG))


def save_config(llm: dict) -> Path:
    """把 llm 配置段写回 exe 同级的 config.json（保留其它字段）。"""
    cfg_path = data_dir() / "config.json"
    try:
        with open(cfg_path, "r", encoding="utf-8") as f:
            cfg = json.load(f)
    except Exception:
        cfg = {}
    cfg["llm"] = llm
    with open(cfg_path, "w", encoding="utf-8") as f:
        json.dump(cfg, f, ensure_ascii=False, indent=2)
    return cfg_path


def llm_available() -> bool:
    cfg = load_config().get("llm", {})
    if cfg.get("provider") == "ollama":
        return ollama_available(cfg.get("base_url") or PROVIDERS["ollama"]["base_url"])
    return bool(cfg.get("api_key") or os.environ.get("LLM_API_KEY"))


def _ollama_root(base_url: str) -> str:
    base_url = (base_url or PROVIDERS["ollama"]["base_url"]).rstrip("/")
    if base_url.endswith("/v1"):
        return base_url[:-3]
    return base_url


def list_ollama_models(base_url: str = "") -> list[str]:
    """列出本地 Ollama 已拉取的模型名；Ollama 未启动 / 不可达时返回空列表。"""
    root = _ollama_root(base_url)
    try:
        _t = httpx.Timeout(connect=2.0, read=5.0, write=5.0, pool=2.0)
        with httpx.Client(timeout=_t) as client:
            r = client.get(f"{root}/api/tags")
            r.raise_for_status()
            models = r.json().get("models", [])
        return [m.get("name", "") for m in models if m.get("name")]
    except Exception:
        return []


def ollama_available(base_url: str = "") -> bool:
    """Ollama 服务是否可达（接口返回 2xx 即视为可用，哪怕无模型）。"""
    root = _ollama_root(base_url)
    try:
        _t = httpx.Timeout(connect=2.0, read=5.0, write=5.0, pool=2.0)
        with httpx.Client(timeout=_t) as client:
            r = client.get(f"{root}/api/tags")
            return r.status_code < 500
    except Exception:
        return False


async def test_llm(provider: str, api_key: str, base_url: str,
                   model: str, timeout: int = 20) -> dict:
    """快速连接测试：用极小请求验证服务商 / Ollama 是否可用。"""
    preset = PROVIDERS.get(provider, PROVIDERS["custom"])
    base_url = (base_url or preset.get("base_url", "")).rstrip("/")
    model = (model or preset.get("default_model", "")).strip()
    key = api_key or ("ollama" if provider == "ollama" else "")
    if provider != "ollama" and not key:
        return {"ok": False, "error": "该服务商需要 API Key"}
    if not base_url:
        return {"ok": False, "error": "缺少 Base URL（自定义服务商需填写）"}
    if not model:
        return {"ok": False, "error": "缺少模型名称"}
    payload = {
        "model": model,
        "messages": [
            {"role": "system", "content": "你是测试助手。"},
            {"role": "user", "content": "请只回复两个字：OK"},
        ],
        "temperature": 0.3,
        "stream": False,
        "max_tokens": 20,
    }
    try:
        _t = httpx.Timeout(connect=5.0, read=timeout, write=10.0, pool=5.0)
        async with httpx.AsyncClient(timeout=_t) as client:
            r = await client.post(
                f"{base_url}/chat/completions", json=payload,
                headers={"Authorization": f"Bearer {key}",
                          "Content-Type": "application/json"})
            r.raise_for_status()
            d = r.json()
        return {
            "ok": True,
            "model": model,
            "reply": d["choices"][0]["message"]["content"][:50],
            "usage": d.get("usage", {}),
        }
    except Exception as e:
        return {"ok": False, "error": f"{type(e).__name__}: {e}"}


class LLMClient:
    """轻量 OpenAI 兼容客户端，带 Token 计量（对应计划书 5.3 节）。"""

    def __init__(self):
        cfg = load_config().get("llm", {})
        self.provider = cfg.get("provider", "deepseek")
        preset = PROVIDERS.get(self.provider, PROVIDERS["custom"])
        self.api_key = cfg.get("api_key") or os.environ.get("LLM_API_KEY", "")
        self.base_url = (cfg.get("base_url") or preset.get("base_url", "")
                         or os.environ.get("LLM_BASE_URL", "")).rstrip("/")
        self.model = (cfg.get("model") or preset.get("default_model", "")
                      or os.environ.get("LLM_MODEL", "")).strip()
        self.timeout = cfg.get("timeout", 60)
        self.usage = {"prompt_tokens": 0, "completion_tokens": 0, "calls": 0}

        # 当前是否真正可用：本地 Ollama 需先确认服务可达，否则回落模板引擎。
        if self.provider == "ollama":
            self._usable = bool(self.base_url) and ollama_available(self.base_url)
            if not self.api_key:
                self.api_key = "ollama"   # Ollama 接受任意 Bearer 值
        else:
            self._usable = bool(self.api_key)

    @property
    def enabled(self) -> bool:
        return self._usable

    async def chat(self, system: str, user: str, json_mode: bool = False) -> str | None:
        """调用 chat/completions。失败或未配置时返回 None（调用方降级到模板引擎）。"""
        if not self.enabled:
            return None
        payload = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            "temperature": 0.8,
            "stream": False,
        }
        if json_mode:
            payload["response_format"] = {"type": "json_object"}
        headers = {"Authorization": f"Bearer {self.api_key}",
                    "Content-Type": "application/json"}
        try:
            # 连接超时短（5s）：本地 Ollama 未启动 / 地址不可达时立即失败并降级，
            # 不会因 60s 读超时把生成卡住；读超时仍用配置值。
            _timeout = httpx.Timeout(connect=5.0, read=self.timeout,
                                     write=10.0, pool=5.0)
            async with httpx.AsyncClient(timeout=_timeout) as client:
                resp = await client.post(f"{self.base_url}/chat/completions",
                                         json=payload, headers=headers)
                resp.raise_for_status()
                data = resp.json()
            usage = data.get("usage", {})
            self.usage["prompt_tokens"] += usage.get("prompt_tokens", 0)
            self.usage["completion_tokens"] += usage.get("completion_tokens", 0)
            self.usage["calls"] += 1
            return data["choices"][0]["message"]["content"]
        except Exception:
            return None

    @staticmethod
    def parse_json(text: str | None) -> dict | None:
        """从模型输出中稳健地解析 JSON（容忍 markdown 代码块包裹）。"""
        if not text:
            return None
        text = text.strip()
        if text.startswith("```"):
            text = text.strip("`")
            if text.startswith("json"):
                text = text[4:]
            text = text.strip()
        try:
            return json.loads(text)
        except Exception:
            start, end = text.find("{"), text.rfind("}")
            if 0 <= start < end:
                try:
                    return json.loads(text[start:end + 1])
                except Exception:
                    return None
            return None
