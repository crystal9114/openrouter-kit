# openrouter-kit

OpenRouter 的文本与生图统一调用封装。配置全部走环境变量，代码里没有任何硬编码的 key 或模型名。

真值存在密匣 mixia 的 `secrets/personal/common.env`，本仓只有占位示例。

## 最重要的一件事：两类模型走两个端点

这是 OpenRouter 的硬约束，不是风格问题。走错直接 404，而且**计价相差约 46 倍**。

| 模型类型 | 端点 | 例子 |
|---|---|---|
| 纯生图模型 | `/images/generations` | `openai/gpt-image-2.5-sunburst`、`flux.2-*`、`seedream-*` |
| 多模态聊天模型 | `/chat/completions` + `modalities` | `openai/gpt-5.4-image-2`、`google/gemini-3-pro-image` |

把纯生图模型丢进 chat 端点，上游会明确拒绝：

```
openai/gpt-image-2.5-sunburst is an image generation model and
cannot be used with the chat/completions endpoint.
Use the /api/v1/images endpoint instead.
```

两条路的 image token 计数方式完全不同。2026-09-11 用同一句 prompt 实测：

| 走法 | image tokens | 单张成本 |
|---|---|---|
| Sunburst 走 `/images/generations` | 158 ~ 186 | **$0.0049 ~ $0.0057** |
| gpt-5.4-image-2 走 `/chat/completions` | 7024 | **$0.2247** |

本库的 `generate_image()` 固定走 images 端点，`chat()` 固定走 chat 端点，不会走错。

## 生图模型实测对比

同一句 prompt（拉丝铝板工业产品摄影），2026-09-11：

| 模型 | 单价/张 | 分辨率 | 耗时 |
|---|---|---|---|
| `openai/gpt-image-2.5-sunburst` | $0.0049 | 1536×1024 | 14s |
| `openai/gpt-image-2.5-flare` | $0.0049 | 1536×1024 | 12s |
| `google/gemini-3-pro-image`（Nano Banana Pro） | $0.1345 | 1408×768 | 25s |

Sunburst 更便宜、更快、分辨率更大，是当前默认。

## 安装

```bash
./install.sh
```

建 `.venv`、装依赖、跑一次不发请求的自检。

或者直接从 git 装进别的项目：

```bash
pip install git+https://github.com/crystal9114/openrouter-kit.git
```

## 使用

先注入凭证（真值在 mixia）：

```bash
set -a; . /path/to/mixia/secrets/personal/common.env; set +a
```

然后：

```python
from openrouter_client import generate_image, chat, OpenRouterError

try:
    img = generate_image("一块拉丝铝板特写，工业产品摄影，柔和侧光，纯白背景")
    img.save("out/alu.png")
    print(f"{img.model}  ${img.cost_usd:.6f}  {img.image_tokens} image tokens")
except OpenRouterError as exc:
    print(f"生图失败：{exc}")

ans = chat([{"role": "user", "content": "写一个读取 CSV 的函数"}])
print(ans.text, ans.cost_usd)
```

临时换模型不用改 env：

```python
img = generate_image(prompt, model="openai/gpt-image-2.5-flare")
```

## 配置

| 变量 | 必填 | 说明 |
|---|---|---|
| `OPENROUTER_API_KEY` | 是 | 缺失或格式不对时**构造配置就失败**，不拖到第一次调用 |
| `OPENROUTER_BASE_URL` | 否 | 默认 `https://openrouter.ai/api/v1` |
| `OPENROUTER_MODEL_IMAGE` | 生图时必填 | 换生图模型只改这里 |
| `OPENROUTER_MODEL_TEXT` | 文本时必填 | 换文本模型只改这里 |

## 在 docker 里用

```yaml
services:
  yourapp:
    env_file:
      - /www/wwwroot/mixia/secrets/personal/common.env
```

改了 mixia 的值之后必须 `docker compose up -d --force-recreate`，
`restart` 不会重读 env_file。

## 错误处理约定

失败永远抛异常，绝不返回跟"没生成"同形的空值。

- `OpenRouterConfigError`：配置缺失或非法，启动即失败
- `OpenRouterError`：请求失败、HTTP 非 200、返回无图、base64 解码失败、结果不是 PNG
- `ValueError`：prompt 为空、messages 为空

图片解码兼容 `b64_json` 和 data URI 两种返回格式，两种都取不到就报错并列出实际字段，
不会写出一个坏文件让调用方以为成功了。解码后还会校验 PNG 文件头，上游换格式能立刻发现。

## 计费须知

- token 本身不加价，实测与厂商官网同价（Fable 5.1 = $10/M 输入、$50/M 输出）
- 充值时收 5.5% 手续费，最低 $0.80
- 额度一年未使用会过期，别一次充太多
- 免费模型（id 以 `:free` 结尾）：20 次/分钟；累计充值满 $10 的账号 1000 次/天，未满的 50 次/天
- **没有完全免费的生图模型**，一个都没有

## 查可用模型

默认的 models 端点不返回全部生图模型，必须带参数：

```bash
curl -H "Authorization: Bearer $OPENROUTER_API_KEY" \
  "https://openrouter.ai/api/v1/models?output_modalities=image"
```

不带 `output_modalities=image` 只能看到 9 个，带上是 54 个。
