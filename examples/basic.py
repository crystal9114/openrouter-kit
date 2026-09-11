"""最小可用示例：生一张图、问一句话，并打印各自花了多少钱。

运行前先注入凭证（真值在密匣 mixia）：

    set -a; . /path/to/mixia/secrets/personal/common.env; set +a
    PYTHONPATH=src python examples/basic.py
"""

import sys

from openrouter_client import OpenRouterError, chat, generate_image

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

PROMPT = "一块拉丝铝板的特写，工业产品摄影，柔和侧光，纯白背景，高细节金属质感"

spent = 0.0

try:
    answer = chat(
        [{"role": "user", "content": "一句话说明什么是铝合金阳极氧化"}],
        max_tokens=200,
    )
    spent += answer.cost_usd
    print(f"[文本] {answer.model}  ${answer.cost_usd:.6f}  {answer.total_tokens} tokens")
    print(answer.text)
except OpenRouterError as exc:
    print(f"[文本] 失败：{exc}", file=sys.stderr)

print()

try:
    image = generate_image(PROMPT)
    spent += image.cost_usd
    saved = image.save("out/alu.png")
    print(f"[生图] {image.model}  ${image.cost_usd:.6f}  {image.image_tokens} image tokens")
    print(f"       已保存 {saved}（{len(image.png) / 1024:.0f} KB）")
except OpenRouterError as exc:
    print(f"[生图] 失败：{exc}", file=sys.stderr)

print(f"\n本次合计 ${spent:.6f}")
