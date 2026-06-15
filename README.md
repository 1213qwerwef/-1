# TAAPI 微服务集群技术文档（8005–8013）

## 一句话总结（给技术大佬）

**这是一套面向 Amazon 电商选品与竞品调研的 Python 微服务集群：9 个独立 FastAPI 进程各占 8005–8013 端口，通过 OpenAI / DeepSeek 大模型完成品牌官网、社媒、评论洞察、准入认证、类目聚合、PPC 指标、Google Trends 等 AI 推理，结果以本地 JSON 文件缓存并对外暴露 REST POST 接口。**

---

## 1. 项目概述

本项目由 **9 个相互独立的 Python 微服务** 组成，每个服务对应一个端口、一个业务场景。服务之间无进程内耦合，由上游调用方（如爬虫、ETL、前端编排）按端口分别 HTTP 调用。

整体定位：**Amazon / 跨境电商数据分析的 AI 推理层**，输入结构化 JSON，输出结构化 JSON，并持久化到本地 `results/`、`outputs/`、`cache/` 目录。

```
┌─────────────────────────────────────────────────────────────┐
│                    上游调用方（爬虫 / 编排）                    │
└──────────┬──────────┬──────────┬──────────┬───────────────┘
           │          │          │          │
     :8005  │   :8006  │   :8007  │  :8008…8013
           ▼          ▼          ▼          ▼
┌──────────────────────────────────────────────────────────────┐
│  FastAPI + Uvicorn（9 个独立进程，workers=1）                  │
└──────────────────────────────────────────────────────────────┘
           │                              │
           ▼                              ▼
┌─────────────────────┐        ┌─────────────────────┐
│ OpenAI 兼容 API      │        │ DeepSeek API         │
│（.env 私人代理地址）  │        │ (api.deepseek.com)   │
└─────────────────────┘        └─────────────────────┘
           │                              │
           ▼                              ▼
┌──────────────────────────────────────────────────────────────┐
│  本地持久化：results/ · outputs/ · cache/ · logs/            │
└──────────────────────────────────────────────────────────────┘
```

---

## 2. 技术栈

| 类别 | 技术 | 说明 |
|------|------|------|
| Web 框架 | **FastAPI** | 所有服务的 HTTP 层，自动生成 OpenAPI 文档 |
| ASGI 服务器 | **Uvicorn** | 单 worker 启动，监听 `0.0.0.0` |
| 数据校验 | **Pydantic** (`BaseModel`) | 请求体模型定义（8005、8006、8007 等） |
| AI 客户端 | **OpenAI Python SDK** | 调用 GPT / o4-mini / gpt-5-mini 等模型 |
| HTTP 客户端 | **httpx** | 8006 直接 POST DeepSeek Chat Completions |
| 中文处理 | **OpenCC** (`opencc-python-reimplemented`) | 8013 繁体转简体 + 英文检测 |
| 并发 | **asyncio** | 8005 异步批量查询、重试、文件 IO |
| 存储 | **本地 JSON 文件** | 无数据库，结果/缓存/日志均落盘 |
| 日志 | **Python logging** | 文件 + 控制台双输出 |

### AI 模型使用情况

| 端口 | 模型 | 接入方式 |
|------|------|----------|
| 8005 | `o4-mini` | OpenAI SDK → `.env` 中配置的兼容代理 |
| 8006 | `deepseek-chat` | httpx → `api.deepseek.com/v1/chat/completions` |
| 8007 | `gpt-4o` | OpenAI SDK → `.env` 中配置的兼容代理 |
| 8008 / 8009 / 8010 / 8011 / 8013 | `gpt-5-mini` | OpenAI SDK → `.env` 中配置的兼容代理 |
| 8012 | `deepseek-chat` | OpenAI SDK → `api.deepseek.com` |

---

## 3. 通用架构特征

所有服务共享以下设计模式：

