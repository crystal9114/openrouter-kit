"""OpenRouter 文本、生图与跑批的统一封装。

三个端点各管一摊，走错会 404：

    chat()            → /chat/completions
    generate_image()  → /images/generations
    submit_batch()    → /api/beta/batches   （五折，异步）

模型分三档，全部由环境变量决定，换模型不改代码：

    OPENROUTER_MODEL_IMAGE   生图
    OPENROUTER_MODEL_TEXT    日常文本（便宜档）
    OPENROUTER_MODEL_HEAVY   掌控类工作（贵档），chat(..., heavy=True) 走这个
"""

from .batch import (
    BatchItem,
    BatchRequest,
    BatchStatus,
    fetch_results,
    get_batch,
    submit_batch,
    wait_batch,
)
from .config import BATCH_BASE_URL, DEFAULT_BASE_URL, Config
from .core import ChatResult, ImageResult, chat, generate_image
from .errors import BatchNotFinished, OpenRouterConfigError, OpenRouterError

__all__ = [
    "BATCH_BASE_URL",
    "BatchItem",
    "BatchNotFinished",
    "BatchRequest",
    "BatchStatus",
    "ChatResult",
    "Config",
    "DEFAULT_BASE_URL",
    "ImageResult",
    "OpenRouterConfigError",
    "OpenRouterError",
    "chat",
    "fetch_results",
    "generate_image",
    "get_batch",
    "submit_batch",
    "wait_batch",
]
