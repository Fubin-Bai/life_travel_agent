"""入口统一加载本地配置；系统环境优先，不搜索其他目录或输出凭据。"""
from pathlib import Path
from dotenv import load_dotenv

PROJECT_ROOT = Path(__file__).resolve().parents[2]


def load_project_env() -> None:
    """只读取源码项目根目录.env；缺失可忽略，既有环境值包括空值都不覆盖。

    不做变量插值，避免文件内引用意外改变系统优先语义；不缓存加载结果。
    """
    load_dotenv(dotenv_path=PROJECT_ROOT / '.env', override=False, interpolate=False)
