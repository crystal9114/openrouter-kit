"""最小可用示例：三档模型各跑一次，打印各自花了多少钱。

运行前先注入凭证（真值在密匣 mixia）：

    set -a; . /path/to/mixia/secrets/personal/projects/openrouter.env; set +a
    PYTHONPATH=src python examples/basic.py
"""

import sys

from openrouter_client import OpenRouterError, chat, generate_image

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

QUESTION = [{"role": "user", "content": "用一句话说明什么是铝合金阳极氧化"}]
PROMPT = "一块拉丝铝板的特写，工业产品摄影，柔和侧光，纯白背景，高细节金属质感"

spent = 0.0

try:
    cheap = chat(QUESTION, max_tokens=500)
    spent += cheap.cost_usd
    print(f"[日常档] {cheap.model}")
    print(f"  ${cheap.cost_usd:.6f}  {cheap.total_tokens} tok  思考 {cheap.reasoning_tokens} tok")
    print(f"  {cheap.text.strip()}")
except OpenRouterError as exc:
    print(f"[日常档] 失败：{exc}", file=sys.stderr)

print()

try:
    heavy = chat(QUESTION, heavy=True, max_tokens=500)
    spent += heavy.cost_usd
    print(f"[掌控档] {heavy.model}")
    print(f"  ${heavy.cost_usd:.6f}  {heavy.total_tokens} tok  思考 {heavy.reasoning_tokens} tok")
    print(f"  {heavy.text.strip()}")
except OpenRouterError as exc:
    print(f"[掌控档] 失败：{exc}", file=sys.stderr)

print()

if "--with-image" in sys.argv:
    try:
        image = generate_image(PROMPT)
        spent += image.cost_usd
        saved = image.save("out/alu.png")
        print(f"[生图] {image.model}")
        print(f"  ${image.cost_usd:.6f}  {image.image_tokens} image tok")
        print(f"  已保存 {saved}（{len(image.png) / 1024:.0f} KB）")
    except OpenRouterError as exc:
        print(f"[生图] 失败：{exc}", file=sys.stderr)
else:
    print("[生图] 跳过，加 --with-image 参数可一并测试")

print(f"\n本次合计 ${spent:.6f}")
