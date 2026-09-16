"""ClipSync Agent —— 「一拍即合」短视频脚本智造与多平台分发智能体

FastAPI 入口：SaaS 网页 + API 两种调用方式（计划书核心功能 5）。
"""
import asyncio
import json
from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from .agent import hotsearch, pipeline, stasis, tts
from .agent.llm import (
    PROVIDERS, llm_available, load_config, save_config,
    list_ollama_models, ollama_available, test_llm,
)
from .paths import app_dir, data_dir

BASE_DIR = app_dir()                      # 内置资源（static）
OUTPUT_DIR = data_dir() / "output"        # 可写目录（exe 同级 / 项目根）
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

app = FastAPI(title="一拍即合 ClipSync Agent",
              description="关键词→成片脚本→多平台文案→AI配音 一站式内容包智能体",
              version="0.3.0")

app.mount("/static", StaticFiles(directory=BASE_DIR / "static"), name="static")
app.mount("/output", StaticFiles(directory=OUTPUT_DIR), name="output")


class GenerateRequest(BaseModel):
    keyword: str = Field(..., min_length=1, max_length=50, description="热点关键词")
    duration: int = Field(60, description="视频时长（秒）")
    industry: str = Field("", description="行业（文旅/电商/餐饮等）")
    platforms: list[str] = Field(default_factory=lambda: ["douyin", "bilibili", "xiaohongshsu"])
    title: str = Field("", description="定制标题（可选）：覆盖自动生成标题，建议用争点选题法产出")


class TTSRequest(BaseModel):
    text: str = Field(..., min_length=1, max_length=2000)
    voice: str = Field("female")


class LLMConfigRequest(BaseModel):
    provider: str = Field("deepseek", description="服务商：deepseek/qwen/glm/ollama/custom")
    api_key: str = Field("", description="API Key（Ollama 可留空）")
    base_url: str = Field("", description="OpenAI 兼容 /v1 端点（Ollama 默认 http://localhost:11434/v1）")
    model: str = Field("", description="模型名（Ollama 可从本地模型列表选择）")
    timeout: int = Field(60, ge=5, le=300, description="读超时（秒）")


@app.get("/")
async def index():
    return FileResponse(BASE_DIR / "static" / "index.html")


@app.get("/api/config")
async def get_config():
    cfg = load_config().get("llm", {})
    provider = cfg.get("provider", "deepseek")
    ollama_on = provider == "ollama" and ollama_available(
        cfg.get("base_url") or PROVIDERS["ollama"]["base_url"])
    return {
        "llm_enabled": llm_available(),
        "provider": provider,
        "provider_name": PROVIDERS.get(provider, PROVIDERS["custom"])["name"],
        "base_url": cfg.get("base_url") or PROVIDERS.get(provider, {}).get("base_url", ""),
        "model": cfg.get("model") or PROVIDERS.get(provider, {}).get("default_model", ""),
        "has_key": bool(cfg.get("api_key")),
        "ollama_available": ollama_on,
        "providers": {k: v["name"] for k, v in PROVIDERS.items()},
        "display_model": (cfg.get("model") or PROVIDERS.get(provider, {}).get("default_model", ""))
                        if llm_available() else "local-template-engine",
        "voices": tts.list_voices(),
    }


@app.post("/api/llm-config")
async def set_llm_config(req: LLMConfigRequest):
    """保存大模型 / Ollama 配置到 exe 同级 config.json。

    - Ollama：可无 Key，base_url 缺省自动填 http://localhost:11434/v1
    - 云端 / 自定义：必须有 API Key（自定义还需 base_url）
    """
    provider = req.provider
    if provider not in PROVIDERS:
        return JSONResponse(status_code=400,
                            content={"ok": False, "error": f"未知服务商：{provider}"})
    preset = PROVIDERS[provider]
    base_url = (req.base_url or "").strip()
    model = (req.model or "").strip()
    api_key = (req.api_key or "").strip()

    if provider == "ollama":
        base_url = base_url or preset["base_url"]
        if not model:
            models = list_ollama_models(base_url)
            if models:
                model = models[0]
            else:
                model = preset["default_model"]
    else:
        if preset.get("needs_key") and not api_key:
            return JSONResponse(status_code=400,
                                content={"ok": False, "error": f"{preset['name']} 需要填写 API Key"})
        if provider == "custom" and not base_url:
            return JSONResponse(status_code=400,
                                content={"ok": False, "error": "自定义服务商需填写 Base URL"})
        base_url = base_url or preset["base_url"]
        model = model or preset["default_model"]

    llm_seg = {
        "provider": provider,
        "api_key": api_key,
        "base_url": base_url,
        "model": model,
        "timeout": req.timeout,
    }
    path = save_config(llm_seg)
    return {
        "ok": True,
        "path": str(path),
        "config": llm_seg,
        "llm_enabled": llm_available(),
    }


@app.get("/api/ollama/models")
async def api_ollama_models(base_url: str = ""):
    """列出本地 Ollama 已拉取的模型（用于下拉选择）。"""
    models = list_ollama_models(base_url or PROVIDERS["ollama"]["base_url"])
    return {
        "ok": True,
        "available": ollama_available(base_url or PROVIDERS["ollama"]["base_url"]),
        "models": models,
    }


@app.post("/api/llm-test")
async def api_llm_test(req: LLMConfigRequest):
    """连接测试：用极小请求验证所选服务商 / 本地 Ollama 是否可用。"""
    result = await test_llm(req.provider, req.api_key, req.base_url, req.model,
                            timeout=min(req.timeout, 30))
    return result


@app.post("/api/generate")
async def generate(req: GenerateRequest):
    """四步工作流：感知 → 规划 → 执行 → 反思，输出完整内容包 JSON。"""
    req.platforms = [p for p in req.platforms if p] or ["douyin", "bilibili", "xiaohongshu"]
    result = await pipeline.run(
        keyword=req.keyword.strip(),
        duration=req.duration,
        industry=req.industry.strip(),
        platforms=req.platforms,
        title=req.title.strip(),
    )
    # 内容包落盘，供下载
    fpath = OUTPUT_DIR / f"pack_{result['task_id']}.json"
    with open(fpath, "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=2)
    result["export"]["json_file"] = f"/output/pack_{result['task_id']}.json"
    return result


@app.get("/api/hotsearch")
async def api_hotsearch(source: str = "all", limit: int = 20, refresh: bool = False):
    """实时热榜：微博 / 抖音 / 百度。refresh=true 时跳过缓存强制拉取。"""
    limit = max(1, min(limit, 50))
    return await hotsearch.fetch(source=source if source in hotsearch.SOURCES else "all",
                                 limit=limit, use_cache=not refresh)


@app.get("/api/stasis")
async def api_stasis(keyword: str = "", industry: str = ""):
    """争点选题法（stasis-topic）：给定热点关键词，确定性产出 3 个备选标题。

    完全离线、无需大模型 Key / 本地 Ollama。
    """
    if not keyword.strip():
        return JSONResponse(status_code=400,
                            content={"ok": False, "error": "缺少 keyword 参数"})
    return stasis.propose(keyword.strip(), industry.strip())


@app.post("/api/tts")
async def api_tts(req: TTSRequest):
    result = await tts.synthesize(req.text, req.voice)
    if not result["ok"]:
        return JSONResponse(status_code=503, content=result)
    return result


@app.get("/api/health")
async def health():
    return {"status": "ok", "service": "clipsync-agent", "version": "0.3.0"}
