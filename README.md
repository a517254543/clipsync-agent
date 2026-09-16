# 「一拍即合」ClipSync Agent v0.2

> 短视频脚本智造与多平台分发智能体 —— 2026 年宁夏算力 + AI Agent 应用创新大赛 · OPC 轻创赛道

**输入一个关键词，输出一套可拍、可发、可配音的内容包。**

> **开箱即用**：默认「本地模板模式」，**无需配置任何大模型 Key、无需本地 Ollama**，断网也能生成内容包。争点选题、三平台文案、AI 配音全部离线可用；实时热榜需联网，断网自动回退本地研判。

---

## 一、已实现功能（对应项目计划书核心方案）

| 计划书模块 | 落地实现 | 代码位置 |
|---|---|---|
| 1. 热点感知 | **实时热榜接入（微博/抖音/百度）** + 关键词热度实算、受众匹配、选题角度、发布窗口、选题安全分级 | `app/agent/hotsearch.py`、`app/agent/pipeline.py::perceive_live` |
| 2. 脚本生成 | 分镜表（镜号/景别/画面/台词/时长）、完整口播稿、字幕条、BGM 建议 | `app/agent/templates.py::build_script` |
| 3. 平台适配 | 抖音（黄金3秒钩子）/B站（口语长文案+弹幕互动）/小红书（种草笔记+emoji+话题标签） | `app/agent/templates.py::adapt_platforms` |
| 4. AI 配音 | Edge-TTS 免费开源方案，女声晓晓 / 男声云希，输出 mp3 可直接下载 | `app/agent/tts.py` |
| 5. 输出集成 | 结构化 JSON 内容包 + Markdown 脚本文档下载；SaaS 网页 + REST API 双通道 | `app/main.py`、`app/static/index.html` |
| 争点选题 | **stasis 争点选题法离线引擎**：选定热点后确定性产出 3 个备选争点标题（事实争点 + 定义争点），含三要素检验，无需大模型 | `app/agent/stasis.py`、`app/main.py::/api/stasis` |
| 反思层 | 敏感词/绝对化用语检测、AIGC 标识提示、平台风格一致性评分、重写建议 | `app/agent/compliance.py` |
| Token 计量 | 按任务统计输入/输出 Token 与估算成本（5.3 节）；模板模式恒为 0 | `app/agent/llm.py`、`pipeline.py` |

## 一之二、实时热榜接入（感知层数据源）

三个平台均使用公开只读接口，**无需 API Key、无需 Cookie**：

| 平台 | 接口 | 关键字段 |
|---|---|---|
| 微博热搜 | `weibo.com/ajax/side/hotSearch` | `data.realtime[].word / num / realpos`；需带 `Referer: https://weibo.com/`，否则 403 |
| 抖音热榜 | `iesdouyin.com/web/api/v2/hotsearch/billboard/word/` | `word_list[].word / hot_value`；主站 `douyin.com/aweme/v1/web/hot/search/list/` 需 X-Bogus 签名，不可用 |
| 百度热搜 | `top.baidu.com/api/board?platform=wise&tab=realtime` | `data.cards[].content` 为**双层嵌套**，需递归展开取 `word / hotScore` |

工程化处理：
- **三级容错**：单平台失败只影响该列；全部失败则感知层回落本地研判引擎（`perceive_live` 返回 `None`）。
- **缓存**：10 分钟内存缓存，对应计划书 5.2 节「热点摘要缓存」，`?refresh=1` 可强制拉取。
- **热度实算**：`热度分 = 基础分 + 排名加权 + 跨平台覆盖加权`，命中榜首最高 96 分；未上榜按长尾计 42 分。
- **选题安全分级**：涉政 / 灾难事故 / 社会案件类词条标记 `safe=False`，在热榜列表标 ⚠，并带入反思层给出「不建议商业化改编」提示。

新增接口：`GET /api/hotsearch?source=weibo|douyin|baidu|all&limit=20&refresh=false`

## 一之三、争点选题引擎（stasis-topic，离线确定性）

选定热点关键词后，调用 `stasis-topic` 争点选题法产出 3 个备选标题，**完全不依赖大模型 / 本地 Ollama**。

方法论（亚里士多德修辞学 stasis 争点理论）：选题 = 共同事实 + 不同解释 + 必须判断的问题；
输出句式统一为「[现象]，真的是[流行解释／候选定义]吗？」一个候选定义 = 一个选题。

- `app/agent/stasis.py::propose(keyword, industry)` 按领域模板库（文旅/电商/餐饮/教育/职场/婚恋/社会/知识付费/通用）确定性产出：
  - **事实争点** 1 条（质疑被热议的既定说法，把结论打回成问题）
  - **定义争点** 2 条（把现象重新定义成两个可站队的候选定义）
  - 三要素检验（共同事实 ✓ / 不同解释 ✓ / 必须判断 ✓）
- 网页端：点击实时热榜任意词条 → 自动在该词下方展示 3 个争点选题标题 → 点击任一标题填入「定制标题」→ 生成时覆盖自动标题（三平台文案随之采用）。
- 接口：`GET /api/stasis?keyword=xxx&industry=文旅`

## 二、架构：感知—规划—执行—反思

```
用户关键词
   │
 ① 感知  热点研判：热度评分 / 受众 / 选题角度 / 发布窗口
   │
 ② 规划  脚本大纲：黄金3秒钩子 → 3个核心论点 → CTA
   │
 ③ 执行  分镜表 + 口播稿 + BGM + 三平台文案 + TTS 音频
   │
 ④ 反思  敏感词检测 / 绝对化用语 / AIGC 标识 / 风格一致性评分 / 重写建议
   │
 输出   JSON 内容包 · Markdown 脚本 · MP3 配音
```

