#!/usr/bin/env python3
"""
按日期范围删除 papers 表中的记录（便于清理某段时间的失败/脏数据后重跑）。
用法: PYTHONPATH=. python tests/clear_papers_by_date.py [--config CONFIG] --from YYYY-MM-DD --to YYYY-MM-DD [--yes]
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
    parser = argparse.ArgumentParser(description="按日期范围删除 papers 表记录（按 created_at）")
    parser.add_argument("--config", type=Path, default=REPO_ROOT / "config" / "config.yaml", help="config 路径")
    parser.add_argument("--from", dest="from_date", required=True, metavar="YYYY-MM-DD", help="起始日期（含）")
    parser.add_argument("--to", dest="to_date", required=True, metavar="YYYY-MM-DD", help="结束日期（含）")
    parser.add_argument("--yes", "-y", action="store_true", help="跳过确认直接删除")
    args = parser.parse_args()

    if not args.config.exists():
        print(f"Config 不存在: {args.config}", file=sys.stderr)
        return 1

    from_str = f"{args.from_date} 00:00:00"
    to_end = f"{args.to_date} 23:59:59"

    config = load_config(args.config)
    db_path = (REPO_ROOT / config["storage"]["db_path"]).resolve()
    if not db_path.exists():
        print(f"数据库文件不存在: {db_path}", file=sys.stderr)
        return 1

    try:
        with db._conn(db_path) as conn:
            cur = conn.execute(
                "SELECT COUNT(*) FROM papers WHERE created_at >= ? AND created_at <= ?",
                (from_str, to_end),
            )
            n = cur.fetchone()[0]
    except Exception as e:
        print(f"查询 papers 表失败: {e}", file=sys.stderr)
        return 1

    if n == 0:
        print(f"没有 created_at 在 {args.from_date} ~ {args.to_date} 的记录，无需删除")
        return 0

    if not args.yes:
        try:
            confirm = input(f"将删除 {n} 条记录（created_at 在 {args.from_date} ~ {args.to_date}），确认? [y/N]: ").strip().lower()
        except EOFError:
            confirm = "n"
        if confirm not in ("y", "yes"):
            print("已取消")
            return 0

    with db._conn(db_path) as conn:
        conn.execute(
            "DELETE FROM papers WHERE created_at >= ? AND created_at <= ?",
            (from_str, to_end),
        )
        conn.commit()
    print(f"已删除 {n} 条记录: {db_path}（{args.from_date} ~ {args.to_date}）")
    return 0


if __name__ == "__main__":
    sys.exit(main())
