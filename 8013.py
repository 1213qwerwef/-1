import json
import logging
import time
from pathlib import Path
from typing import Dict, List

from fastapi import FastAPI, HTTPException, Body
from openai import OpenAI
import uvicorn

from env_config import OPENAI_API_KEY, OPENAI_BASE_URL

# ✅ 新增：繁体转简体
from opencc import OpenCC

cc = OpenCC('t2s')

# =============================
# 日志配置
# =============================
LOGS_DIR = Path("logs")
LOGS_DIR.mkdir(exist_ok=True)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s",
    handlers=[
        logging.FileHandler(LOGS_DIR / "app.log", encoding="utf-8"),
        logging.StreamHandler()
    ]
)

logger = logging.getLogger(__name__)

# =============================
# OpenAI 客户端
# =============================
client = OpenAI(
    api_key=OPENAI_API_KEY,
    base_url=OPENAI_BASE_URL,
    timeout=180
)

# =============================
# FastAPI 初始化
# =============================
app = FastAPI()

# =============================
# Prompt（不动）
# =============================
PROMPT = """
你是由全球顶尖亚马逊电商类目分析专家。

========================
【强制输出规则（必须遵守）】
========================
1. 只允许输出 JSON，禁止输出任何解释、说明、前缀、后缀。
2. JSON 字段名必须为英文，字段值必须为【纯中文】。
3. 严禁出现任何英文单词、字母、符号（如 LED / FDA / CE / USD 等）。
4. 所有内容必须是中文表达（例如：美元、认证名称需翻译为中文或用通用中文说法）。
5. 每个字段如果有多个要点，必须使用“\\n”进行换行：
   - 每一个要点单独一行
   - 不允许使用分号、逗号拼接多个要点
6. 禁止使用：
   - 分号 ;
   - 英文括号 ()
   - 英文编号 1) 2)
7. 必须使用中文编号格式：
   - 一、二、三、四 或
   - ①②③（推荐）
8. 所有字段必须存在，不允许缺失，即使为空也必须返回 ""。
9. 输出前必须自检：
   - 是否存在英文？如果有 → 重新生成
   - 是否未换行？如果有 → 重新生成

========================
【输入数据说明】
========================
你将收到：
- category_url：类目地址
- subcategory：小类（可能为空）
- products：产品列表（包含标题、描述、价格）

========================
【分析任务】
========================

你需要基于所有 products 聚合分析，输出以下四个维度：

--------------------------------
1. 类目产品分类
--------------------------------
要求：
- 按产品标题、描述、结构、功能、是否带电、材质、配置进行归类
- 分类必须符合行业逻辑
- 不要过度细分
- 每一类单独一行

示例格式：
① 面部光疗美容仪
② 手持按摩仪
③ 微电流紧致设备

--------------------------------
2. 产品分类价格带
--------------------------------
要求：
- 每个分类对应一个价格区间
- 使用“美元”中文表达
- 每个分类一行

示例：
面部光疗美容仪：80-300美元
手持按摩仪：20-120美元

--------------------------------
3. 每个产品分类入场分析推荐
--------------------------------
要求：
- 每个分类一行
    针对“类目产品分类”中的每一个分类，结合以下因素进行分析：
    - 产品复杂度
    - 是否带电
    - 是否涉及认证
    - 价格带
    - 市场集中度
    - 产品结构差异
- 必须包含：难度 + 是否建议进入 + 原因

示例：
面部光疗美容仪：门槛较高，不建议新卖家进入，涉及技术与安全要求高
手持按摩仪：门槛较低，适合新卖家进入，结构简单竞争适中

--------------------------------
4. 类目所需认证
--------------------------------
规则：

- 如果 subcategory 不为空：
  至少输出 5 条认证（中文表达）
  示例：
  ① 美国食品药品监督管理认证
  ② 电气安全认证
  ③ 电磁兼容认证
  ④ 有害物质限制认证
  ⑤ 锂电池运输安全认证

- 如果 subcategory 为空：
  输出：
  无小类目抓取

========================
【输出格式（唯一合法输出）】
========================
{
  "category_url": "原始输入",
  "summary": {
    "Category Product Types": "",
    "Category Price Ranges": "",
    "Entry Recommendation by Product Type": "",
    "Required Certifications": ""
  }
}

========================
【最终强制检查（极其重要）】
========================
输出前请再次确认：
✔ 是否全部为中文
✔ 是否每个要点已换行（\\n）
✔ 是否没有英文字符
✔ 是否没有使用分号

如果不符合，请自动重新生成，直到完全符合要求
"""

