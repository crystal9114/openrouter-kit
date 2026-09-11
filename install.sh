#!/usr/bin/env bash
# 一键安装：建虚拟环境、装依赖、跑离线自检（不发请求，不花钱）
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

echo "==> 离线自检"
PYTHONPATH=src python scripts/selfcheck.py

cat <<'EOF'

安装完成。使用前先把凭证注入环境（真值在密匣 mixia 的 secrets/personal/common.env）：

  set -a; . /path/to/mixia/secrets/personal/common.env; set +a

然后跑真实调用（会产生少量费用）：

  PYTHONPATH=src python examples/basic.py               # 日常档 + 掌控档
  PYTHONPATH=src python examples/basic.py --with-image  # 再加一张图
  PYTHONPATH=src python examples/batch_job.py           # 跑批五折，约几分钟
EOF
