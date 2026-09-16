"""本地模板引擎 —— 无 LLM Key 时的降级生成通道（计划书 5.4 节）。

按"关键词 → 热点研判 → 脚本分镜 → 三平台文案"产出结构化内容包。
基于关键词哈希做确定性变化，保证同一关键词稳定、不同关键词多样。
"""
import hashlib
import random

# ---------------- 可复用的结构模板 ----------------

HOOKS = [
    "别再刷到{kw}还只会点赞了，今天3分钟教你彻底搞懂",
    "花了{days}天整理的{kw}攻略，看完少走80%弯路",
    "{kw}这件事，90%的人第一步就做错了",
    "为什么你的{kw}总是没效果？真相只有一个",
    "预算不多也想玩转{kw}？这篇直接抄作业",
]

ANGLES = [
    {"type": "痛点切入", "desc": "先放大用户在{kw}上的常见翻车点，再给出解法"},
    {"type": "干货清单", "desc": "以「3个技巧/5个坑」清单体拆解{kw}核心要点"},
    {"type": "情绪共鸣", "desc": "用真实场景故事带出{kw}的价值，结尾升华"},
    {"type": "对比反差", "desc": "「做对 vs 做错」的{kw}对照，强化记忆点"},
]

CTAS = [
    "关注我，下期拆解{kw}的进阶玩法",
    "评论区扣「1」，把这份{kw}攻略发你",
    "觉得有用就点赞收藏，别刷着刷着找不到了",
    "转发给需要的朋友，{kw}这件事别再瞎折腾",
]

BGMS = [
    "轻快节奏流行乐（BPM 110-120），副歌处踩分镜转场",
    "Lo-fi 舒缓节拍，适合口播讲解，音量压至 -18dB",
    "国风电子混音，副歌炸点对齐黄金3秒钩子",
    "悬念感钢琴前奏 + 鼓点渐强，配合中段情绪爬升",
]

SHOT_SCENES = [
    ("特写", "手机屏幕上{kw}相关内容的滑动画面，字幕逐条弹出"),
    ("近景", "博主正对镜头挑眉，做「嘘」的手势压低声音"),
    ("中景", "博主坐在书桌前，桌上摆着与{kw}相关的道具"),
    ("全景", "户外空镜一闪而过，字幕打出关键词大字"),
    ("特写", "手写便签/白板列出「3个要点」，逐条划重点"),
    ("近景", "博主竖起手指逐条讲解，语速加快"),
    ("中景", "情景再现：用户使用{kw}前后的对比画面（分屏）"),
    ("特写", "结尾定格：logo + 「关注」手势引导，字幕放大"),
]

PLATFORM_META = {
    "douyin": {
        "name": "抖音",
        "tips": "强钩子短句 + 黄金3秒；台词口语化、每句≤15字；结尾强CTA",
    },
    "bilibili": {
        "name": "B站",
        "tips": "口语化长文案 + 互动引导；开头自报家门；中段埋两个互动点",
    },
    "xiaohongshu": {
        "name": "小红书",
        "tips": "种草笔记体；emoji 分段；文末挂 5-8 个话题标签；真诚不硬广",
    },
}


def _seed(keyword: str) -> random.Random:
    return random.Random(int(hashlib.md5(keyword.encode("utf-8")).hexdigest()[:8], 16))


def _pick(rng: random.Random, seq: list) -> object:
    return rng.choice(seq)


# ---------------- 热点研判（感知层降级） ----------------

def perceive(keyword: str, industry: str = "") -> dict:
    rng = _seed(keyword)
    heat = rng.randint(62, 95)
    angle = _pick(rng, ANGLES)
    return {
        "keyword": keyword,
        "industry": industry or "通用",
        "heat_score": heat,
        "heat_level": "高热" if heat >= 85 else ("升温" if heat >= 75 else "潜力"),
        "audience": _pick(rng, ["18-30岁泛兴趣用户", "25-40岁本地消费者",
                                  "18-35岁内容消费者", "创业/副业人群"]),
        "recommended_angle": {
            "type": angle["type"],
            "desc": angle["desc"].format(kw=keyword),
        },
        "suggested_title": str(_pick(rng, HOOKS)).format(kw=keyword, days=rng.randint(3, 30)),
        "best_post_window": _pick(rng, ["12:00-13:00 午休高峰", "18:00-20:00 晚高峰",
                                          "21:00-23:00 睡前黄金档"]),
        "data_source": "本地研判引擎（未接入实时热榜）",
    }


# ---------------- 脚本生成（规划 + 执行降级） ----------------

