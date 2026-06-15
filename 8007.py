import json
import re
import logging
from time import sleep
from typing import List
from datetime import datetime
from pathlib import Path

from fastapi import FastAPI
from pydantic import BaseModel
from openai import OpenAI
import uvicorn

from env_config import OPENAI_API_KEY, OPENAI_BASE_URL

# ==============================
# 配置
# ==============================
MODEL_NAME = "gpt-4o"

DIMENSIONS = [
    "好评分析",
    "差评分析",
    "未满足需求",
    "购买动机",
    "人群场景分析"
]

# ==============================
# 日志 & 输出目录
# ==============================
LOG_DIR = Path("logs")
LOG_DIR.mkdir(exist_ok=True)

OUTPUT_DIR = Path("outputs")
OUTPUT_DIR.mkdir(exist_ok=True)

log_file = LOG_DIR / f"app_{datetime.now().strftime('%Y%m%d')}.log"

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(message)s",
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler(log_file, encoding="utf-8")
    ]
)

logger = logging.getLogger(__name__)

# ==============================
# FastAPI 初始化
# ==============================
app = FastAPI(title="产品评论 AI 分析接口")

client = OpenAI(
    api_key=OPENAI_API_KEY,
    base_url=OPENAI_BASE_URL,
    timeout=60
)

# ==============================
# 请求体
# ==============================
class ProductComments(BaseModel):
    product_id: str
    comments: List[str]


# ==============================
# AI分析函数
# ==============================
def analyze_comments(comments: List[str]) -> dict:

    total_comments = len(comments)

    logger.info(f"开始 AI 分析 评论数: {total_comments}")

    prompt = f"""
请作为电商评论分析专家，对用户评论进行聚合洞察分析。

评论总数：{total_comments}

评论内容：
{comments}

分析要求：

1. 每个维度总结 **5条核心洞察**
2. 每条洞察必须包含：
   - 描述
   - 原因
   - 提及评论数（大约多少评论提到）
   - 评论占比

3. 评论占比计算规则：
评论占比 = 提及评论数 / 评论总数 × 100%
输出格式必须为百分比，例如：
25%
10%
5%
禁止输出小数格式（如 0.25 或 0.10）

严格输出 JSON，每个维度正好5条，禁止尾逗号，每条必须包含 "描述"、"原因"、"提及评论数"、"评论占比"。  
五个维度：
1. 好评分析
2. 差评分析
3. 未满足需求
4. 购买动机
5. 人群场景分析

输出示例：
{{
  "好评分析": [
    {{"描述": "XXX", "原因": "XXX", "提及评论数": "XXX", "评论占比":  "XXX"}},
    {{"描述": "XXX", "原因": "XXX", "提及评论数": "XXX", "评论占比":  "XXX"}},
    {{"描述": "XXX", "原因": "XXX", "提及评论数": "XXX", "评论占比":  "XXX"}},
    {{"描述": "XXX", "原因": "XXX", "提及评论数": "XXX", "评论占比":  "XXX"}},
    {{"描述": "XXX", "原因": "XXX", "提及评论数": "XXX", "评论占比":  "XXX"}}
  ],
  "差评分析": [
    {{"描述": "XXX", "原因": "XXX", "提及评论数": "XXX", "评论占比":  "XXX"}},
    {{"描述": "XXX", "原因": "XXX", "提及评论数": "XXX", "评论占比":  "XXX"}},
    {{"描述": "XXX", "原因": "XXX", "提及评论数": "XXX", "评论占比":  "XXX"}},
    {{"描述": "XXX", "原因": "XXX", "提及评论数": "XXX", "评论占比":  "XXX"}},
    {{"描述": "XXX", "原因": "XXX", "提及评论数": "XXX", "评论占比":  "XXX"}}
  ],
  "未满足需求": [
    {{"描述": "XXX", "原因": "XXX", "提及评论数": "XXX", "评论占比":  "XXX"}},
    {{"描述": "XXX", "原因": "XXX", "提及评论数": "XXX", "评论占比":  "XXX"}},
    {{"描述": "XXX", "原因": "XXX", "提及评论数": "XXX", "评论占比":  "XXX"}},
    {{"描述": "XXX", "原因": "XXX", "提及评论数": "XXX", "评论占比":  "XXX"}},
    {{"描述": "XXX", "原因": "XXX", "提及评论数": "XXX", "评论占比":  "XXX"}}
  ],
  "购买动机": [
    {{"描述": "XXX", "原因": "XXX", "提及评论数": "XXX", "评论占比":  "XXX"}},
    {{"描述": "XXX", "原因": "XXX", "提及评论数": "XXX", "评论占比":  "XXX"}},
    {{"描述": "XXX", "原因": "XXX", "提及评论数": "XXX", "评论占比":  "XXX"}},
    {{"描述": "XXX", "原因": "XXX", "提及评论数": "XXX", "评论占比":  "XXX"}},
    {{"描述": "XXX", "原因": "XXX", "提及评论数": "XXX", "评论占比":  "XXX"}}
  ],
  "人群场景分析": [
    {{"描述": "XXX", "原因": "XXX", "提及评论数": "XXX", "评论占比":  "XXX"}},
    {{"描述": "XXX", "原因": "XXX", "提及评论数": "XXX", "评论占比":  "XXX"}},
    {{"描述": "XXX", "原因": "XXX", "提及评论数": "XXX", "评论占比":  "XXX"}},
    {{"描述": "XXX", "原因": "XXX", "提及评论数": "XXX", "评论占比":  "XXX"}},
    {{"描述": "XXX", "原因": "XXX", "提及评论数": "XXX", "评论占比":  "XXX"}}
  ]
}}

6. 禁止Markdown
7. 禁止解释文本
8. JSON必须合法
"""

    response = client.chat.completions.create(
        model=MODEL_NAME,
        messages=[{"role": "user", "content": prompt}],
        max_completion_tokens=8192
    )

    raw_output = response.choices[0].message.content.strip()

    # 清理代码块
    raw_output = re.sub(r"^```json", "", raw_output)
    raw_output = re.sub(r"```$", "", raw_output).strip()

    # 清理尾逗号
    raw_output = re.sub(r",\s*}", "}", raw_output)
    raw_output = re.sub(r",\s*]", "]", raw_output)

    try:
        result = json.loads(raw_output)
    except Exception:
        logger.error("JSON解析失败")
        logger.error(raw_output)
        raise

    # ==============================
    # 数据补齐
    # ==============================
    for dim in DIMENSIONS:

        items = result.get(dim, [])

        # 补齐不足 5 条
        while len(items) < 5:
            items.append({
                "描述": "无",
                "原因": "无",
                "提及评论数": 0,
                "评论占比": "0%"
            })

        # 按评论占比从大到小排序
        def parse_percent(p: str) -> int:
            return int(p.strip('%')) if isinstance(p, str) else 0

        items.sort(key=lambda x: parse_percent(x.get("评论占比", "0%")), reverse=True)

        # 只保留前 5 条
        result[dim] = items[:5]

    logger.info("AI分析完成")

    return result



