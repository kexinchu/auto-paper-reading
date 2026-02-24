#!/usr/bin/env python3
"""
清空 papers 表中全部数据，便于重复测试 pipeline。
用法: PYTHONPATH=. python tests/clear_papers_db.py [--config CONFIG] [--yes]
"""

import argparse
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from src.config import load_config
from src import db


def main() -> int:
    parser = argparse.ArgumentParser(description="清空 papers 表数据（测试用）")
    parser.add_argument("--config", type=Path, default=REPO_ROOT / "config" / "config.yaml", help="config.yaml 路径")
    parser.add_argument("--yes", "-y", action="store_true", help="跳过确认直接清空")
    args = parser.parse_args()

    if not args.config.exists():
        print(f"Config 不存在: {args.config}", file=sys.stderr)
        return 1

    config = load_config(args.config)
    db_path = (REPO_ROOT / config["storage"]["db_path"]).resolve()
    if not db_path.exists():
        print(f"数据库文件不存在: {db_path}", file=sys.stderr)
        return 1

    try:
        with db._conn(db_path) as conn:
            cur = conn.execute("SELECT COUNT(*) FROM papers")
            n = cur.fetchone()[0]
    except Exception as e:
        print(f"读取 papers 表失败: {e}", file=sys.stderr)
        return 1
    if n == 0:
        print("papers 表已是空的，无需清空")
        return 0

    if not args.yes:
        try:
            confirm = input(f"将删除 papers 表中 {n} 条记录，确认? [y/N]: ").strip().lower()
        except EOFError:
            confirm = "n"
        if confirm != "y" and confirm != "yes":
            print("已取消")
            return 0

    with db._conn(db_path) as conn:
        conn.execute("DELETE FROM papers")
        conn.commit()
    print(f"已清空 papers 表（共删除 {n} 条记录）: {db_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