1. **单文件单服务**：`8005.py` ~ `8013.py` 各自独立，可单独 `python 800x.py` 启动。
2. **JSON 入 / JSON 出**：REST POST，Content-Type `application/json`。
3. **本地缓存**：多数服务读取 `results/` 历史文件，按 ASIN / category_url / categoryname 等 key 去重，避免重复调用 AI。
4. **结果落盘**：每次分析写入带时间戳的 JSON 文件，便于审计与断点续跑。
5. **重试机制**：AI 调用失败时 2–5 次重试，部分服务带 3–5 秒 sleep 限流。
6. **日志目录**：`logs/` 下按服务记录运行日志。
7. **环境变量**：API Key 与 OpenAI 代理地址统一由 `.env` + `env_config.py` 加载，勿写入源码或公开文档。

> **安全提示**：`.env` 含 API Key 及 **私人 OpenAI 兼容代理地址**（`OPENAI_BASE_URL`），仅本地或内网使用，禁止提交版本库或在 README / 技术文档中暴露真实 URL。公开仓库请参考 `env配置说明.txt` 中的占位符模板。

---

## 4. 服务明细

### 4.1 端口 8005 — 品牌官网查询

| 项 | 内容 |
|----|------|
| 文件 | `8005.py` |
| 服务名 | 品牌官网查询接口 |
| 端点 | `POST /tool/find-official-site-batch` |
| 功能 | 批量根据品牌名（+ 可选 ASIN）查询官方主页 URL |
| AI | OpenAI `o4-mini`，`client.responses.create` |
| 缓存 | `cache/asin_cache.json`、`cache/brand_cache.json`、`cache/queried_brands.json` |
| 输出 | `results/brand_*.json`、`results/complete_results_*.json` |

**请求示例：**

```json
{
  "data": [
    ["BrandName", "B0XXXXXXXX"],
    ["AnotherBrand"]
  ]
}
```

**响应字段：** `total`、`start_time`、`end_time`、`duration_seconds`、`results`（key 为 ASIN 或品牌名，value 为官网 URL 或 null）

**特性：** 唯一性去重、ASIN/品牌双级缓存、逐条 5 秒间隔、最多 3 次 AI 重试。

---

### 4.2 端口 8006 — 社媒链接提取（AI 版）

| 项 | 内容 |
|----|------|
| 文件 | `8006.py` |
| 服务名 | 社媒链接提取接口（AI版） |
| 端点 | `POST /tool/extract-social-links` |
| 功能 | 根据品牌官网 URL，AI 推断 Instagram / Facebook / Twitter / YouTube / TikTok 官方账号 |
| AI | DeepSeek `deepseek-chat`（httpx 直连） |
| 输出 | `results/social_results.json` |

**请求示例：**

```json
{
  "data": {
    "B0XXXXXXXX": "https://www.example-brand.com",
    "B0YYYYYYYY": "https://another-brand.com"
  }
}
```

**响应：** 每个 ASIN 对应 5 个社媒字段，经域名规则校验后返回有效链接或 null。

---

### 4.3 端口 8007 — 产品评论 AI 分析

| 项 | 内容 |
|----|------|
| 文件 | `8007.py` |
| 服务名 | 产品评论 AI 分析接口 |
| 端点 | `POST /analyze` |
| 功能 | 对商品评论做五维聚合洞察分析 |
| AI | GPT-4o |
| 输出 | `outputs/analysis_result_{request_id}.json` |

**分析维度（每维 5 条）：**

- 好评分析
- 差评分析
- 未满足需求
- 购买动机
- 人群场景分析

每条洞察含：描述、原因、提及评论数、评论占比（百分比格式）。

**请求示例：**

```json
[
  {
    "product_id": "B0XXXXXXXX",
    "comments": ["评论1", "评论2", "..."]
  }
]
```

**响应：** `success`、`request_id`、`products[]`（含 `cached` 标记）。

---

### 4.4 端口 8008 — Amazon 准入认证分析（增强版）

| 项 | 内容 |
|----|------|
| 文件 | `8008.py` |
| 端点 | `POST /analyze` |
| 功能 | 根据 ASIN + 产品标题，推断 Amazon US 上架所需认证文件 |
| AI | gpt-5-mini |
| 差异点 | **每产品至少 5 条认证**；**分批处理**（batch_size=10）；ASIN 级缓存 |

**请求示例：**

