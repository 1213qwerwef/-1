import json
import logging
import time
from pathlib import Path
from typing import List
from time import sleep
from datetime import datetime

from fastapi import FastAPI, UploadFile, File, Request
from openai import OpenAI

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
client = OpenAI(api_key=OPENAI_API_KEY, base_url=OPENAI_BASE_URL, timeout=120)

# =============================
# FastAPI 初始化
# =============================
app = FastAPI()

# =============================
# AI Prompt
# =============================
PROMPT = """
Please become a product access certification analyst expert group. Please strictly follow the following rules:
1. Input as a JSON array, each element containing: - asin: Amazon product ID - category_name: product_title
2. Process:
a. Extract precise product name keywords from product_title for judgment.  
b. Based on the extracted product name, list all certification documents that may be required to sell this product on Amazon US.
c. Based solely on the product name, do not refer to any fixed certification list or requirements outside of the country.
d. Ensure that each product has **at least 5 certificates in total**. The AI can output more than 5 if relevant, but there must **always** be at least 5 certificates. If the mandatory list is too short, supplement with optional certificates to reach the minimum.
3. The output JSON strictly follows the following structure, with each input corresponding to an output: {"asin": "string", "required certificates": ["string"]}
4. Do not output any analysis process, explanation, or redundant fields.
Now start analyzing the following input data:
"""

# =============================
# 结果目录
# =============================
RESULTS_DIR = Path("results")
RESULTS_DIR.mkdir(exist_ok=True)

# =============================
# 核心分析函数（带重试）
# =============================
def analyze_products(input_data, retries=3):
    for attempt in range(retries):
        try:
            response = client.chat.completions.create(
                model="gpt-5-mini",
                messages=[
                    {"role": "system", "content": PROMPT},
                    {"role": "user", "content": json.dumps(input_data, ensure_ascii=False)}
                ],
                temperature=1
            )
            content = response.choices[0].message.content
            return content
        except Exception as e:
            logger.error(f"Attempt {attempt+1} failed: {e}")
            time.sleep(2)
    logger.error("All retries failed.")
    return json.dumps([{"error": "All retries failed"}], ensure_ascii=False)

# =============================
# 工具函数：加载历史所有结果
# =============================
def load_existing_results():
    existing = {}
    for file in RESULTS_DIR.glob("analysis_result_*.json"):
        try:
            with open(file, "r", encoding="utf-8") as f:
                data = json.load(f)
                for item in data:
                    existing[item["asin"]] = item
        except:
            continue
    return existing

def save_results(results):
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    output_file = RESULTS_DIR / f"analysis_result_{timestamp}.json"
    with open(output_file, "w", encoding="utf-8") as f:
        json.dump(results, f, ensure_ascii=False, indent=2)
    logger.info(f"Analysis results saved to {output_file}")

# =============================
# FastAPI 接口（支持顶层数组 JSON）
# =============================
@app.post("/analyze")
async def analyze(request: Request):
    # 读取原始 JSON
    try:
        input_products = await request.json()
    except Exception as e:
        return {"error": f"Failed to parse JSON: {e}"}

    # 判断数据类型
    if isinstance(input_products, dict) and "products" in input_products:
        input_products = input_products["products"]
    elif not isinstance(input_products, list):
        return {"error": "No products provided"}

    if len(input_products) == 0:
        return {"error": "No products provided"}

    logger.info(f"Total products received: {len(input_products)}")

    # 加载历史结果
    existing_results = load_existing_results()

    # 分离新产品和复用产品
    new_products = [p for p in input_products if p["asin"] not in existing_results]
    reused_results = [existing_results[p["asin"]] for p in input_products if p["asin"] in existing_results]

    logger.info(f"Reusing {len(reused_results)} results, {len(new_products)} products need AI analysis")

    # AI分析（分批处理）
    ai_results = []

    if new_products:

        batch_size = 10

        for i in range(0, len(new_products), batch_size):

            batch = new_products[i:i + batch_size]

            logger.info(f"Analyzing batch {i // batch_size + 1}, size={len(batch)}")

            content = analyze_products(batch)

            try:
                result = json.loads(content)
                ai_results.extend(result)
            except Exception as e:
                logger.error(f"Batch parse error: {e}")
                ai_results.extend(
                    [{"asin": p["asin"], "required certificates": []} for p in batch]
                )

    # 合并结果并保存
    final_results = reused_results + ai_results
    save_results(final_results)

    sleep(3)
    return final_results

# =============================
# 本地启动
# =============================
if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8008, workers=1)