"""OpenRouter 客户端：文本与生图的统一入口。

两类模型走不同端点，这是 OpenRouter 的硬约束，不是风格问题：

  - 纯生图模型（gpt-image-*、flux.*、seedream-* 等）只能走 /images/generations
  - 多模态聊天模型（gpt-5.4-image-2 等）走 /chat/completions 并传 modalities

走错端点直接 404，而且两条路的 image token 计数方式不同，
同一张图实测差约 46 倍（Sunburst 走 images 端点 $0.0049，
gpt-5.4-image-2 走 chat 端点 $0.2247）。

配置全部来自环境变量，没有硬编码的 key 或模型名：

  OPENROUTER_API_KEY       必填
  OPENROUTER_BASE_URL      可选，默认 https://openrouter.ai/api/v1
  OPENROUTER_MODEL_IMAGE   生图默认模型
  OPENROUTER_MODEL_TEXT    文本默认模型
"""

from __future__ import annotations

import base64
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Final, Mapping, Sequence

import requests

DEFAULT_BASE_URL: Final = "https://openrouter.ai/api/v1"
DEFAULT_TIMEOUT: Final = 300
_DATA_URI_PREFIX: Final = "base64,"


class OpenRouterError(RuntimeError):
    """调用失败。失败永远抛异常，绝不返回跟「空结果」同形的值。"""


class OpenRouterConfigError(OpenRouterError):
    """配置缺失或非法，启动即失败，不拖到第一次调用。"""


@dataclass(frozen=True)
class Config:
    api_key: str
    base_url: str
    model_image: str
    model_text: str

    @staticmethod
    def from_env(env: Mapping[str, str] | None = None) -> "Config":
        src = os.environ if env is None else env

        api_key = (src.get("OPENROUTER_API_KEY") or "").strip()
        if not api_key:
            raise OpenRouterConfigError("缺少 OPENROUTER_API_KEY")
        if not api_key.startswith("sk-or-"):
            raise OpenRouterConfigError("OPENROUTER_API_KEY 格式不对，应以 sk-or- 开头")

        return Config(
            api_key=api_key,
            base_url=(src.get("OPENROUTER_BASE_URL") or DEFAULT_BASE_URL).rstrip("/"),
            model_image=(src.get("OPENROUTER_MODEL_IMAGE") or "").strip(),
            model_text=(src.get("OPENROUTER_MODEL_TEXT") or "").strip(),
        )


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


def _post(cfg: Config, path: str, payload: Mapping[str, Any], timeout: int) -> dict:
    url = f"{cfg.base_url}{path}"
    try:
        resp = requests.post(
            url,
            headers={
                "Authorization": f"Bearer {cfg.api_key}",
                "Content-Type": "application/json",
            },
            json=payload,
            timeout=timeout,
        )
    except requests.RequestException as exc:
        raise OpenRouterError(f"请求 {path} 失败：{exc}") from exc

    if resp.status_code != 200:
        # 把上游原文带出来，404 常常是模型走错端点，讯息里写得很清楚
        raise OpenRouterError(
            f"{path} 返回 HTTP {resp.status_code}：{resp.text[:500]}"
        )

    try:
        body = resp.json()
    except ValueError as exc:
        raise OpenRouterError(f"{path} 返回的不是 JSON：{resp.text[:200]}") from exc

    if "error" in body:
        raise OpenRouterError(f"{path} 返回错误：{body['error']}")
    return body


def _decode_image(payload: Mapping[str, Any]) -> bytes:
    """从 images 端点的 data[0] 里取出 PNG 字节。

    不同上游返回字段不一样：有的给 b64_json，有的给 data URI。
    两种都认，都不认就报错，绝不返回空 bytes 让调用方以为成功了。
    """
    raw = payload.get("b64_json")
    if not raw:
        url = (payload.get("image_url") or {}).get("url", "")
        if _DATA_URI_PREFIX in url:
            raw = url.split(_DATA_URI_PREFIX, 1)[1]

    if not raw:
        raise OpenRouterError(
            f"返回里找不到图片数据，可用字段：{sorted(payload.keys())}"
        )

    try:
        data = base64.b64decode(raw, validate=True)
    except (ValueError, TypeError) as exc:
        raise OpenRouterError(f"图片 base64 解码失败：{exc}") from exc

    if not data.startswith(b"\x89PNG"):
        raise OpenRouterError("解码结果不是 PNG，上游可能换了格式")
    return data


def generate_image(
    prompt: str,
    *,
    model: str | None = None,
    cfg: Config | None = None,
    timeout: int = DEFAULT_TIMEOUT,
) -> ImageResult:
    """生图。纯生图模型走 /images/generations，走 chat 端点会 404。"""
    if not prompt.strip():
        raise ValueError("prompt 不能为空")

    conf = cfg or Config.from_env()
    target = (model or conf.model_image).strip()
    if not target:
        raise OpenRouterConfigError("未指定生图模型，且 OPENROUTER_MODEL_IMAGE 为空")

    body = _post(conf, "/images/generations", {"model": target, "prompt": prompt}, timeout)

    items = body.get("data") or []
    if not items:
        raise OpenRouterError("images 端点返回 data 为空")

    usage = body.get("usage") or {}
    details = usage.get("completion_tokens_details") or {}
    return ImageResult(
        model=target,
        png=_decode_image(items[0]),
        cost_usd=float(usage.get("cost") or 0.0),
        image_tokens=int(details.get("image_tokens") or 0),
    )


def chat(
    messages: Sequence[Mapping[str, str]],
    *,
    model: str | None = None,
    cfg: Config | None = None,
    max_tokens: int | None = None,
    timeout: int = DEFAULT_TIMEOUT,
) -> ChatResult:
    """文本 / 代码。走 /chat/completions。"""
    if not messages:
        raise ValueError("messages 不能为空")

    conf = cfg or Config.from_env()
    target = (model or conf.model_text).strip()
    if not target:
        raise OpenRouterConfigError("未指定文本模型，且 OPENROUTER_MODEL_TEXT 为空")

    payload: dict[str, Any] = {"model": target, "messages": list(messages)}
    if max_tokens is not None:
        payload["max_tokens"] = max_tokens

    body = _post(conf, "/chat/completions", payload, timeout)

    choices = body.get("choices") or []
    if not choices:
        raise OpenRouterError("chat 端点返回 choices 为空")

    usage = body.get("usage") or {}
    return ChatResult(
        model=body.get("model") or target,
        text=(choices[0].get("message") or {}).get("content") or "",
        cost_usd=float(usage.get("cost") or 0.0),
        total_tokens=int(usage.get("total_tokens") or 0),
    )


if __name__ == "__main__":
    import sys

    # Windows 控制台默认 GBK，不改的话中文输出全是乱码
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")

    cfg = Config.from_env()
    print(f"生图模型={cfg.model_image}  文本模型={cfg.model_text}")

    answer = chat([{"role": "user", "content": "用一句话说明你是谁"}], cfg=cfg, max_tokens=100)
    print(f"\n[文本] {answer.model}  ${answer.cost_usd:.6f}  {answer.total_tokens} tokens")
    print(answer.text)

    if "--with-image" in sys.argv:
        img = generate_image("一块拉丝铝板特写，工业产品摄影，柔和侧光，纯白背景", cfg=cfg)
        saved = img.save("out/sample.png")
        print(f"\n[生图] {img.model}  ${img.cost_usd:.6f}  {img.image_tokens} image tokens")
        print(f"已保存 {saved}  {len(img.png)} bytes")
