"""ClipSync Agent 编排器 —— 感知 / 规划 / 执行 / 反思 四步工作流（计划书 5.1 节）。

有 LLM Key 时走大模型生成；失败或未配置时自动降级到本地模板引擎（5.4 节），
保证"断连可用"。所有产出统一为结构化 JSON 内容包。
"""
import time
import uuid
from datetime import datetime

from . import hotsearch, templates
from .compliance import reflect
from .llm import LLMClient

# ---------------- 提示词工程（对应计划书"提示词压缩与模板约束"） ----------------

SYS_PERCEIVE = (
    "你是短视频热点分析师。基于给定关键词做选题研判，只输出 JSON，字段："
    "heat_score(int 0-100), heat_level(str), audience(str), recommended_angle"
    "{type,desc}, suggested_title(str), best_post_window(str)。中文作答，简洁。"
)

SYS_SCRIPT = (
    "你是爆款短视频编导。根据关键词和时长写一条可拍摄脚本，只输出 JSON，字段："
    "title(str), storyboard(数组，每项含 镜号/景别/画面/台词/时长，总时长约等于给定秒数),"
    "narration(str 完整口播稿), subtitles(数组), bgm{style,volume,cut_points}, tts_text(适合口播的完整台词)。"
    "要求：开头3秒强钩子；景别在特写/近景/中景/全景间切换；台词口语化。中文作答。"
)

SYS_ADAPT = (
    "你是多平台内容运营。把给定脚本改写为指定平台文案，只输出 JSON："
    "每个平台一个键(douyin/bilibili/xiaohongshu)，值为{name,title,copy,tags,style_tips}。"
    "抖音：黄金3秒钩子+短句+强CTA；B站：口语化长文案+弹幕互动；"
    "小红书：种草笔记+emoji分段+5-8个话题标签。中文作答。"
)


def _base_pack(keyword: str, duration: int, industry: str, platforms: list[str]) -> dict:
    """本地模板通道：一步产出完整内容包。"""
    perception = templates.perceive(keyword, industry)
    script = templates.build_script(keyword, duration, industry)
    copies = templates.adapt_platforms(keyword, script, platforms)
    return perception, script, copies


def _score_from_rank(rank: int, platform_count: int, strong: bool) -> int:
    """依据榜单排名与跨平台覆盖度计算热度分（0-100）。"""
    base = 58 if strong else 46
    rank_bonus = max(0, 26 - int(rank))          # 榜首加分最高
    cross_bonus = 8 * max(0, platform_count - 1)  # 多平台上榜加权
    return int(min(96, base + rank_bonus + cross_bonus))


async def perceive_live(keyword: str, industry: str, limit: int = 30) -> dict | None:
    """感知层（联网版）：拉取微博/抖音/百度实时热榜，研判关键词热度。

    返回 None 表示热榜全部不可用，由上层回落本地研判。
    """
    hot = await hotsearch.fetch("all", limit=limit)
    if not hot["ok"]:
        return None

    all_items = [it for p in hot["platforms"] for it in p["items"]]
    if not all_items:
        return None

    matched = hotsearch.match_keyword(keyword, all_items)
    strong_hits = [m for m in matched if m["match"] == "直接命中"]
    weak_hits = [m for m in matched if m["match"] == "弱相关"]
    platforms_on = sorted({m["source_name"] for m in matched})

    if strong_hits:
        best = min(int(h.get("rank") or 99) for h in strong_hits)
        score = _score_from_rank(best, len(platforms_on), strong=True)
        hit_desc = f"命中 {len(platforms_on)} 个平台热榜，最好排名 第{best}位"
    elif weak_hits:
        best = min(int(h.get("rank") or 99) for h in weak_hits)
        score = _score_from_rank(best, 1, strong=False)
        hit_desc = f"热榜弱相关，最好排名 第{best}位"
    else:
        score = 42
        hit_desc = "未进入三平台实时热榜（长尾/垂类关键词）"

    level = "高热" if score >= 85 else ("升温" if score >= 70 else
                                        ("潜力" if score >= 55 else "长尾"))
    safety = hotsearch.safety_level(keyword)

    base = templates.perceive(keyword, industry)  # 复用受众/角度/发布窗口等本地研判
    base.update({
        "heat_score": score,
        "heat_level": level,
        "hot_hit": hit_desc,
        "hot_matched": matched[:8],
        "hot_safety": safety,
        "data_source": "微博热搜 + 抖音热榜 + 百度热搜（实时）",
        "hot_updated_at": hot["updated_at"],
        "hot_top": {p["name"]: p["items"][:10]
                    for p in hot["platforms"] if p["ok"]},
        "live": True,
    })
    return base


