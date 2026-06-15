# social_api_ai.py
import json
import re
import httpx
from pathlib import Path
from fastapi import FastAPI
from pydantic import BaseModel
import logging
from datetime import datetime

from env_config import DEEPSEEK_SOCIAL_API_KEY

# ==============================
# 配置目录
# ==============================
SCRIPT_DIR = Path(__file__).parent.absolute()
RESULTS_DIR = SCRIPT_DIR / "results"
RESULTS_DIR.mkdir(parents=True, exist_ok=True)

LOGS_DIR = SCRIPT_DIR / "logs"
LOGS_DIR.mkdir(parents=True, exist_ok=True)

log_file = LOGS_DIR / f"social_api_{datetime.now().strftime('%Y%m%d_%H%M%S')}.log"

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[logging.FileHandler(log_file, encoding="utf-8"), logging.StreamHandler()],
    force=True
)
logger = logging.getLogger(__name__)
logger.info(f"✅ 日志系统初始化完成，日志文件: {log_file}")

# ==============================
# FastAPI 初始化
# ==============================
app = FastAPI(title="社媒链接提取接口（AI版）")

# ==============================
# 请求体模型
# ==============================
class SocialRequest(BaseModel):
    data: dict  # ASIN -> 官网 URL

# ==============================
# 社媒字段
# ==============================
SOCIAL_KEYS = ["instagram", "facebook", "twitter", "youtube", "tiktok"]

# ==============================
# 链接校验
# ==============================
def validate_link(link, platform):
    if not link:
        return None

    link = link.strip()

    rules = {
        "instagram": "instagram.com",
        "facebook": "facebook.com",
        "twitter": ["twitter.com", "x.com"],
        "youtube": ["youtube.com", "youtu.be"],
        "tiktok": "tiktok.com",
    }

    valid = rules[platform]
    if isinstance(valid, list):
        if not any(v in link for v in valid):
            return None
    else:
        if valid not in link:
            return None

    # 过滤垃圾链接
    if any(x in link for x in ["share", "intent", "login", "status"]):
        return None

    return link


# ==============================
# AI 提取函数
# ==============================
def extract_social_links(url: str):
    result = {k: None for k in SOCIAL_KEYS}

    try:
        domain = re.sub(r"https?://(www\.)?", "", url).split("/")[0]

        prompt = f"""
你是一个品牌调研专家，请根据官网信息找到该品牌的官方社媒账号。

官网: {url}
品牌域名: {domain}

请返回 JSON：
{{
  "instagram": "...",
  "facebook": "...",
  "twitter": "...",
  "youtube": "...",
  "tiktok": "..."
}}

要求：
1. 必须是官方账号（不是粉丝页）
2. 优先返回认证账号
3. 没有找到填 null
4. 只返回 JSON
"""

        response = httpx.post(
            "https://api.deepseek.com/v1/chat/completions",
            headers={
                "Authorization": f"Bearer {DEEPSEEK_SOCIAL_API_KEY}",
                "Content-Type": "application/json",
            },
            json={
                "model": "deepseek-chat",
                "messages": [
                    {"role": "system", "content": "你是社媒搜索专家"},
                    {"role": "user", "content": prompt},
                ],
                "temperature": 0.2,
            },
            timeout=30
        )

        content = response.json()["choices"][0]["message"]["content"]

        # 提取 JSON
        match = re.search(r"\{.*\}", content, re.S)
        if match:
            ai_result = json.loads(match.group())

            for k in SOCIAL_KEYS:
                link = ai_result.get(k)
                result[k] = validate_link(link, k)

    except Exception as e:
        logger.warning(f"❌ DeepSeek 查询失败 {url}: {e}")

    return result


# ==============================
# 保存结果
# ==============================
def save_results(data: dict, filename="social_results.json"):
    path = RESULTS_DIR / filename
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    logger.info(f"✅ 社媒结果已保存: {path}")


# ==============================
# 接口
# ==============================
@app.post("/tool/extract-social-links")
def extract_social_links_endpoint(request: SocialRequest):
    results = {}

    for asin, url in request.data.items():
        logger.info(f"🔍 AI提取: {asin} -> {url}")
        results[asin] = extract_social_links(url)

    save_results(results)
    return results


# ==============================
# 启动
# ==============================
if __name__ == "__main__":
    import uvicorn

    host = "0.0.0.0"
    port = 8006

    logger.info(f"🚀 服务器启动: http://{host}:{port}")
    uvicorn.run(app, host=host, port=port, workers=1)