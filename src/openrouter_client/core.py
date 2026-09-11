"""实时调用：文本与生图。

两类模型走两个端点，这是 OpenRouter 的硬约束：

    纯生图模型      → /images/generations
    聊天类模型      → /chat/completions

走错直接 404，而且两条路的 image token 计数方式不同，
同一张图实测差约 46 倍。本模块把差异封住，不会走错。

跑批（五折）在 batch.py，那是第三个端点。
"""

from __future__ import annotations

import base64
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping, Sequence

from . import http
from .config import Config
from .errors import OpenRouterError

_DATA_URI_MARK = "base64,"
_PNG_MAGIC = b"\x89PNG"


@dataclass(frozen=True)
class ImageResult:
    model: str
    png: bytes
    cost_usd: float
    image_tokens: int

    def save(self, path: str | Path) -> Path:
        target = Path(path)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(self.png)
        return target


@dataclass(frozen=True)
class ChatResult:
    model: str
    text: str
    cost_usd: float
    total_tokens: int
    reasoning_tokens: int = 0
    finish_reason: str = ""


def _decode_png(item: Mapping[str, Any]) -> bytes:
    """取出 PNG 字节。不同上游返回字段不一样，b64_json 和 data URI 都认。"""
    raw = item.get("b64_json")
    if not raw:
        url = (item.get("image_url") or {}).get("url", "")
        if _DATA_URI_MARK in url:
            raw = url.split(_DATA_URI_MARK, 1)[1]

    if not raw:
        raise OpenRouterError(f"返回里没有图片数据，实际字段：{sorted(item.keys())}")

    try:
        data = base64.b64decode(raw, validate=True)
    except (ValueError, TypeError) as exc:
        raise OpenRouterError(f"图片 base64 解码失败：{exc}") from exc

    if not data.startswith(_PNG_MAGIC):
        raise OpenRouterError("解码结果不是 PNG，上游可能换了格式")
    return data


def generate_image(
    prompt: str,
    *,
    model: str | None = None,
    cfg: Config | None = None,
    timeout: int = http.DEFAULT_TIMEOUT,
) -> ImageResult:
    """生图。固定走 /images/generations。"""
    if not prompt.strip():
        raise ValueError("prompt 不能为空")

    conf = cfg or Config.from_env()
    target = (model or conf.require_model("image")).strip()

    body = http.post(
        conf,
        f"{conf.base_url}/images/generations",
        {"model": target, "prompt": prompt},
        timeout=timeout,
    )

    items = body.get("data") or []
    if not items:
        raise OpenRouterError("images 端点返回 data 为空")

    usage = body.get("usage") or {}
    details = usage.get("completion_tokens_details") or {}
    return ImageResult(
        model=target,
        png=_decode_png(items[0]),
        cost_usd=float(usage.get("cost") or 0.0),
        image_tokens=int(details.get("image_tokens") or 0),
    )


def chat(
    messages: Sequence[Mapping[str, str]],
    *,
    heavy: bool = False,
    model: str | None = None,
    cfg: Config | None = None,
    max_tokens: int | None = None,
    reasoning_effort: str | None = None,
    timeout: int = http.DEFAULT_TIMEOUT,
) -> ChatResult:
    """文本。固定走 /chat/completions。

    heavy=False 用便宜那档（OPENROUTER_MODEL_TEXT），并压低思考强度
    heavy=True  用掌控类那档（OPENROUTER_MODEL_HEAVY），思考不设限

    reasoning_effort 显式传入时优先；日常档不传则用配置里的值（默认 low）。
    思考无法关闭，上游对 enabled=false 会返回 400。
    """
    if not messages:
        raise ValueError("messages 不能为空")

    conf = cfg or Config.from_env()
    target = (model or conf.require_model("heavy" if heavy else "text")).strip()

    if target.endswith(":batch"):
        raise ValueError(
            f"{target} 是跑批模型，只能走 /api/beta/batches，请改用 submit_batch()"
        )

    payload: dict[str, Any] = {"model": target, "messages": list(messages)}
    if max_tokens is not None:
        payload["max_tokens"] = max_tokens

    # 掌控类工作要的就是深度推理，不去压它；日常档压到最低档省钱
    effort = reasoning_effort or (None if heavy else conf.reasoning_effort)
    if effort:
        payload["reasoning"] = {"effort": effort}

    body = http.post(
        conf, f"{conf.base_url}/chat/completions", payload, timeout=timeout
    )

    choices = body.get("choices") or []
    if not choices:
        raise OpenRouterError("chat 端点返回 choices 为空")

    choice = choices[0]
    usage = body.get("usage") or {}
    details = usage.get("completion_tokens_details") or {}
    reasoning_tokens = int(details.get("reasoning_tokens") or 0)
    finish = str(choice.get("finish_reason") or "")
    text = (choice.get("message") or {}).get("content") or ""

    # 拿到空正文却照样扣钱，是这类模型最容易踩的坑：
    # 思考把 max_tokens 预算吃光，正文一个字没剩。
    # 这种情况必须抛异常，不能返回空字符串让调用方以为「模型没话说」。
    if not text.strip():
        raise OpenRouterError(
            f"{target} 返回空正文（finish_reason={finish or '未知'}，"
            f"思考用掉 {reasoning_tokens} tokens，本次仍计费 "
            f"${float(usage.get('cost') or 0.0):.6f}）。"
            + (
                "思考占满了额度，把 max_tokens 调大，或把 reasoning_effort 降到 low。"
                if finish == "length"
                else "上游未给出正文，稍后重试或换模型。"
            )
        )

    return ChatResult(
        model=body.get("model") or target,
        text=text,
        cost_usd=float(usage.get("cost") or 0.0),
        total_tokens=int(usage.get("total_tokens") or 0),
        reasoning_tokens=reasoning_tokens,
        finish_reason=finish,
    )
