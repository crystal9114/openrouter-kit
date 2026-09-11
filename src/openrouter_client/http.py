"""HTTP 层。所有请求走这里，统一错误处理。"""

from __future__ import annotations

from typing import Any, Final, Mapping

import requests

from .config import Config
from .errors import OpenRouterError

DEFAULT_TIMEOUT: Final = 300


def _headers(cfg: Config) -> dict[str, str]:
    return {
        "Authorization": f"Bearer {cfg.api_key}",
        "Content-Type": "application/json",
    }


def _parse(resp: requests.Response, where: str) -> dict:
    if resp.status_code >= 400:
        # 把上游原文带出来。404 常常是模型走错端点，讯息里写得很清楚：
        # 纯生图模型要走 /images/generations，:batch 模型要走 /api/beta/batches
        raise OpenRouterError(f"{where} 返回 HTTP {resp.status_code}：{resp.text[:500]}")

    try:
        body = resp.json()
    except ValueError as exc:
        raise OpenRouterError(f"{where} 返回的不是 JSON：{resp.text[:200]}") from exc

    if isinstance(body, dict) and body.get("error"):
        raise OpenRouterError(f"{where} 返回错误：{body['error']}")
    return body


def post(
    cfg: Config,
    url: str,
    payload: Mapping[str, Any],
    *,
    timeout: int = DEFAULT_TIMEOUT,
) -> dict:
    try:
        resp = requests.post(url, headers=_headers(cfg), json=payload, timeout=timeout)
    except requests.RequestException as exc:
        raise OpenRouterError(f"POST {url} 失败：{exc}") from exc
    return _parse(resp, url)


def get(cfg: Config, url: str, *, timeout: int = DEFAULT_TIMEOUT) -> dict:
    try:
        resp = requests.get(url, headers=_headers(cfg), timeout=timeout)
    except requests.RequestException as exc:
        raise OpenRouterError(f"GET {url} 失败：{exc}") from exc
    return _parse(resp, url)
