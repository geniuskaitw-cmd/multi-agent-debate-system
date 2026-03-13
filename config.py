"""環境設定模組

從 .env 檔案與環境變數載入系統設定，並在啟動時驗證必要設定是否存在。
"""

from pydantic_settings import BaseSettings, SettingsConfigDict
from pydantic import ValidationError


class Settings(BaseSettings):
    """系統設定，從環境變數載入"""

    # LLM API 金鑰（必填）
    google_api_key: str

    # 各智能體使用的模型名稱
    agent_a_model: str = "gemini-3-flash-preview"
    agent_b_model: str = "gemini-3-flash-preview"
    agent_c_model: str = "gemini-3-flash-preview"
    agent_d_model: str = "gemini-3.1-pro-preview"

    # LLM 呼叫設定
    llm_timeout: int = 120
    llm_max_retries: int = 3

    # SQLite 資料庫路徑
    database_path: str = "/app/data/debates.db"

    # JWT 認證設定
    jwt_secret: str
    jwt_expire_hours: int = 24

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8")


def get_settings() -> Settings:
    """載入並驗證設定，缺少必要設定時拋出明確錯誤。

    Returns:
        Settings: 已驗證的系統設定實例

    Raises:
        ValueError: 缺少必要的環境變數設定
    """
    try:
        return Settings()
    except ValidationError as e:
        missing_fields = []
        for error in e.errors():
            field_name = ".".join(str(loc) for loc in error["loc"])
            missing_fields.append(field_name.upper())
        raise ValueError(
            f"缺少必要的環境變數設定: {', '.join(missing_fields)}。"
            f"請在 .env 檔案或環境變數中設定這些值。"
        ) from e
