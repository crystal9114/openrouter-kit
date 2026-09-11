"""跑批示例：五折，但要等。

实测一个 2 条的小批次约 5 分钟返回，官方承诺窗口是 24 小时。
适合半夜出稿这类不等结果的活，聊天和写代码用不了。

    set -a; . /path/to/mixia/secrets/personal/common.env; set +a
    PYTHONPATH=src python examples/batch_job.py
"""

import sys

from openrouter_client import BatchRequest, submit_batch, wait_batch

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

TOPICS = {
    "alu": "用两句话说明铝的密度和它在包装行业的意义",
    "fe": "用两句话说明铁的密度和它与铝的差别",
}

requests = tuple(
    # max_tokens 要留足。思考会先吃这份预算，给少了正文一个字都剩不下，
    # 而且批次要等几分钟才发现整批都是空的。
    BatchRequest(cid, ({"role": "user", "content": q},), max_tokens=400)
    for cid, q in TOPICS.items()
)

status = submit_batch(requests)
print(f"已提交 {status.id}")
print(f"  模型 {status.model}  共 {status.total} 条\n")


def show(s):
    print(f"  [{s.status}] {s.completed}/{s.total} 完成，失败 {s.failed}")


items = wait_batch(status.id, poll_seconds=15, timeout_seconds=1800, on_progress=show)

print()
ok = 0
for item in items:
    if item.ok:
        ok += 1
        print(f"[{item.custom_id}] {item.text.strip()}")
    else:
        # 空正文在这里会被判成失败，不会伪装成「模型没话说」
        print(f"[{item.custom_id}] 失败：{item.error}", file=sys.stderr)

print(f"\n{ok}/{len(items)} 成功")
