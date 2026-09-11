"""配置。全部来自环境变量，代码里没有任何硬编码的 key 或模型名。

    OPENROUTER_API_KEY       必填
    OPENROUTER_BASE_URL      可选，默认 https://openrouter.ai/api/v1
    OPENROUTER_MODEL_IMAGE   生图模型
    OPENROUTER_MODEL_TEXT    日常文本模型（便宜那档）
    OPENROUTER_MODEL_HEAVY   掌控类工作用的模型（贵那档）
    OPENROUTER_REASONING_EFFORT  日常档的思考强度，默认 low
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Final, Mapping

from .errors import OpenRouterConfigError

DEFAULT_BASE_URL: Final = "https://openrouter.ai/api/v1"
BATCH_BASE_URL: Final = "https://openrouter.ai/api/beta"
KEY_PREFIX: Final = "sk-or-"

# Gemini 这类模型的思考关不掉（enabled=false 与 max_tokens=0 都返回 400
# "Reasoning is mandatory"），但能压到最低档。实测 effort=low 让
# reasoning_tokens 归零，同一个问题成本从 $0.001116 降到 $0.000115，
# 便宜约 9.7 倍，答案质量没有差别。
#
# 注意别用 reasoning.exclude=true：那只是不把思考过程返回给你，
# token 照算照收钱，看着省了其实没省。
DEFAULT_REASONING_EFFORT: Final = "low"
VALID_EFFORTS: Final = frozenset({"low", "medium", "high"})


@dataclass(frozen=True)
class Config:
    api_key: str
    base_url: str
    batch_url: str
    model_image: str
    model_text: str
    model_heavy: str
    reasoning_effort: str

    @staticmethod
    def from_env(env: Mapping[str, str] | None = None) -> "Config":
        src = os.environ if env is None else env

        api_key = (src.get("OPENROUTER_API_KEY") or "").strip()
        if not api_key:
            raise OpenRouterConfigError("缺少 OPENROUTER_API_KEY")
        if not api_key.startswith(KEY_PREFIX):
            raise OpenRouterConfigError(
                f"OPENROUTER_API_KEY 格式不对，应以 {KEY_PREFIX} 开头"
            )

        effort = (
            src.get("OPENROUTER_REASONING_EFFORT") or DEFAULT_REASONING_EFFORT
        ).strip().lower()
        if effort not in VALID_EFFORTS:
            raise OpenRouterConfigError(
                f"OPENROUTER_REASONING_EFFORT={effort!r} 非法，可选 {sorted(VALID_EFFORTS)}。"
                "思考无法完全关闭，上游对 enabled=false 会返回 400。"
            )

        base = (src.get("OPENROUTER_BASE_URL") or DEFAULT_BASE_URL).rstrip("/")
        return Config(
            api_key=api_key,
            base_url=base,
            batch_url=BATCH_BASE_URL,
            model_image=(src.get("OPENROUTER_MODEL_IMAGE") or "").strip(),
            model_text=(src.get("OPENROUTER_MODEL_TEXT") or "").strip(),
            model_heavy=(src.get("OPENROUTER_MODEL_HEAVY") or "").strip(),
            reasoning_effort=effort,
        )

    def require_model(self, kind: str) -> str:
        """取某一档的模型名，没配就报错，不静默回退到别的档。

        回退是危险的：悄悄把便宜模型换成贵的会烧钱，
        反过来把贵的换成便宜的会让质量无声下降。
        """
        table = {
            "image": ("model_image", "OPENROUTER_MODEL_IMAGE"),
            "text": ("model_text", "OPENROUTER_MODEL_TEXT"),
            "heavy": ("model_heavy", "OPENROUTER_MODEL_HEAVY"),
        }
        if kind not in table:
            raise ValueError(f"未知模型档位 {kind!r}，可选 {sorted(table)}")

        attr, env_name = table[kind]
        value = getattr(self, attr)
        if not value:
            raise OpenRouterConfigError(f"未配置 {env_name}")
        return value
