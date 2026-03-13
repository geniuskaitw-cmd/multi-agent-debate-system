"""FastAPI 應用入口"""

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from api import router
from auth import auth_router
from config import get_settings
from database import init_db

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s:	%(message)s",
)
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    try:
        settings = get_settings()
        logger.info("環境設定驗證通過")
        logger.info("Agent A/B/C 模型: %s", settings.agent_a_model)
        logger.info("Agent D 模型: %s", settings.agent_d_model)
        await init_db()
        logger.info("資料庫初始化完成")
    except ValueError as e:
        logger.error("e啟動失敗: %s", e)
        raise
    yield


app = FastAPI(
    title="多智能體辯論臇決秖系統",
    description="透過四個 AI 智能體進行結構化辯論，產出最佳方案臇量化評分",
    version="1.0.0",
    lifespan=lifespan,
)

app.include_router(router)
app.include_router(auth_router)
app.mount("/static", StaticFiles(directory="static"), name="static")
