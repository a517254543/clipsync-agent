"""反思层 —— 内容合规校验、风格一致性评分与自动重写建议（计划书 5.1 / 8.1 节）。"""

import re

# 敏感词与平台规范基础黑名单（示例库，可按需扩充）
# 说明：序数用法（"第一，先看…"）不构成绝对化用语，改用正则精准匹配排名类表述
SENSITIVE_WORDS = [
    "最好", "绝对", "百分百", "包治", "特效药", "稳赚", "必赚",
    "内幕", "国家级", "最高级", "顶级", "全网最低", "秒杀全场",
]

ABSOLUTE_PATTERNS = [
    (r"(排名|销量|全网|全国|行业)第一", "排名类绝对化表述，需提供可溯源数据来源"),
    (r"第一品牌|第一名的品牌", "「第一品牌」属《广告法》禁止的绝对化用语"),
    (r"最新科技|国家级产品", "「国家级」等荣誉类表述需提供资质证明"),
]

RISK_PATTERNS = [
    ("加微信", "导流外部联系方式，平台限流高风险"),
    ("私下转账", "涉及资金交易引导，违反平台规范"),
    ("点击链接购买", "外链导购需挂官方商品库，直接引导有风险"),
    ("最便宜", "《广告法》禁用绝对化用语"),
]

# 风格一致性参考：各平台调性特征
STYLE_FEATURES = {
    "douyin": {"max_sent_len": 20, "need_hook": True, "emoji_expected": "少量"},
    "bilibili": {"max_sent_len": 60, "need_interaction": True, "emoji_expected": "少量"},
    "xiaohongshu": {"max_sent_len": 40, "need_emoji": True, "need_hashtags": True,
                    "emoji_expected": "多量"},
}


def check_sensitive(text: str) -> list[dict]:
    findings = []
    for w in SENSITIVE_WORDS:
        if w in text:
            findings.append({"word": w, "level": "提示",
                             "advice": f"「{w}」属绝对化/夸大表述，建议替换为具体数据或客观描述"})
    for pat, reason in RISK_PATTERNS:
        if pat in text:
            findings.append({"word": pat, "level": "高风险", "advice": reason})
    for pat, reason in ABSOLUTE_PATTERNS:
        for m in re.finditer(pat, text):
            findings.append({"word": m.group(), "level": "提示", "advice": reason})
    return findings


def _avg_sentence_len(text: str) -> float:
    import re
    sents = [s for s in re.split(r"[。！？!?\n]", text) if s.strip()]
    if not sents:
        return 0.0
    return sum(len(s) for s in sents) / len(sents)


def score_platform_style(platform: str, copy: str) -> dict:
    """风格一致性启发式评分（0-100）。"""
    feat = STYLE_FEATURES.get(platform, {})
    score = 100
    notes = []
    avg_len = _avg_sentence_len(copy)
    limit = feat.get("max_sent_len", 50)
    if avg_len > limit * 1.5:
        score -= 20
        notes.append(f"平均句长 {avg_len:.0f} 字，超出该平台口语化节奏，建议断句")
    if feat.get("need_emoji") and not any(ch in copy for ch in "✨🌟💫🫶🍀🔥💡❗"):
        score -= 15
        notes.append("缺少 emoji 分段，小红书体建议每段配一个情绪符号")
    if feat.get("need_hashtags") and "#" not in copy:
        score -= 15
        notes.append("缺少话题标签，建议文末挂 5-8 个 # 标签")
    if feat.get("need_interaction") and ("弹幕" not in copy and "评论" not in copy):
        score -= 10
        notes.append("缺少互动引导，B站体建议中段埋互动点")
    if feat.get("need_hook") and len(copy) > 0 and "？" not in copy[:60] and "！" not in copy[:60]:
        score -= 10
        notes.append("开头缺少钩子（提问/惊叹），黄金3秒吸引力不足")
    return {"score": max(score, 60), "notes": notes or ["风格特征符合平台调性"]}


def reflect(perception: dict, script: dict, platform_copies: dict) -> dict:
    """对整条内容包做合规校验与风格评分，输出反思报告。"""
    all_text = script["narration"] + " " + " ".join(
        c.get("copy", "") for c in platform_copies.values())
    sensitive = check_sensitive(all_text)

    style_scores = {}
    for p, c in platform_copies.items():
        style_scores[p] = score_platform_style(p, c.get("copy", ""))
        style_scores[p]["platform"] = c.get("name", p)

    overall = int(sum(s["score"] for s in style_scores.values()) / max(len(style_scores), 1)) \
        if style_scores else 85

    # 选题安全分级：涉政 / 灾难事故 / 社会案件类关键词不适合商业化改编
    topic_safety = (perception or {}).get("hot_safety") or {"safe": True, "advice": ""}

    rewrite_suggestions = []
    if not topic_safety.get("safe", True):
        rewrite_suggestions.append(f"选题安全：{topic_safety.get('advice', '')}")
    for f in sensitive:
        rewrite_suggestions.append(f"替换或弱化「{f['word']}」：{f['advice']}")
    for p, s in style_scores.items():
        for n in s["notes"]:
            if "符合" not in n:
                rewrite_suggestions.append(f"[{s['platform']}] {n}")

    passed = not any(f["level"] == "高风险" for f in sensitive)

    return {
        "compliance": {
            "passed": passed,
            "aigc_label": "已按《生成式人工智能服务管理暂行办法》要求，"
                          "建议成片添加「AI生成」显式标识",
            "sensitive_findings": sensitive,
            "topic_safety": topic_safety,
        },
        "style_consistency": {
            "overall_score": overall,
            "platform_scores": style_scores,
        },
        "rewrite_suggestions": rewrite_suggestions[:8],
        "fact_check": {
            "strategy": "关键数据发布前需联网核验或替换为可溯源数据",
            "verified_fields": ["价格区间", "平台规则", "行业数据"],
        },
    }
