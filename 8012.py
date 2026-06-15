import json
import logging
import time
from pathlib import Path
from datetime import datetime
from time import sleep

from fastapi import FastAPI, Request
from openai import OpenAI

from env_config import DEEPSEEK_TRENDS_API_KEY, DEEPSEEK_API_BASE_URL

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
# DeepSeek 客户端
# =============================
client = OpenAI(
    api_key=DEEPSEEK_TRENDS_API_KEY,
    base_url=DEEPSEEK_API_BASE_URL,
    timeout=180
)

# =============================
# FastAPI 初始化
# =============================
app = FastAPI()

# =============================
# Prompt（简化稳定版）
# =============================
PROMPT = """
你是全球电商数据分析专家，擅长分析 Google Trends 搜索趋势数据。

⚠️⚠️⚠️【最高优先级强约束规则 - 必须严格遵守】

=============================
一、关键词逐条分析执行协议（必须100%执行）
=============================

1. 对于每一个 category_url：
   - 必须对输入中的每一个关键词 **逐个独立分析**
   - 严禁将多个关键词合并分析
   - 严禁遗漏任何关键词

2. 输出必须严格为 3 行：
   - 第1行 → 对应第1个关键词
   - 第2行 → 对应第2个关键词（若不存在则输出占位）
   - 第3行 → 对应第3个关键词（若不存在则输出占位）

3. 每一行必须满足：
   - 必须以“关键词原文 + ：”开头
   - 必须是完整分析句
   - 不允许合并多个关键词

4. 严格禁止以下行为：
   - ❌ 合并多个关键词做总结
   - ❌ 只输出1条或2条
   - ❌ 改写、翻译、拆分或重组关键词
   - ❌ 打乱顺序

5. 如果违反以上规则，输出视为无效

=============================
二、输入 JSON 格式
=============================

{
  "category_url": {
    "keyword1": [
      {"date": "YYYY/MM/DD", "value": 数值}
    ],
    "keyword2": [
      {"date": "YYYY/MM/DD", "value": 数值}
    ],
    "keyword3": [
      {"date": "YYYY/MM/DD", "value": 数值}
    ]
  }
}

说明：
1. JSON 的 key 是 category_url（产品类目页面 URL）。
2. 每个 URL 的 value 是一个字典，包含 **1~3 个关键词**。
3. 每个关键词可以是任意字符串（英文、中文等）。

=============================
三、分析任务（逐关键词执行）
=============================

对于每一个关键词，分别独立分析：

1. 【起势时间】
   - 判断首次出现明显上升趋势的时间（年+月）

2. 【2025年比2024年增长率】
   - 分别计算2024年全年平均值 与 2025年全年平均值
   - 增长率 = ((2025 - 2024) / 2024) × 100%
   - 若2024为0，则增长率为0%

3. 【旺季月份】
   - 搜索热度最高的月份（取平均值最高的月份）

4. 【淡季月份】
   - 搜索热度最低的月份（取平均值最低的月份）

⚠️ 每个关键词必须完整输出以上四项分析

=============================
四、缺失关键词处理规则（必须执行）
=============================

如果关键词不存在：

- 第2个关键词缺失：
  输出：
  "关键词2：无足够数据判断起势，2025年比2024年增长率为0%，旺季为无，淡季为无"

- 第3个关键词缺失：
  输出：
  "关键词3：无足够数据判断起势，2025年比2024年增长率为0%，旺季为无，淡季为无"

=============================
五、关键词一致性自检规则（必须执行）
=============================

在生成最终输出 JSON 之前，必须执行以下自检步骤：

【步骤1：提取输入关键词】
- 按顺序记录输入关键词为：
  - 关键词1 = 第1个关键词
  - 关键词2 = 第2个关键词（如果存在）
  - 关键词3 = 第3个关键词（如果存在）

【步骤2：逐行校验输出】
- 第1行必须以“关键词1 + ：”开头
- 第2行必须以“关键词2 + ：”或占位文本开头
- 第3行必须以“关键词3 + ：”或占位文本开头

【步骤3：严格一致性要求】
必须逐字符完全一致，包括：
- 大小写完全一致
- 空格完全一致
- 符号完全一致
- 不允许翻译或改写

【步骤4：错误判定】
以下任一情况视为错误：
- ❌ 关键词被改写（如 cordless screwdriver → cordless screw driver）
- ❌ 关键词被翻译
- ❌ 关键词大小写变化
- ❌ 关键词缺失
- ❌ 输出关键词不在输入中

【步骤5：自动修正机制】
如果发现不一致：
- 必须使用输入中的原始关键词强制替换输出行开头
- 重新生成该行分析内容
- 直到完全匹配为止

【步骤6：最终确认】
输出前必须满足：
- 每一行关键词与输入完全一致
- 输出行数 = 3
- 顺序完全正确

否则禁止输出

=============================
六、输出规则（严格格式）
=============================

1. 只允许输出 JSON，不允许任何解释内容
2. JSON 结构如下：

{
  "category_url": [
    "关键词1分析结果",
    "关键词2分析结果或占位",
    "关键词3分析结果或占位"
  ]
}

3. 每个 URL 的 value：
   - 必须是长度=3的数组
   - 顺序必须严格对应输入关键词顺序

4. 输出语言要求：
   - 所有分析内容必须为中文
   - ⚠️关键词必须严格使用输入原文（逐字符完全一致），禁止任何形式修改

=============================
七、输出示例（必须严格参考格式）
=============================

{
  "https://example.com/category/screwdriversy": [
    "cordless screwdriver：2024年2月开始有明显起势，2025年比2024年增长率为121%，旺季为2月，淡季为1月",
    "electric screwdriver：2023年11月开始有明显起势，2025年比2024年增长率为85%，旺季为11月，淡季为2月",
    "关键词3：无足够数据判断起势，2025年比2024年增长率为0%，旺季为无，淡季为无"
  ]
}
"""

