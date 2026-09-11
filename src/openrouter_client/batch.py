"""跑批：五折，但不是实时。

这是第三个端点，跟实时调用完全分开：

    POST /api/beta/batches        提交
    GET  /api/beta/batches/{id}   查状态，完成后结果就在同一个对象里

价格是标准价的一半，代价是异步：请求进队列，承诺 24 小时内完成，
实际多久看队列。所以跑批适合半夜出稿、批量改写这类不等结果的活，
聊天和写代码用不了。

带 :batch 后缀的模型只能走这里，丢进 /chat/completions 会 404。
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Any, Iterable, Mapping, Sequence

from . import http
from .config import Config
from .errors import BatchNotFinished, OpenRouterError

BATCH_SUFFIX = ":batch"
TERMINAL_OK = "completed"
TERMINAL_BAD = frozenset({"failed", "expired", "cancelled"})


@dataclass(frozen=True)
class BatchRequest:
    """批次里的一条。custom_id 用来把结果对回原始任务。"""

    custom_id: str
    messages: tuple[Mapping[str, str], ...]
    max_tokens: int | None = None

    def to_payload(self, reasoning_effort: str | None = None) -> dict[str, Any]:
        body: dict[str, Any] = {"messages": list(self.messages)}
        if self.max_tokens is not None:
            body["max_tokens"] = self.max_tokens
        if reasoning_effort:
            body["reasoning"] = {"effort": reasoning_effort}
        return {"custom_id": self.custom_id, "body": body}


@dataclass(frozen=True)
class BatchStatus:
    id: str
    status: str
    model: str
    total: int
    completed: int
    failed: int
    cost_usd: float

    @property
    def is_done(self) -> bool:
        return self.status == TERMINAL_OK or self.status in TERMINAL_BAD

    @property
    def is_success(self) -> bool:
        return self.status == TERMINAL_OK


@dataclass(frozen=True)
class BatchItem:
    """一条结果。error 非空表示这条失败了，text 不可信。"""

    custom_id: str
    text: str
    error: str | None = None

    @property
    def ok(self) -> bool:
        return self.error is None


def _as_status(body: Mapping[str, Any]) -> BatchStatus:
    counts = body.get("request_counts") or {}
    usage = body.get("usage") or {}
    return BatchStatus(
        id=str(body.get("id") or ""),
        status=str(body.get("status") or "unknown"),
        model=str(body.get("model") or ""),
        total=int(counts.get("total") or 0),
        completed=int(counts.get("completed") or 0),
        failed=int(counts.get("failed") or 0),
        cost_usd=float(usage.get("cost") or 0.0) if isinstance(usage, Mapping) else 0.0,
    )


def _with_batch_suffix(model: str) -> str:
    return model if model.endswith(BATCH_SUFFIX) else model + BATCH_SUFFIX


def submit_batch(
    requests: Sequence[BatchRequest],
    *,
    heavy: bool = False,
    model: str | None = None,
    cfg: Config | None = None,
    reasoning_effort: str | None = None,
    endpoint: str = "/v1/chat/completions",
) -> BatchStatus:
    """提交批次。模型名会自动补 :batch 后缀。

    思考强度跟实时调用一个规矩：日常档压到最低，掌控档不设限。
    批次里踩这个坑更贵，因为要等几分钟才发现整批都是空正文。
    """
    if not requests:
        raise ValueError("requests 不能为空")

    seen = [r.custom_id for r in requests]
    if len(set(seen)) != len(seen):
        raise ValueError("custom_id 必须唯一，否则结果对不回原始任务")

    conf = cfg or Config.from_env()
    base = model or conf.require_model("heavy" if heavy else "text")
    effort = reasoning_effort or (None if heavy else conf.reasoning_effort)

    body = http.post(
        conf,
        f"{conf.batch_url}/batches",
        {
            "endpoint": endpoint,
            "model": _with_batch_suffix(base),
            "requests": [r.to_payload(effort) for r in requests],
        },
    )
    status = _as_status(body)
    if not status.id:
        raise OpenRouterError(f"提交批次后没拿到 id，返回：{body}")
    return status


def get_batch(batch_id: str, *, cfg: Config | None = None) -> BatchStatus:
    if not batch_id.strip():
        raise ValueError("batch_id 不能为空")
    conf = cfg or Config.from_env()
    return _as_status(http.get(conf, f"{conf.batch_url}/batches/{batch_id}"))


def fetch_results(
    batch_id: str, *, cfg: Config | None = None
) -> tuple[BatchItem, ...]:
    """取结果。批次没结束就抛 BatchNotFinished，不返回空元组。

    返回空元组会跟「跑完了但没有结果」长得一样，
    调用方分不出是没跑完还是真没结果。
    """
    if not batch_id.strip():
        raise ValueError("batch_id 不能为空")

    conf = cfg or Config.from_env()
    body = http.get(conf, f"{conf.batch_url}/batches/{batch_id}")
    status = _as_status(body)

    if not status.is_done:
        raise BatchNotFinished(
            f"批次 {batch_id} 还在 {status.status}"
            f"（{status.completed}/{status.total} 完成）"
        )
    if not status.is_success:
        raise OpenRouterError(
            f"批次 {batch_id} 以 {status.status} 结束：{body.get('error')}"
        )

    return tuple(_parse_items(body.get("results") or []))


def _parse_items(raw: Iterable[Mapping[str, Any]]) -> Iterable[BatchItem]:
    for entry in raw:
        cid = str(entry.get("custom_id") or "")

        if entry.get("error"):
            yield BatchItem(cid, "", str(entry["error"]))
            continue

        response = entry.get("response") or {}
        code = response.get("status_code")
        if code is not None and int(code) >= 400:
            yield BatchItem(cid, "", f"HTTP {code}: {str(response.get('body'))[:200]}")
            continue

        body = response.get("body") or {}
        choices = body.get("choices") or []
        if not choices:
            yield BatchItem(cid, "", f"返回没有 choices：{str(body)[:200]}")
            continue

        choice = choices[0]
        text = (choice.get("message") or {}).get("content") or ""

        # HTTP 200 但正文为空，多半是思考把 max_tokens 吃光了。
        # 这种条目必须标成失败，否则整批空结果会被当成「模型没话说」。
        if not text.strip():
            usage = body.get("usage") or {}
            rt = (usage.get("completion_tokens_details") or {}).get("reasoning_tokens", 0)
            yield BatchItem(
                cid,
                "",
                f"空正文（finish_reason={choice.get('finish_reason')}，"
                f"思考用掉 {rt} tokens）：调大 max_tokens 或降低 reasoning_effort",
            )
            continue

        yield BatchItem(cid, text)


def wait_batch(
    batch_id: str,
    *,
    poll_seconds: int = 30,
    timeout_seconds: int = 24 * 3600,
    cfg: Config | None = None,
    on_progress=None,
) -> tuple[BatchItem, ...]:
    """阻塞等批次跑完。默认最多等满 24 小时的承诺窗口。

    长任务别用这个占着进程，拿 batch_id 存下来，之后用 get_batch 查更实际。
    """
    if poll_seconds < 5:
        raise ValueError("poll_seconds 不要小于 5，免得把自己打成限流")

    conf = cfg or Config.from_env()
    deadline = time.monotonic() + timeout_seconds

    while True:
        status = get_batch(batch_id, cfg=conf)
        if on_progress is not None:
            on_progress(status)
        if status.is_done:
            return fetch_results(batch_id, cfg=conf)
        if time.monotonic() >= deadline:
            raise BatchNotFinished(
                f"等了 {timeout_seconds}s，批次 {batch_id} 仍是 {status.status}"
                f"（{status.completed}/{status.total}）"
            )
        time.sleep(poll_seconds)
