"""实时热榜接入 —— 微博 / 抖音 / 百度（感知层数据源，对应计划书核心功能1）。

全部使用各平台公开只读接口，无需 Key：
- 微博：weibo.com/ajax/side/hotSearch（需带 Referer）
- 抖音：iesdouyin.com/web/api/v2/hotsearch/billboard/word/
- 百度：top.baidu.com/api/board?platform=wise&tab=realtime

设计要点：
1. 三级容错：单平台失败不影响其他平台；全部失败时上层回落本地研判引擎。
2. 内存缓存（默认 10 分钟），对应计划书 5.2 节「热点摘要缓存」，避免重复拉取。
3. 选题安全分级：涉政、灾难事故、社会案件类词条标注为「不建议商业化改编」。
"""
import asyncio
import time
from datetime import datetime

import httpx

UA = ("Mozilla/5.0 (iPhone; CPU iPhone OS 16_0 like Mac OS X) AppleWebKit/605.1.15 "
      "(KHTML, like Gecko) Version/16.0 Mobile/15E148 Safari/604.1")
HEADERS_WEIBO = {"User-Agent": UA, "Referer": "https://weibo.com/",
                 "Accept": "application/json"}
HEADERS_DEFAULT = {"User-Agent": UA}

TIMEOUT = 10
CACHE_TTL = 600  # 10 分钟

SOURCES = {
    "weibo": {"name": "微博热搜", "url": "https://weibo.com/ajax/side/hotSearch",
              "headers": HEADERS_WEIBO},
    "douyin": {"name": "抖音热榜",
               "url": "https://www.iesdouyin.com/web/api/v2/hotsearch/billboard/word/",
               "headers": HEADERS_DEFAULT},
    "baidu": {"name": "百度热搜",
              "url": "https://top.baidu.com/api/board?platform=wise&tab=realtime",
              "headers": HEADERS_DEFAULT},
}

# 选题安全分级关键词：命中即提示「不建议商业化改编」
BLOCK_HINTS = {
    "涉政时政": ["总书记", "中央", "国务院", "人大", "政协", "外交部", "国防部",
                 "主席", "总理", "峰会", "政治局", "解放军", "军区", "领导人"],
    "灾难事故": ["遇难", "失联", "身亡", "死亡", "地震", "泥石流", "塌方", "坍塌", "爆炸",
                 "火灾", "车祸", "坠亡", "溺亡", "中毒", "事故", "救援", "伤亡"],
    "社会案件": ["刑拘", "逮捕", "判刑", "诈骗", "性侵", "猥亵", "贩毒", "立案",
                 "涉嫌", "被捕", "通报"],
}

_cache: dict[str, tuple[float, list]] = {}
_lock = asyncio.Lock()


def _fmt_value(n) -> str:
    """热度值转中文可读格式。"""
    try:
        n = int(n)
    except Exception:
        return "—"
    if n >= 100_000_000:
        return f"{n / 100_000_000:.1f}亿"
    if n >= 10_000:
        return f"{n / 10_000:.1f}万"
    return str(n)


def safety_level(title: str) -> dict:
    """选题安全分级：判断词条是否适合商业化改编。"""
    for category, words in BLOCK_HINTS.items():
        for w in words:
            if w in title:
                return {"safe": False, "category": category,
                        "advice": f"涉及{category}，不建议用于营销改编与蹭热点"}
    return {"safe": True, "category": "常规", "advice": ""}


# ---------------- 各平台解析 ----------------

def _parse_weibo(data: dict) -> list:
    items = (data.get("data") or {}).get("realtime") or []
    out = []
    for i, it in enumerate(items):
        title = it.get("word") or it.get("note") or ""
        if not title:
            continue
        out.append({"rank": it.get("realpos") or (i + 1), "title": title,
                    "hot_value": it.get("num", 0), "hot_text": _fmt_value(it.get("num", 0)),
                    "label": it.get("label_name") or "", "source": "weibo",
                    "source_name": "微博",
                    "url": f"https://s.weibo.com/weibo?q={it.get('word_scheme') or title}"})
    return out