# =============================
# 结果目录
# =============================
RESULTS_DIR = Path("results")
RESULTS_DIR.mkdir(exist_ok=True)

# =============================
# JSON清洗
# =============================
def clean_json(text):
    text = text.strip()
    if text.startswith("```"):
        text = text.strip("```").strip()
        if text.startswith("json"):
            text = text[4:].strip()
    return text

# =============================
# 结果校验
# =============================
def validate_result(input_data, output_data):
    try:
        for url, kw_dict in input_data.items():
            keywords = list(kw_dict.keys())

            if url not in output_data:
                return False

            lines = output_data[url]

            if len(lines) != 3:
                return False

            for i, kw in enumerate(keywords):
                if not lines[i].startswith(kw + "："):
                    return False

        return True
    except:
        return False

# =============================
# AI分析函数
# =============================
def analyze_trends(data, retries=3):
    for attempt in range(retries):
        try:
            response = client.chat.completions.create(
                model="deepseek-chat",
                messages=[
                    {"role": "system", "content": PROMPT},
                    {"role": "user", "content": json.dumps(data, ensure_ascii=False)}
                ],
                temperature=0.3
            )

            result_text = response.choices[0].message.content
            result_text = clean_json(result_text)

            result_json = json.loads(result_text)

            if not validate_result(data, result_json):
                raise ValueError("结果校验失败")

            return result_json

        except Exception as e:
            logger.error(f"失败 第{attempt+1}次: {e}")
            time.sleep(5)

    return {"error": "AI分析失败"}

# =============================
# 加载历史结果
# =============================
def load_existing_results():
    existing = {}
    for file in RESULTS_DIR.glob("trend_result_*.json"):
        try:
            with open(file, "r", encoding="utf-8") as f:
                data = json.load(f)
                existing.update(data)
        except Exception as e:
            logger.warning(f"加载失败: {e}")
    return existing

# =============================
# 保存结果
# =============================
def save_results(results):
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    file = RESULTS_DIR / f"trend_result_{timestamp}.json"

    with open(file, "w", encoding="utf-8") as f:
        json.dump(results, f, ensure_ascii=False, indent=2)

    logger.info(f"已保存: {file}")

# =============================
# API接口
# =============================
@app.post("/analyze")
async def analyze(request: Request):
    try:
        input_data = await request.json()
    except Exception as e:
        return {"error": f"JSON解析失败: {e}"}

    if not isinstance(input_data, dict):
        return {"error": "输入必须为JSON对象"}

    logger.info(f"收到: {len(input_data)} 个URL")

    existing = load_existing_results()

    new_data = {k: v for k, v in input_data.items() if k not in existing}
    reused = {k: existing[k] for k in input_data if k in existing}

    logger.info(f"复用 {len(reused)} | 新分析 {len(new_data)}")

    ai_result = {}
    if new_data:
        ai_result = analyze_trends(new_data)

    final = {**reused, **ai_result}

    save_results(final)

    sleep(3)

    return final

# =============================
# 启动
# =============================
if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8012, workers=1)