# =============================
# 结果目录
# =============================
RESULTS_DIR = Path("results")
RESULTS_DIR.mkdir(exist_ok=True)

# =============================
# ✅ 工具函数：强制转简体
# =============================
def force_simplified(obj):
    if isinstance(obj, dict):
        return {k: force_simplified(v) for k, v in obj.items()}
    elif isinstance(obj, list):
        return [force_simplified(i) for i in obj]
    elif isinstance(obj, str):
        return cc.convert(obj)
    else:
        return obj

# =============================
# ✅ 工具函数：检测英文
# =============================
def contains_english(text):
    return any(c.isascii() and c.isalpha() for c in text)

def validate_no_english(obj):
    if isinstance(obj, dict):
        return all(validate_no_english(v) for v in obj.values())
    elif isinstance(obj, list):
        return all(validate_no_english(i) for i in obj)
    elif isinstance(obj, str):
        return not contains_english(obj)
    return True

# =============================
# ✅ 工具函数：结构兜底
# =============================
def ensure_structure(summary):
    return {
        "Category Product Types": summary.get("Category Product Types", ""),
        "Category Price Ranges": summary.get("Category Price Ranges", ""),
        "Entry Recommendation by Product Type": summary.get("Entry Recommendation by Product Type", ""),
        "Required Certifications": summary.get("Required Certifications", "")
    }

# =============================
# 本地缓存查询
# =============================
def find_existing_result(category_url):
    for file in RESULTS_DIR.glob("analysis_result_*.json"):
        try:
            with open(file, "r", encoding="utf-8") as f:
                data = json.load(f)

            if data.get("category_url") == category_url:
                logger.info(f"Found cached result: {file}")
                return data
        except Exception:
            continue

    return None

# =============================
# 类目聚合分析（核心增强点）
# =============================
def analyze_category(category_url, subcategory, products, retries=5):

    payload = {
        "category_url": category_url,
        "subcategory": subcategory,
        "products": products
    }

    for attempt in range(retries):
        try:
            logger.info(f"AI attempt: {attempt+1}")

            response = client.chat.completions.create(
                model="gpt-5-mini",
                messages=[
                    {"role": "system", "content": PROMPT},
                    {"role": "user", "content": json.dumps(payload, ensure_ascii=False)}
                ],
                temperature=1
            )

            content = response.choices[0].message.content.strip()

            parsed = json.loads(content)

            # ✅ 1. 强制转简体
            parsed = force_simplified(parsed)

            # ✅ 2. 结构兜底
            summary = ensure_structure(parsed.get("summary", {}))

            # ✅ 3. 英文检测（不通过直接重试）
            if not validate_no_english(summary):
                logger.warning("检测到英文，重试")
                raise ValueError("存在英文")

            time.sleep(2)

            return summary

        except Exception as e:
            logger.error(f"Analysis attempt {attempt+1} failed: {e}")
            time.sleep(2)

    # 最终兜底
    return {
        "Category Product Types": "",
        "Category Price Ranges": "",
        "Entry Recommendation by Product Type": "",
        "Required Certifications": ""
    }

# =============================
# API 接口
# =============================
@app.post("/analyze")
async def analyze(data: dict = Body(...)):
    if "category_url" not in data or "products" not in data:
        raise HTTPException(status_code=400, detail="JSON 必须包含 category_url 和 products")

    category_url = data["category_url"]
    products = data["products"]
    subcategory = data.get("subcategory", "")

    logger.info(f"Received category: {category_url}")
    logger.info(f"Product count: {len(products)}")

    # 缓存
    cached = find_existing_result(category_url)
    if cached:
        logger.info("Using cached analysis result")
        return cached

    # AI分析
    summary = analyze_category(category_url, subcategory, products)

    result_data = {
        "category_url": category_url,
        "summary": summary
    }

    # 保存
    timestamp = time.strftime("%Y%m%d_%H%M%S")
    output_file = RESULTS_DIR / f"analysis_result_{timestamp}.json"

    with open(output_file, "w", encoding="utf-8") as f:
        json.dump(result_data, f, ensure_ascii=False, indent=2)

    logger.info(f"Result saved to {output_file}")

    return result_data

# =============================
# 启动服务
# =============================
if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8013, workers=1)