def _parse_douyin(data: dict) -> list:
    items = data.get("word_list") or []
    out = []
    for i, it in enumerate(items):
        title = it.get("word") or ""
        if not title:
            continue
        out.append({"rank": i + 1, "title": title, "hot_value": it.get("hot_value", 0),
                    "hot_text": _fmt_value(it.get("hot_value", 0)),
                    "label": {1: "新", 2: "荐", 3: "热"}.get(it.get("label", 0), ""),
                    "source": "douyin", "source_name": "抖音",
                    "url": f"https://www.douyin.com/search/{title}"})
    return out


def _flatten_baidu(node) -> list:
    """百度 cards[].content 存在双层嵌套（content → content → 词条），递归展开。"""
    rows = []
    if isinstance(node, dict):
        if "word" in node or "query" in node:
            return [node]
        for v in node.values():
            rows.extend(_flatten_baidu(v))
    elif isinstance(node, list):
        for v in node:
            rows.extend(_flatten_baidu(v))
    return rows


def _parse_baidu(data: dict) -> list:
    cards = (data.get("data") or {}).get("cards") or []
    out = []
    for card in cards:
        for it in _flatten_baidu(card.get("content") or []):
            title = it.get("word") or it.get("query") or ""
            if not title:
                continue
            score = it.get("hotScore") or it.get("hot_score") or 0
            out.append({"rank": it.get("index") or (len(out) + 1), "title": title,
                        "hot_value": score, "hot_text": _fmt_value(score),
                        "label": "置顶" if it.get("isTop") else "",
                        "source": "baidu", "source_name": "百度",
                        "url": it.get("url") or f"https://www.baidu.com/s?wd={title}"})
    for idx, it in enumerate(out, 1):  # 百度 index 字段缺失时兜底重排序号
        if not it.get("rank"):
            it["rank"] = idx
    return out


PARSERS = {"weibo": _parse_weibo, "douyin": _parse_douyin, "baidu": _parse_baidu}


# ---------------- 抓取 ----------------

async def _fetch_one(source: str, limit: int) -> dict:
    cfg = SOURCES[source]
    try:
        async with httpx.AsyncClient(timeout=TIMEOUT, follow_redirects=True) as client:
            resp = await client.get(cfg["url"], headers=cfg["headers"])
            resp.raise_for_status()
            data = resp.json()
        items = PARSERS[source](data)[:limit]
        for it in items:
            it["safety"] = safety_level(it["title"])
        return {"source": source, "name": cfg["name"], "ok": True,
                "items": items, "error": None}
    except Exception as e:
        return {"source": source, "name": cfg["name"], "ok": False,
                "items": [], "error": f"{type(e).__name__}: {str(e)[:80]}"}


async def fetch(source: str = "all", limit: int = 30, use_cache: bool = True) -> dict:
    """抓取热榜。source 可为 weibo / douyin / baidu / all。"""
    targets = list(SOURCES.keys()) if source == "all" else [source]
    now = time.time()
    results, from_cache = [], 0

    async with _lock:
        pending = []
        for s in targets:
            if use_cache and s in _cache:
                ts, data = _cache[s]
                if now - ts < CACHE_TTL:
                    results.append({"source": s, "name": SOURCES[s]["name"], "ok": True,
                                    "items": data[:limit], "error": None})
                    from_cache += 1
                    continue
            pending.append(s)

        if pending:
            fetched = await asyncio.gather(*[_fetch_one(s, limit) for s in pending])
            for s, res in zip(pending, fetched):
                if res["ok"]:
                    _cache[s] = (now, res["items"])
                results.append(res)

    order = {s: i for i, s in enumerate(SOURCES)}
    results.sort(key=lambda r: order.get(r["source"], 99))
    return {
        "ok": any(r["ok"] for r in results),
        "updated_at": datetime.now().strftime("%H:%M:%S"),
        "cached_sources": from_cache,
        "platforms": results,
        "note": "数据来自各平台公开热榜接口，仅供选题参考",
    }


def match_keyword(keyword: str, items: list) -> list:
    """在榜单中找与关键词相关的词条（含字/词级交集）。"""
    if not keyword:
        return []
    hits = []
    for it in items:
        title = it["title"]
        if keyword in title or title in keyword:
            hits.append({**it, "match": "直接命中"})
            continue
        if len(keyword) >= 2:  # 二字及以上做连续片段匹配
            hit = any(keyword[i:i + 2] in title for i in range(len(keyword) - 1))
            if hit:
                hits.append({**it, "match": "弱相关"})
    return hits[:10]
