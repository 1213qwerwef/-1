import asyncio
import json
from typing import List, Optional
from fastapi import FastAPI
from pydantic import BaseModel
from openai import OpenAI
import logging
import uvicorn
from datetime import datetime
from pathlib import Path

from env_config import OPENAI_API_KEY, OPENAI_BASE_URL

# ==============================
# 目录初始化
# ==============================
RESULTS_DIR = Path("results")
RESULTS_DIR.mkdir(exist_ok=True)

LOGS_DIR = Path("logs")
LOGS_DIR.mkdir(exist_ok=True)

CACHE_DIR = Path("cache")
CACHE_DIR.mkdir(exist_ok=True)

ASIN_CACHE_FILE = CACHE_DIR / "asin_cache.json"
BRAND_CACHE_FILE = CACHE_DIR / "brand_cache.json"
QUERIED_FILE = CACHE_DIR / "queried_brands.json"  # 新增唯一性文件

# ==============================
# 日志
# ==============================
log_filename = LOGS_DIR / f"brand_query_{datetime.now().strftime('%Y%m%d_%H%M%S')}.log"
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.FileHandler(log_filename, encoding="utf-8"),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)
logger.info(f"日志文件已创建: {log_filename}")

# ==============================
# OpenAI客户端
# ==============================
client = OpenAI(
    api_key=OPENAI_API_KEY,
    base_url=OPENAI_BASE_URL,
    timeout=60
)

# ==============================
# FastAPI
# ==============================
app = FastAPI(title="品牌官网查询接口")

# ==============================
# 请求模型
# ==============================
class BrandBatchRequest(BaseModel):
    data: List[List[str]]

# ==============================
# 缓存读取/保存工具
# ==============================
def load_cache(file_path):
    if file_path.exists():
        try:
            with open(file_path, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception as e:
            logger.warning(f"读取缓存失败 {file_path}: {e}")
            return {}
    return {}

def save_cache(data, file_path):
    with open(file_path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

# 初始化缓存
asin_cache = load_cache(ASIN_CACHE_FILE)
brand_cache = load_cache(BRAND_CACHE_FILE)
queried = load_cache(QUERIED_FILE)
if "ASIN" not in queried: queried["ASIN"] = {}
if "BRAND" not in queried: queried["BRAND"] = {}

# ==============================
# AI 查询
# ==============================
async def find_official_site(brand_name: str):
    prompt = f"""
Official website homepage of brand: {brand_name}
Return only the official homepage URL.
If none exists return nothing.
"""
    response = client.responses.create(
        model="o4-mini",
        input=prompt
    )
    text = response.output_text.strip()
    urls = [w for w in text.split() if w.startswith("http")]
    return urls[0] if urls else None

MAX_RETRIES = 3
RETRY_DELAY = 5

async def find_official_site_with_retry(brand_name: str):
    for attempt in range(1, MAX_RETRIES + 1):
        try:
            result = await find_official_site(brand_name)
            if result:
                logger.info(f"✅ AI查询成功: {brand_name} → {result}")
                return result
            else:
                logger.info(f"⚠️ AI返回空: {brand_name}")
                return None
        except Exception as e:
            logger.warning(f"⚠️ AI查询失败 {brand_name} 第{attempt}次: {e}")
            if attempt < MAX_RETRIES:
                await asyncio.sleep(RETRY_DELAY)
            else:
                return None

# ==============================
# 唯一性检查
# ==============================
async def check_unique(brand_name: str, asin: Optional[str]):
    brand_key = brand_name.strip().lower()
    if asin and asin in queried["ASIN"]:
        logger.info(f"⚡ ASIN唯一性命中 {asin}")
        return True
    if brand_key in queried["BRAND"]:
        logger.info(f"⚡ Brand唯一性命中 {brand_name}")
        return True
    return False

async def update_unique(brand_name: str, asin: Optional[str]):
    brand_key = brand_name.strip().lower()
    if asin:
        queried["ASIN"][asin] = True
    queried["BRAND"][brand_key] = True
    save_cache(queried, QUERIED_FILE)

# ==============================
# 保存单个品牌JSON
# ==============================
async def save_single_brand_result(brand_name, asin, result, index, total):
    data = {
        "brand_name": brand_name,
        "asin": asin,
        "official_site": result,
        "query_time": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "index": index,
        "total": total
    }
    key = asin if asin else brand_name
    safe_key = "".join(c for c in key if c.isalnum() or c in (' ', '-', '_')).strip().replace(" ", "_")
    filename = RESULTS_DIR / f"brand_{index:04d}_{safe_key}.json"
    def save():
        with open(filename, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
    await asyncio.to_thread(save)
    logger.info(f"📝 保存结果 {filename}")

# ==============================
# 批量查询接口
# ==============================
@app.post("/tool/find-official-site-batch")
async def find_official_sites_batch(request: BrandBatchRequest):
    total = len(request.data)
    results_dict = {}
    start_time = datetime.now()
    logger.info(f"🚀 开始查询 {total} 个品牌")

    for index, row in enumerate(request.data, 1):
        brand_name = row[0]
        asin = row[1] if len(row) > 1 else None
        key = asin if asin else brand_name

        logger.info(f"📌 {index}/{total} 处理 {brand_name}")

        # 先检查唯一性文件
        unique_hit = await check_unique(brand_name, asin)
        if unique_hit:
            # 从缓存直接复用
            result = None
            if asin and asin in asin_cache:
                result = asin_cache[asin]
            elif brand_name.strip().lower() in brand_cache:
                result = brand_cache[brand_name.strip().lower()]
        else:
            # 调用 AI
            result = await find_official_site_with_retry(brand_name)
            # 写入缓存
            if asin:
                asin_cache[asin] = result
                save_cache(asin_cache, ASIN_CACHE_FILE)
            brand_cache[brand_name.strip().lower()] = result
            save_cache(brand_cache, BRAND_CACHE_FILE)
            # 更新唯一性文件
            await update_unique(brand_name, asin)

        results_dict[key] = result
        await save_single_brand_result(brand_name, asin, result, index, total)
        logger.info(f"🔹 完成 {key} → {result}")

        if index < total:
            await asyncio.sleep(5)

    end_time = datetime.now()
    duration = (end_time - start_time).total_seconds()

    final_result = {
        "total": total,
        "start_time": start_time.strftime("%Y-%m-%d %H:%M:%S"),
        "end_time": end_time.strftime("%Y-%m-%d %H:%M:%S"),
        "duration_seconds": duration,
        "results": results_dict
    }

    filename = RESULTS_DIR / f"complete_results_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
    with open(filename, "w", encoding="utf-8") as f:
        json.dump(final_result, f, ensure_ascii=False, indent=2)

    logger.info(f"🎉 全部完成 共{total}个品牌")
    return final_result

# ==============================
# 启动服务
# ==============================
if __name__ == "__main__":
    uvicorn.run("main:app", host="0.0.0.0", port=8005)