```json
[
  {"asin": "B0XXXXXXXX", "category_name": "Wireless Bluetooth Headphones"}
]
```

**响应：**

```json
[
  {"asin": "B0XXXXXXXX", "required certificates": ["FCC", "CE", "..."]}
]
```

---

### 4.5 端口 8009 — Amazon 准入认证分析（标准版）

| 项 | 内容 |
|----|------|
| 文件 | `8009.py` |
| 端点 | `POST /analyze` |
| 功能 | 与 8008 同类，推断 US 站认证要求 |
| AI | gpt-5-mini |
| 差异点 | 无「至少 5 条」强制；**整批一次** AI 调用，无分批 |

输入输出格式与 8008 相同。

---

### 4.6 端口 8010 — 类目产品属性聚合

| 项 | 内容 |
|----|------|
| 文件 | `8010.py` |
| 端点 | `POST /analyze` |
| 功能 | 聚合类目下所有产品标题与描述，输出三维中文摘要 |
| AI | gpt-5-mini |

**三个固定维度：**

1. 物理结构（尺寸、材质、颜色等）
2. 功能属性
3. 使用场景

**请求示例：**

```json
{
  "category_url": "https://www.amazon.com/...",
  "products": {
    "Product Title A": ["desc1", "desc2"],
    "Product Title B": ["desc1"]
  }
}
```

---

### 4.7 端口 8011 — Amazon PPC / SPR / CPA 分析

| 项 | 内容 |
|----|------|
| 文件 | `8011.py` |
| 端点 | `POST /analyze` |
| 功能 | 对类目 Top 关键词（PPC、SPR）去重后计算平均值及 CPA |
| AI | gpt-5-mini（Prompt 内嵌计算规则，由 AI 执行） |
| 缓存 key | `categoryname` |

**计算公式（Prompt 约定）：**

- PPC 平均 = 去重关键词 PPC 之和 / N
- SPR 平均 = 去重关键词 SPR 之和 / N
- CPA = PPC 平均 / 5%

**请求示例：**

```json
[
  {
    "categoryname": "https://www.amazon.com/gp/bestsellers/...",
    "top_keywords": [
      {"keyword": "keyword1", "PPC": 1.20, "SPR": 150}
    ]
  }
]
```

**响应：**

```json
[
  {"categoryname": "...", "PPC": "1.18", "CPA": "23.60", "SPR": 150}
]
```

---

### 4.8 端口 8012 — Google Trends 趋势分析

| 项 | 内容 |
|----|------|
| 文件 | `8012.py` |
| 端点 | `POST /analyze` |
| 功能 | 对每个类目 URL 下 1–3 个关键词的 Trends 时序数据做独立分析 |
| AI | DeepSeek `deepseek-chat` |
| 校验 | 输出必须 3 行、关键词原文一致、结果 JSON 校验 |

**每个关键词分析四项：**

- 起势时间
- 2025 比 2024 增长率
- 旺季月份
- 淡季月份

**请求示例：**

```json
{
  "https://example.com/category/screwdrivers": {
    "cordless screwdriver": [
      {"date": "2024/01/01", "value": 45}
    ],
    "electric screwdriver": [
      {"date": "2024/01/01", "value": 30}
    ]
  }
}
```

**响应：** 每个 URL 对应长度为 3 的中文字符串数组。

---

### 4.9 端口 8013 — Amazon 类目深度分析

| 项 | 内容 |
|----|------|
| 文件 | `8013.py` |
| 端点 | `POST /analyze` |
| 功能 | 类目级选品分析：产品分类、价格带、入场建议、所需认证 |
| AI | gpt-5-mini |
| 后处理 | OpenCC 繁转简、英文字符检测、结构兜底、最多 5 次重试 |
| 缓存 | 按 `category_url` 命中历史 `analysis_result_*.json` |

**四个输出维度（summary 内）：**

| 字段 | 含义 |
|------|------|
| Category Product Types | 类目产品分类 |
| Category Price Ranges | 各分类价格带 |
| Entry Recommendation by Product Type | 各分类入场难度与建议 |
| Required Certifications | 类目所需认证（subcategory 为空则返回「无小类目抓取」） |

