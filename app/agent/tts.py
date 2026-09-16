"""AI 配音模块 —— Edge-TTS 免费开源方案（计划书核心功能 4 / 5.4 节离线可用）。"""
import asyncio
from pathlib import Path

from ..paths import data_dir

OUTPUT_DIR = data_dir() / "output"
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

VOICES = {
    "female": {"id": "zh-CN-XiaoxiaoNeural", "label": "女声·晓晓（亲和种草）"},
    "male": {"id": "zh-CN-YunxiNeural", "label": "男声·云希（阳光口播）"},
}


def list_voices() -> list[dict]:
    return [{"key": k, "id": v["id"], "label": v["label"]} for k, v in VOICES.items()]


async def synthesize(text: str, voice_key: str = "female", rate: str = "+8%") -> dict:
    """合成配音，返回 {ok, file, error}。依赖 edge-tts（需联网访问微软服务）。"""
    try:
        import edge_tts
    except ImportError:
        return {"ok": False, "file": None,
                "error": "edge-tts 未安装：pip install edge-tts 后重试"}

    voice = VOICES.get(voice_key, VOICES["female"])
    filename = f"tts_{voice_key}_{abs(hash(text)) % 10**8}.mp3"
    out_path = OUTPUT_DIR / filename
    try:
        communicate = edge_tts.Communicate(text=text, voice=voice["id"], rate=rate)
        await communicate.save(str(out_path))
        return {"ok": True, "file": f"output/{filename}", "voice": voice["label"],
                "error": None}
    except Exception as e:
        return {"ok": False, "file": None,
                "error": f"配音合成失败（需联网）：{e}"}