# ==============================
# API接口
# ==============================
@app.post("/analyze")
def analyze_api(products: List[ProductComments]):

    request_id = datetime.now().strftime("%Y%m%d_%H%M%S_%f")

    logger.info(f"收到请求 request_id={request_id}")

    cached_results = {}

    # 读取历史缓存
    for file in OUTPUT_DIR.glob("analysis_result_*.json"):

        try:
            with open(file, "r", encoding="utf-8") as f:
                data = json.load(f)

                for p in data.get("products", []):
                    cached_results[p["product_id"]] = p["data"]

        except Exception as e:
            logger.warning(f"读取缓存失败 {file} {e}")

    results = []

    for product in products:

        logger.info(f"处理产品 {product.product_id}")

        # 如果缓存存在
        if product.product_id in cached_results:

            results.append({
                "product_id": product.product_id,
                "count": len(product.comments),
                "data": cached_results[product.product_id],
                "cached": True
            })

            continue

        # AI分析
        try:

            data = analyze_comments(product.comments)

            results.append({
                "product_id": product.product_id,
                "count": len(product.comments),
                "data": data,
                "cached": False
            })

        except Exception as e:

            logger.exception("分析失败")

            results.append({
                "product_id": product.product_id,
                "count": len(product.comments),
                "error": str(e)
            })

        sleep(3)

    final_result = {
        "success": True,
        "request_id": request_id,
        "products": results
    }

    # 保存文件
    output_file = OUTPUT_DIR / f"analysis_result_{request_id}.json"

    with open(output_file, "w", encoding="utf-8") as f:
        json.dump(final_result, f, ensure_ascii=False, indent=2)

    logger.info(f"结果保存 {output_file}")

    return final_result


# ==============================
# 启动
# ==============================
if __name__ == "__main__":

    logger.info("服务启动 8007")

    uvicorn.run(
        app,
        host="0.0.0.0",
        port=8007,
        workers=1
    )