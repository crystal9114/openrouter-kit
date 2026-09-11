#!/usr/bin/env bash
# 一键安装：建虚拟环境、装依赖、跑一次自检（自检不发请求，不花钱）
set -euo pipefail

cd "$(dirname "$0")"

PY="${PYTHON:-python3}"
command -v "$PY" >/dev/null 2>&1 || PY=python

echo "==> 使用 $($PY --version)"

if [ ! -d .venv ]; then
  echo "==> 创建 .venv"
  "$PY" -m venv .venv
fi

if [ -f .venv/bin/activate ]; then
  . .venv/bin/activate           # Linux / macOS
else
  . .venv/Scripts/activate       # Windows Git Bash
fi

echo "==> 安装依赖"
python -m pip install -q --upgrade pip
python -m pip install -q -r requirements.txt

echo "==> 自检（只校验能否导入与配置解析，不发任何请求）"
PYTHONPATH=src python - <<'PYEOF'
import sys

# Windows 控制台默认 GBK，不改中文会乱码
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

import openrouter_client as oc

# 缺 key 必须在构造时就失败，而不是等到第一次调用
try:
    oc.Config.from_env({})
    raise SystemExit("自检失败：缺 key 时没有报错")
except oc.OpenRouterConfigError:
    pass

cfg = oc.Config.from_env({
    "OPENROUTER_API_KEY": "sk-or-v1-" + "x" * 64,
    "OPENROUTER_MODEL_IMAGE": "openai/gpt-image-2.5-sunburst",
    "OPENROUTER_MODEL_TEXT": "anthropic/claude-fable-5.1",
})
assert cfg.base_url == oc.DEFAULT_BASE_URL
print("自检通过")
PYEOF

cat <<'EOF'

安装完成。使用前先把凭证注入环境（真值在密匣 mixia 的 secrets/personal/common.env）：

  set -a; . /path/to/mixia/secrets/personal/common.env; set +a

然后跑一次真实调用（会产生少量费用）：

  PYTHONPATH=src python src/openrouter_client.py            # 只测文本
  PYTHONPATH=src python src/openrouter_client.py --with-image  # 文本 + 生图
EOF