**请求示例：**

```json
{
  "category_url": "https://www.amazon.com/...",
  "subcategory": "Facial Devices",
  "products": [
    {"title": "...", "description": "...", "price": "99.99"}
  ]
}
```

---

## 5. 端口速查表

| 端口 | 端点 | 业务 | AI 模型 |
|------|------|------|---------|
| **8005** | `POST /tool/find-official-site-batch` | 品牌官网批量查询 | o4-mini |
| **8006** | `POST /tool/extract-social-links` | 官网 → 社媒链接 | deepseek-chat |
| **8007** | `POST /analyze` | 评论五维洞察 | gpt-4o |
| **8008** | `POST /analyze` | 准入认证（≥5 条，分批） | gpt-5-mini |
| **8009** | `POST /analyze` | 准入认证（标准） | gpt-5-mini |
| **8010** | `POST /analyze` | 类目属性三维聚合 | gpt-5-mini |
| **8011** | `POST /analyze` | PPC / SPR / CPA | gpt-5-mini |
| **8012** | `POST /analyze` | Google Trends 分析 | deepseek-chat |
| **8013** | `POST /analyze` | 类目选品深度分析 | gpt-5-mini |

---

## 6. 启动方式

每个服务独立启动（需预先安装依赖）：

```bash
# 建议依赖（项目未提供 requirements.txt，需自行安装）
pip install fastapi uvicorn pydantic openai httpx opencc-python-reimplemented

# 分别启动（9 个终端或后台进程）
python 8005.py   # → http://0.0.0.0:8005
python 8006.py   # → http://0.0.0.0:8006
python 8007.py   # → http://0.0.0.0:8007
python 8008.py   # → http://0.0.0.0:8008
python 8009.py   # → http://0.0.0.0:8009
python 8010.py   # → http://0.0.0.0:8010
python 8011.py   # → http://0.0.0.0:8011
python 8012.py   # → http://0.0.0.0:8012
python 8013.py   # → http://0.0.0.0:8013
```

启动后可访问各端口 Swagger 文档：

- `http://<host>:800x/docs`

> **注意**：`8005.py` 启动命令写为 `uvicorn.run("main:app", ...)`，若文件名不是 `main.py` 需改为 `uvicorn.run(app, ...)` 或 `uvicorn.run("8005:app", ...)`，否则启动会失败。

---

## 7. 目录结构

```
taapi/
├── 8005.py ~ 8013.py    # 9 个微服务入口
├── env_config.py        # 环境变量加载（不含敏感默认值）
├── env配置说明.txt       # 配置模板（无真实代理地址）
├── .env                 # 本地私密配置（已 gitignore，勿提交）
├── cache/               # 8005 品牌/ASIN 缓存
├── results/             # 多数服务的分析结果
├── outputs/             # 8007 评论分析结果
└── logs/                # 各服务运行日志
```

---

## 8. 已知问题与改进建议

| 问题 | 建议 |
|------|------|
| 私人代理地址泄露 | `OPENAI_BASE_URL` 仅写在 `.env`，公开文档用占位符 |
| 8005 启动模块名错误 | 修正为 `"8005:app"` 或直接 `uvicorn.run(app, ...)` |
| 无统一 requirements.txt | 补充依赖清单与版本锁定 |
| 无鉴权 / 限流 | 生产环境加 API Key 中间件或网关 |
| 文件缓存无并发锁 | 多 worker 或并发写时需加文件锁或换 Redis |
| 8011 错误兜底字段名错误 | batch 失败时返回 `required certificates` 应为 PPC/CPA/SPR 结构 |

---

## 9. 业务链路关系（可选编排）

典型 Amazon 选品分析流水线可按以下顺序调用：

```
8005 查品牌官网
  → 8006 提取社媒
  → 8007 分析评论
  → 8008/8009 查准入认证
  → 8010 聚合类目属性
  → 8011 算 PPC/CPA
  → 8012 分析 Trends
  → 8013 输出类目选品结论
```

各步骤相互独立，由上游系统按需组合，非强制串行。

---

*文档生成时间：2026-06-12 · 基于 `8005.py`–`8013.py` 源码整理*