async def run(keyword: str, duration: int = 60, industry: str = "",
              platforms: list[str] | None = None, title: str = "") -> dict:
    """执行完整四步工作流，返回结构化内容包（JSON）。"""
    platforms = [p for p in (platforms or ["douyin", "bilibili", "xiaohongshu"])
                 if p in templates.PLATFORM_META]
    task_id = uuid.uuid4().hex[:12]
    started = time.time()
    llm = LLMClient()
    mode = "llm" if llm.enabled else "template"

    # ── Step 1 感知：实时热榜 + 选题研判 ────────────────────
    perception = await perceive_live(keyword, industry)   # 优先接真实热榜
    if perception is None:                                # 热榜不可用 → 本地研判
        perception = templates.perceive(keyword, industry)
        perception["live"] = False
        perception["data_source"] = "本地研判引擎（热榜接口暂不可用）"
    if llm.enabled:                                       # 有 Key 时叠加 LLM 定性研判
        raw = await llm.chat(
            SYS_PERCEIVE,
            f"关键词：{keyword}；行业：{industry or '通用'}；目标时长：{duration}秒")
        extra = LLMClient.parse_json(raw)
        if extra:
            perception.update({k: v for k, v in extra.items() if v})
    perception.setdefault("keyword", keyword)
    perception.setdefault("industry", industry or "通用")
    if title:
        perception["suggested_title"] = title

    # ── Step 2+3 规划 & 执行：脚本分镜 + 多平台文案 ─────────
    script = None
    if llm.enabled:
        raw = await llm.chat(SYS_SCRIPT, (
            f"关键词：{keyword}\n行业：{industry or '通用'}\n时长：{duration}秒\n"
            f"选题角度：{perception.get('recommended_angle', {}).get('type', '干货清单')}"))
        script = LLMClient.parse_json(raw)
    if script is None:
        script = templates.build_script(keyword, duration, industry)
        mode = "template" if not llm.enabled else "llm+fallback"
    script.setdefault("duration", duration)
    if title:
        script["title"] = title   # 用户选定的争点选题标题覆盖自动标题（三平台文案随之采用）

    platform_copies = None
    if llm.enabled:
        raw = await llm.chat(SYS_ADAPT, (
            f"关键词：{keyword}\n脚本标题：{script.get('title','')}\n"
            f"口播稿：{script.get('narration','')[:500]}\n"
            f"目标平台：{','.join(platforms)}"))
        parsed = LLMClient.parse_json(raw)
        if isinstance(parsed, dict):
            platform_copies = {k: v for k, v in parsed.items() if k in platforms and isinstance(v, dict)}
            for p in platform_copies.values():
                p.setdefault("name", templates.PLATFORM_META.get(
                    list(p.keys()) if False else "douyin", {}).get("name", ""))
    if not platform_copies:
        platform_copies = templates.adapt_platforms(keyword, script, platforms)
        mode = "template" if not llm.enabled else "llm+fallback"

    # ── Step 4 反思：合规校验与风格评分 ─────────────────────
    reflection = reflect(perception, script, platform_copies)

    # ── 输出集成：结构化内容包（计划书核心功能5） ─────────────
    elapsed = round(time.time() - started, 2)
    usage = llm.usage if llm.enabled else {
        "prompt_tokens": 0, "completion_tokens": 0, "calls": 0}
    total_tokens = usage["prompt_tokens"] + usage["completion_tokens"]

    return {
        "task_id": task_id,
        "meta": {
            "keyword": keyword,
            "industry": industry or "通用",
            "duration": duration,
            "platforms": platforms,
            "mode": mode,
            "model": llm.model if llm.enabled else "local-template-engine",
            "generated_at": datetime.now().isoformat(timespec="seconds"),
            "elapsed_seconds": elapsed,
        },
        "token_metering": {  # 对应计划书 5.3 节 Token 计量
            "prompt_tokens": usage["prompt_tokens"],
            "completion_tokens": usage["completion_tokens"],
            "total_tokens": total_tokens,
            "estimated_cost_rmb": round(total_tokens / 1000 * 0.002, 4),
            "note": "本地模板模式不消耗Token；接入LLM后按调用实测计量",
        },
        "perception": perception,
        "script": script,
        "platform_copies": platform_copies,
        "reflection": reflection,
        "export": {
            "json": "可下载完整JSON",
            "docs": "可下载Markdown脚本文档",
            "editing": "分镜表可直接导入剪映/CapCut参照拍摄",
        },
    }
