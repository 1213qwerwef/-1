import os
from pathlib import Path

_ENV_PATH = Path(__file__).resolve().parent / ".env"


def _load_env_file(path: Path) -> None:
    if not path.exists():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        os.environ.setdefault(key.strip(), value.strip())


try:
    from dotenv import load_dotenv

    load_dotenv(_ENV_PATH)
except ImportError:
    _load_env_file(_ENV_PATH)

OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "")
OPENAI_BASE_URL = os.getenv("OPENAI_BASE_URL", "")

DEEPSEEK_SOCIAL_API_KEY = os.getenv("DEEPSEEK_SOCIAL_API_KEY", "")
DEEPSEEK_TRENDS_API_KEY = os.getenv("DEEPSEEK_TRENDS_API_KEY", "")
DEEPSEEK_API_BASE_URL = os.getenv("DEEPSEEK_API_BASE_URL", "https://api.deepseek.com")
