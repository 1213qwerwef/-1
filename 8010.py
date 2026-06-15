import json
import logging
import time
from pathlib import Path
from typing import Dict, List

from fastapi import FastAPI, HTTPException, Body
from openai import OpenAI
import uvicorn

from env_config import OPENAI_API_KEY, OPENAI_BASE_URL

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
    timeout=120
)

# =============================
# FastAPI 初始化
# =============================
app = FastAPI()

# =============================
# Prompt
# =============================
PROMPT = """
你是一名产品属性分析专家。

任务：
你将收到一个类目URL，以及一组产品数据。每个产品包含一个标题和多条描述信息。

要求：
- 聚合该类目下所有产品的标题和描述信息。
- 将整个类目总结为三个固定维度：
  1. 物理结构：包括尺寸、重量、容量、材质、颜色、形状、外观等属性。
  2. 功能属性：包括产品功能、模式、设置、特性等，根据产品内容分析相关功能属性。
  3. 使用场景：例如家庭、户外、汽车、办公室等使用环境。
- 维度必须严格保持为以上三个。
- 每个维度中的具体属性可以根据产品内容由AI灵活增加或减少。
- 总结应简洁、清晰，并具有概括性。
- 所有总结内容必须使用中文。

仅返回一个 JSON，严格按照以下格式：

{
  "category_url": "输入的category_url",
  "summary": {
    "物理结构": "物理结构属性的简洁汇总",
    "功能属性": "功能属性的简洁汇总",
    "使用场景": "使用场景的简洁汇总"
  }
}

不要包含任何额外文本、解释或说明，只返回 JSON。
"""

# =============================
# 结果目录
# =============================
RESULTS_DIR = Path("results")
RESULTS_DIR.mkdir(exist_ok=True)

# =============================
# 类目聚合分析
# =============================
def analyze_category(products: Dict[str, List[List[str]]], retries=3):

    all_text = []

    # 遍历每个产品标题
    for title, descriptions in products.items():
        all_text.append(f"Product Title: {title}")
        all_text.extend(descriptions)

    payload = {
        "products_count": len(products),
        "content": all_text
    }

    for attempt in range(retries):
        try:
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

            time.sleep(3)
            return parsed

        except Exception as e:
            logger.error(f"Analysis attempt {attempt+1} failed: {e}")
            time.sleep(3)

    # 重试失败返回空
    return {
        "物理结构": "",
        "功能属性": "",
        "使用场景": ""
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

    logger.info(f"Received category: {category_url}")
    logger.info(f"Product count: {len(products)}")

    # 执行分析
    summary = analyze_category(products)

    result_data = {
        "category_url": category_url,
        "summary": summary
    }

    # 生成动态文件名
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
    uvicorn.run(app, host="0.0.0.0", port=8010, workers=1)