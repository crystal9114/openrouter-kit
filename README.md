# openrouter-kit

OpenRouter 的文本、生图与跑批封装。配置全部走环境变量，代码里没有任何硬编码的 key 或模型名。

真值存在密匣 mixia 的 `secrets/personal/common.env`，本仓只有占位示例。

## 三个端点，走错就 404

这是 OpenRouter 的硬约束，不是风格问题。

| 用途 | 端点 | 本库入口 |
|---|---|---|
| 文本、代码 | `/v1/chat/completions` | `chat()` |
| 生图 | `/v1/images/generations` | `generate_image()` |
| 跑批（五折，异步） | `/api/beta/batches` | `submit_batch()` |

把纯生图模型丢进 chat 端点，上游明确拒绝：

```
openai/gpt-image-2.5-sunburst is an image generation model and
cannot be used with the chat/completions endpoint.
```

把 `:batch` 模型丢进 chat 端点也一样：

```
This model is only available through the Batch API.
Use the /api/beta/batches endpoint instead.
```

**端点选错不只是报错，还可能贵几十倍。** 同一张图：

| 走法 | image tokens | 单张成本 |
|---|---|---|
| `gpt-image-2.5-sunburst` 走 images 端点 | 158 | **$0.0049** |
| `gpt-5.4-image-2` 走 chat 端点 | 7024 | **$0.2247** |

## 三档模型

| 档位 | 环境变量 | 当前值 | 价格 |
|---|---|---|---|
| 生图 | `OPENROUTER_MODEL_IMAGE` | `openai/gpt-image-2.5-sunburst` | $0.0049/张 |
| 日常 | `OPENROUTER_MODEL_TEXT` | `google/gemini-3.8-flash` | $0.75 / $3.75 每 M |
| 掌控 | `OPENROUTER_MODEL_HEAVY` | `google/gemini-3.8-flash` | 同上，靠放开思考拉开档位 |

两档同一个模型，区别只在思考强度：日常档压到 `low`（$0.000115），掌控档不压（$0.001116）。需要深一点的推理时显式 `chat(..., heavy=True)`。

2026-09-11 停用 Fable 5.1（$10/$50 太贵）。**也不要换成 Gemini Pro 档**：实测 `gemini-3.1-pro-preview` 对 `effort=low` 不买账，思考照跑 478 tokens、正文还被截断，单次 $0.005972，比 Fable 还贵。

某一档没配会直接报错，**不会静默回退到别的档**：悄悄换成贵的会烧钱，换成便宜的会让质量无声下降，两种都比报错难查。

## 思考关不掉，但能压到最低档，省九成

Gemini 这类模型默认开思考，reasoning token 按输出价计费。实测同一个问题：

| 写法 | reasoning tokens | 成本 | 说明 |
|---|---|---|---|
| `reasoning.enabled=false` | — | — | 400 `Reasoning is mandatory and cannot be disabled` |
| `reasoning.max_tokens=0` | — | — | 同样 400 |
| `reasoning.exclude=true` | 218 | $0.000966 | **陷阱**：只是不返回给你看，照样计费 |
| **`reasoning.effort=low`** | **0** | **$0.000115** | 答案质量无差别 |
| 不传 | 265 | $0.001116 | |

`effort=low` 比默认便宜约 **9.7 倍**。本库对日常档默认就传 `low`，掌控档不设限（要的就是深度推理）。用 `OPENROUTER_REASONING_EFFORT` 改全局默认，或在单次调用传 `reasoning_effort=`。

## 空正文会被当成失败，不会伪装成"模型没话说"

思考会先吃 `max_tokens` 预算。给少了就会出现这种结果：

```
HTTP 200，finish_reason=length，content=None，
completion_tokens=17，其中 reasoning_tokens=17
```

钱照扣，正文一个字没有。本库遇到空正文一律抛异常，并带上 `finish_reason`、思考用掉多少 token、本次仍然计费多少，直接指向该调大 `max_tokens` 还是该降 `reasoning_effort`。

跑批里这个坑更贵，因为要等几分钟才发现整批都是空的，所以 `BatchItem` 同样把空正文标成 `error`。

## 安装

```bash
./install.sh
```

建 `.venv`、装依赖、跑离线自检（不发请求、不需要 key）。

装进别的项目：

```bash
pip install git+https://github.com/crystal9114/openrouter-kit.git
```

## 使用

先注入凭证：

```bash
set -a; . /path/to/mixia/secrets/personal/common.env; set +a
```

实时调用：

```python
from openrouter_client import chat, generate_image, OpenRouterError

try:
    r = chat([{"role": "user", "content": "写个读 CSV 的函数"}], max_tokens=800)
    print(r.text, r.cost_usd, r.reasoning_tokens)
except OpenRouterError as exc:
    print(f"失败：{exc}")

r = chat(messages, heavy=True)          # 掌控档
img = generate_image("一块拉丝铝板特写")
img.save("out/alu.png")
```

跑批（五折）：

```python
from openrouter_client import BatchRequest, submit_batch, wait_batch

reqs = [
    BatchRequest("a1", ({"role": "user", "content": "改写这段"},), max_tokens=400),
    BatchRequest("a2", ({"role": "user", "content": "改写那段"},), max_tokens=400),
]
st = submit_batch(reqs)          # 模型名自动补 :batch
items = wait_batch(st.id, poll_seconds=30)

for it in items:
    print(it.custom_id, it.text) if it.ok else print(it.custom_id, it.error)
```

`custom_id` 必须唯一，否则结果对不回原始任务，提交前就会报错。

长任务别用 `wait_batch` 占着进程，存下 `st.id`，之后用 `get_batch()` 查。

## 跑批要等多久

官方承诺窗口 24 小时。实测一个 2 条的小批次 **315 秒** 返回。适合半夜出稿、批量改写这类不等结果的活，聊天和写代码用不了。

## 在 docker 里用

```yaml
services:
  yourapp:
    env_file:
      - /www/wwwroot/mixia/secrets/personal/common.env
```

改了 mixia 的值必须 `docker compose up -d --force-recreate`，`restart` 不会重读 env_file。

## 错误约定

失败永远抛异常，绝不返回跟"没结果"同形的空值。

| 异常 | 什么时候 |
|---|---|
| `OpenRouterConfigError` | 配置缺失或非法，构造 `Config` 时就抛 |
| `OpenRouterError` | 请求失败、HTTP 非 200、返回无图、空正文、解码失败、不是 PNG |
| `BatchNotFinished` | 批次还没结束。这不是错误，是让你继续等，区别于"跑完了但没结果" |
| `ValueError` | 入参问题：空 prompt、空 messages、custom_id 重复、轮询间隔过小 |

## 计费须知

- token 不加价，实测与厂商官网同价
- 充值收 5.5% 手续费，最低 $0.80
- 额度一年未使用会过期
- 免费模型（`:free` 结尾）：20 次/分钟；累计充值满 $10 的账号 1000 次/天，未满 50 次/天
- **没有完全免费的生图模型**

## 查可用模型

默认的 models 端点不返回全部生图模型，必须带参数：

```bash
curl -H "Authorization: Bearer $OPENROUTER_API_KEY" \
  "https://openrouter.ai/api/v1/models?output_modalities=image"
```

不带 `output_modalities=image` 只能看到 9 个，带上是 54 个。
