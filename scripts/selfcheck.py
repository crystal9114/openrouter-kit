"""离线自检：只验证配置解析与防呆，不发任何网络请求，不花钱，不需要 key。

install.sh 与 CI 共用这一份。
"""

import sys

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

import openrouter_client as oc

FAKE_KEY = "sk-or-v1-" + "x" * 64
FULL = {
    "OPENROUTER_API_KEY": FAKE_KEY,
    "OPENROUTER_MODEL_IMAGE": "openai/gpt-image-2.5-sunburst",
    "OPENROUTER_MODEL_TEXT": "google/gemini-3.8-flash",
    "OPENROUTER_MODEL_HEAVY": "anthropic/claude-fable-5.1",
}

failures: list[str] = []


def expect(name, exc_type, fn):
    try:
        fn()
    except exc_type:
        return
    except Exception as exc:  # noqa: BLE001
        failures.append(f"{name}: 抛了 {type(exc).__name__} 而不是 {exc_type.__name__}")
        return
    failures.append(f"{name}: 没有报错")


# 配置必须在构造期就挡住问题，而不是拖到第一次调用才炸
expect("缺 API key", oc.OpenRouterConfigError, lambda: oc.Config.from_env({}))
expect(
    "key 格式错",
    oc.OpenRouterConfigError,
    lambda: oc.Config.from_env({"OPENROUTER_API_KEY": "nope"}),
)
expect(
    "非法 reasoning_effort",
    oc.OpenRouterConfigError,
    lambda: oc.Config.from_env({**FULL, "OPENROUTER_REASONING_EFFORT": "off"}),
)

cfg = oc.Config.from_env(FULL)
if cfg.base_url != oc.DEFAULT_BASE_URL:
    failures.append(f"base_url 默认值不对：{cfg.base_url}")
if cfg.reasoning_effort != "low":
    failures.append(f"reasoning_effort 默认值应为 low，实际 {cfg.reasoning_effort}")

# 某一档没配时不能静默回退到别的档：悄悄换贵的会烧钱，换便宜的会让质量无声下降
bare = oc.Config.from_env({"OPENROUTER_API_KEY": FAKE_KEY})
expect("未配生图模型", oc.OpenRouterConfigError, lambda: bare.require_model("image"))
expect("未配文本模型", oc.OpenRouterConfigError, lambda: bare.require_model("text"))
expect("未配掌控模型", oc.OpenRouterConfigError, lambda: bare.require_model("heavy"))
expect("未知档位", ValueError, lambda: cfg.require_model("nope"))

# 入参防呆
expect("空 prompt", ValueError, lambda: oc.generate_image("   ", cfg=cfg))
expect("空 messages", ValueError, lambda: oc.chat([], cfg=cfg))
expect("空批次", ValueError, lambda: oc.submit_batch([], cfg=cfg))
expect("空 batch_id", ValueError, lambda: oc.get_batch("  ", cfg=cfg))

# batch 模型丢进 chat 端点必须在本地就挡住，不要打到上游换一个 404
expect(
    "batch 模型走 chat",
    ValueError,
    lambda: oc.chat(
        [{"role": "user", "content": "hi"}],
        model="anthropic/claude-fable-5.1:batch",
        cfg=cfg,
    ),
)

# custom_id 重复会让结果对不回原始任务
expect(
    "custom_id 重复",
    ValueError,
    lambda: oc.submit_batch(
        [
            oc.BatchRequest("same", ({"role": "user", "content": "a"},)),
            oc.BatchRequest("same", ({"role": "user", "content": "b"},)),
        ],
        cfg=cfg,
    ),
)

# 轮询间隔太小会把自己打成限流
expect(
    "poll_seconds 过小",
    ValueError,
    lambda: oc.wait_batch("batch-x", poll_seconds=1, cfg=cfg),
)

if failures:
    print("自检失败：")
    for line in failures:
        print(f"  - {line}")
    sys.exit(1)

print("自检通过")