## 三、快速启动

### 方式一：exe 可执行程序（推荐，双击即用）

**直接下载 → [ClipSyncAgent-v0.2-win64.exe](https://github.com/a517254543/clipsync-agent/releases/latest/download/ClipSyncAgent-v0.2-win64.exe)**（18.9 MB，免安装）

1. 双击 `ClipSyncAgent-v0.2-win64.exe`；
2. 控制台窗口显示服务地址，**浏览器会自动打开**；
3. 用完后关闭控制台窗口即可退出。

> 无需安装 Python 和任何依赖。首次启动需解压约 10-20 秒，属正常现象。
> 端口被占用时自动切换到 8522、8523…；
> 配音音频与 JSON 内容包保存在 exe 同级 `output/` 目录；
> 接入大模型时编辑 exe 同级 `config.json` 填入 api_key 后重启。
> exe 未经代码签名，Windows SmartScreen 可能提示「未知发布者」，选择「仍要运行」即可。

### 方式二：源码运行

```bash
# 1. 安装依赖
pip install -r requirements.txt

# 2. 启动服务
uvicorn app.main:app --host 127.0.0.1 --port 8521

# 3. 打开网页
http://127.0.0.1:8521
```

### 打包命令（供维护）

```bash
pip install pyinstaller
pyinstaller --noconfirm --clean --onefile --console --name "一拍即合ClipSyncAgent" \
  --hidden-import uvicorn.loops.auto --hidden-import uvicorn.protocols.http.auto \
  --hidden-import uvicorn.protocols.http.h11_impl \
  --hidden-import uvicorn.protocols.http.httptools_impl \
  --hidden-import uvicorn.protocols.websockets.auto --hidden-import uvicorn.lifecycle.on \
  --hidden-import uvicorn.logging --hidden-import app.main \
  --collect-all edge_tts --collect-all aiohttp \
  --add-data "app/static;app/static" --add-data "config.json;." \
  --exclude-module tkinter launcher.py
```

> 关键适配：`app/paths.py` 处理 frozen 模式路径——内置资源在 `sys._MEIPASS`，
> 用户数据（output、config.json）落在 exe 同级目录，保证打包后既可读又可写。

## 四、两种运行模式

- **本地模板模式（默认，开箱即用）**：**无需任何 API Key、无需本地 Ollama、断网可用**。基于关键词哈希的确定性模板引擎 + 离线 stasis 争点选题法生成内容包。对应计划书 5.4 节"网络断连时降级为本地模板生成"。**本项目默认即此模式，不配置任何模型也能完整使用全部功能。**
- **大模型模式（可选增强）**：在 `config.json` 中填入 `llm.api_key` / `base_url` / `model`（兼容 DeepSeek、Qwen、GLM 等 OpenAI 格式接口），界面自动切换为大模型生成；**任何一步调用失败（含地址不可达、本地 Ollama 未启动）都会快速降级回模板引擎**（连接超时仅 5 秒），保证服务不中断。

```json
{ "llm": { "api_key": "sk-xxx", "base_url": "https://api.deepseek.com/v1", "model": "deepseek-chat" } }
```

本地 Ollama 示例（可选，未安装则保持默认空 key 即可，程序自动走模板模式）：

```json
{ "llm": { "api_key": "ollama", "base_url": "http://localhost:11434/v1", "model": "qwen2.5:7b" } }
```

> 若填了 `base_url` 但对应服务不可达（如 Ollama 未启动），程序会在 5 秒内判定失败并自动回落模板引擎，**不会卡住生成**。

也可用环境变量：`LLM_API_KEY` / `LLM_BASE_URL` / `LLM_MODEL`。

## 五、API 接口

| 方法 | 路径 | 说明 |
|---|---|---|
| GET | `/api/health` | 健康检查 |
| GET | `/api/config` | 当前运行模式、可用音色 |
| GET | `/api/hotsearch` | 微博/抖音/百度实时热榜（source/limit/refresh） |
| GET | `/api/stasis` | 争点选题法：给定关键词确定性产出 3 个备选标题（无需大模型） |
| POST | `/api/generate` | 生成完整内容包（keyword / duration / industry / platforms / title） |
| POST | `/api/tts` | Edge-TTS 配音合成，返回 mp3 地址 |

调用示例：

```bash
curl -X POST http://127.0.0.1:8521/api/generate \
  -H "Content-Type: application/json" \
  -d '{"keyword":"沙坡头星空营地","duration":60,"industry":"文旅","platforms":["douyin","bilibili","xiaohongshu"]}'
```

## 六、后续迭代建议（v0.3 路线）

1. **LoRA 微调**：用宁夏本地文旅/电商/餐饮语料微调 7B 模型，承担改写与校验，落实 5.2 节"大模型创意 + 小模型改写"分流（已内置 OpenAI 兼容接口与自动降级，接上即生效）。
2. **多租户与计费**：引入租户表与 Token 用量落库，对接运营商算力券抵扣字段。
3. **剪映/ CapCut 草稿导出**：直接生成可导入的工程文件，缩短从脚本到成片的最后一公里。
4. **热榜订阅推送**：每日定时抓取榜单，自动挑出与行业相关的 TOP 选题推送给用户，把感知层从被动变主动。
