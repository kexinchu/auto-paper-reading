#!/usr/bin/env python3
"""
初始化 storage 环境：根据 config 创建 data 目录、SQLite 数据库及 papers 表。
供 env_prepare.sh 调用，也可单独运行：PYTHONPATH=. python tests/setup_storage_db.py
"""

import sys
from pathlib import Path

# 项目根目录
REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from src.config import load_config
from src import db


def main() -> int:
    config_path = REPO_ROOT / "config" / "config.yaml"
    if not config_path.exists():
        print(f"Config not found: {config_path}", file=sys.stderr)
        return 1
    config = load_config(config_path)
    storage = config["storage"]
    root = REPO_ROOT

    db_path = (root / storage["db_path"]).resolve()
    pdf_dir = (root / storage["pdf_dir"]).resolve()
    text_dir = (root / storage["text_dir"]).resolve()

    db_path.parent.mkdir(parents=True, exist_ok=True)
    pdf_dir.mkdir(parents=True, exist_ok=True)
    text_dir.mkdir(parents=True, exist_ok=True)

    if db_path.exists():
        print(f"SQLite 已存在: {db_path}")
    else:
        print(f"创建 SQLite 数据库: {db_path}")
    db.ensure_db(db_path)
    print(f"存储目录: {pdf_dir}, {text_dir}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
