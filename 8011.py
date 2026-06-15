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
作为亚马逊广告数据分析专家。

任务说明：

1. 对每个 categoryname，已抓取前三产品的前三关键词（共9个）。
2. 每个关键词带有已抓取的 PPC 和 SPR 值。
3. 对这9个关键词进行去重，剩余 N 个不同关键词。
4. 计算平均值：
   - PPC平均 = 所有去重关键词的PPC之和 / N
   - SPR平均 = 所有去重关键词的SPR之和 / N
   - CPA = PPC平均 / 5%
5. CPA保留两位小数

=====================
输入 JSON 结构
=====================

输入为一个 JSON 数组，每个对象包含：

{
  "categoryname": "字符串",
  "top_keywords": [
    {"keyword": "字符串", "PPC": 数字, "SPR": 数字},
    {"keyword": "字符串", "PPC": 数字, "SPR": 数字},
    ...
  ]
}

示例输入：

[
  {
    "categoryname": "https://www.amazon.com/gp/bestsellers/electronics/227758/ref=pd_zg_hrsr_electronics",
    "top_keywords": [
      {"keyword": "关键词1", "PPC": 1.20, "SPR": 150},
      {"keyword": "关键词2", "PPC": 1.10, "SPR": 140},
      {"keyword": "关键词3", "PPC": 1.25, "SPR": 160},
      {"keyword": "关键词4", "PPC": 1.20, "SPR": 155},
      {"keyword": "关键词5", "PPC": 1.20, "SPR": 150},
      {"keyword": "关键词6", "PPC": 1.15, "SPR": 145},
      {"keyword": "关键词7", "PPC": 1.18, "SPR": 148},
      {"keyword": "关键词8", "PPC": 1.22, "SPR": 152},
      {"keyword": "关键词9", "PPC": 1.17, "SPR": 149}
    ]
  }
]

=====================
输出 JSON 结构
=====================

返回一个 JSON 数组，每个 categoryname 对应一个对象：

[
  {
    "categoryname": "字符串",
    "PPC": "数字",   # 平均PPC
    "CPA": "数字",   # 平均CPA
    "SPR": "数字"    # 平均SPR
  }
]

示例输出：

[
  {
    "categoryname": "https://www.amazon.com/gp/bestsellers/electronics/227758/ref=pd_zg_hrsr_electronics",
    "PPC": "1.18",
    "CPA": "23.60",
    "SPR": 150
  }
]

=====================
重要规则
=====================

1. 输出 JSON 仅包含上述结构。
2. 不要输出解释或额外字段。
3. 输出对象数量必须与输入 categoryname 数量一致。
4. PPC 和 CPA 保留两位小数，SPR取整数。
5. 平均值均基于去重后的关键词集合计算。
6. 同一 categoryname 下关键词重复，只计算一次。
7. CPA = PPC平均 / 5%
8. 输入字段 PPC 和 SPR 直接作为计算原始值。

现在请分析以下输入数据：
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
                    existing[item["categoryname"]] = item
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
    new_products = [p for p in input_products if p["categoryname"] not in existing_results]
    reused_results = [existing_results[p["categoryname"]] for p in input_products if p["categoryname"] in existing_results]

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
                    [{"categoryname": p["categoryname"], "required certificates": []} for p in batch]
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
    uvicorn.run(app, host="0.0.0.0", port=8011, workers=1)