def build_script(keyword: str, duration: int = 60, industry: str = "") -> dict:
    rng = _seed(keyword + str(duration))
    n_shots = {30: 4, 60: 6, 90: 8}.get(duration, 6)
    unit = duration / n_shots
    hook = str(_pick(rng, HOOKS)).format(kw=keyword, days=rng.randint(3, 30))
    cta = str(_pick(rng, CTAS)).format(kw=keyword)

    lines = [
        f"你是不是也这样——刷到{keyword}就心动，一动手就翻车？",
        f"今天用{duration}秒，把{keyword}这件事给你彻底讲透。",
        "第一，先看底层逻辑。" + f"{keyword}真正起作用的地方，从来不是工具，而是你先想清楚要什么。",
        "第二，记住三个关键动作：定目标、拆步骤、留反馈。" + f"别贪多，一次只解决{keyword}里的一个核心问题。",
        f"第三，也是最多人忽略的——{keyword}要做长期主义，爆一次靠运气，持续爆靠体系。",
        cta,
    ]

    shots = []
    for i in range(n_shots):
        jingbie, scene = SHOT_SCENES[i % len(SHOT_SCENES)]
        if i == 0:
            line = hook
        elif i == n_shots - 1:
            line = cta
        else:
            line = lines[1 + (i - 1) % (len(lines) - 2)]
        shots.append({
            "镜号": f"{i + 1:02d}",
            "景别": jingbie,
            "画面": scene.format(kw=keyword),
            "台词": line,
            "时长": f"{round(unit, 1)}s",
        })

    subtitles = [f"{s['镜号']} {s['台词'][:12]}…" if len(s["台词"]) > 12 else f"{s['镜号']} {s['台词']}"
                 for s in shots]
    narration = " ".join(s["台词"] for s in shots)

    return {
        "title": hook,
        "duration": duration,
        "storyboard": shots,
        "narration": narration,
        "subtitles": subtitles,
        "bgm": {
            "style": str(_pick(rng, BGMS)),
            "volume": "-18dB（人声-6dB）",
            "cut_points": "每个分镜切换处对齐节拍",
        },
        "tts_text": narration,
    }


# ---------------- 三平台改写（执行层降级） ----------------

def adapt_platforms(keyword: str, script: dict, platforms: list[str]) -> dict:
    rng = _seed(keyword + "plat")
    title = script["title"]
    out = {}
    for p in platforms:
        meta = PLATFORM_META.get(p)
        if not meta:
            continue
        if p == "douyin":
            out[p] = {
                "name": meta["name"],
                "style_tips": meta["tips"],
                "title": f"{title[:18]}｜{keyword}保姆级教程",
                "copy": (
                    f"🔥 {title}\n\n"
                    f"① 别闷头研究，{keyword}先定目标\n"
                    f"② 拆3步：定目标→拆步骤→留反馈\n"
                    f"③ 长期主义才是王道\n\n"
                    f"👇 评论区扣「1」，攻略直接发你\n"
                    f"#{keyword} #干货分享 #新手必看"
                ),
                "tags": [f"#{keyword}", "#干货分享", "#新手必看", "#三分钟教程"],
            }
        elif p == "bilibili":
            out[p] = {
                "name": meta["name"],
                "style_tips": meta["tips"],
                "title": f"【硬核拆解】{keyword}从入门到上手，一条视频讲透",
                "copy": (
                    f"大家好，我是你的内容搭子。今天聊{keyword}。\n\n"
                    f"先说结论：{title}\n\n"
                    f"接下来我会分三个部分展开——第一部分讲底层逻辑，"
                    f"第二部分给可抄作业的行动清单，第三部分聊聊大多数人踩过的坑。"
                    f"弹幕告诉我你现在卡在哪一步？\n\n"
                    f"（中段互动）你觉得{keyword}最难的是哪步？打在公屏上。\n\n"
                    f"最后，一键三连不迷路，下期出进阶篇。"
                ),
                "tags": [f"#{keyword}", "#教程", "#干货", "#经验分享"],
            }
        else:  # xiaohongshu
            emoji = _pick(rng, ["✨", "🌟", "💫", "🫶", "🍀"])
            out[p] = {
                "name": meta["name"],
                "style_tips": meta["tips"],
                "title": f"{keyword}保姆级攻略｜{rng.randint(3, 6)}个技巧帮你省下{rng.randint(3, 30)}天试错{emoji}",
                "copy": (
                    f"{emoji} 姐妹们！{keyword}这块我终于趟明白了！\n\n"
                    f"📌 划重点：\n"
                    f"1️⃣ 先想清楚目标，别上来就囤工具\n"
                    f"2️⃣ 拆成3步走，每步只解决一个问题\n"
                    f"3️⃣ 留反馈渠道，每周复盘一次\n\n"
                    f"💡 真心话：{keyword}真的不难，难的是开始。\n"
                    f"踩过坑的都懂，方法对了事半功倍{emoji}\n\n"
                    f"评论区聊聊你的经历，互帮互助～\n"
                    f"# {keyword} #新手攻略 #自我提升 #干货笔记 #经验分享"
                ),
                "tags": [f"# {keyword}", "#新手攻略", "#自我提升", "#干货笔记", "#经验分享"],
            }
    return out
