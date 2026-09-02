#!/usr/bin/env python3
"""
Backs up mess.db using SQLite's own online-backup API (safe even while the
app is running and writing to the database) and prunes old backups beyond
a retention count. This is the main protection against losing mess data
to a corrupted file, a failed SD card, or a dead machine -- there was
previously no backup mechanism at all.

Meant to run on a schedule:
  Linux (cron):   0 * * * * cd /opt/smart-hostel-mess && python3 scripts/backup_db.py
  Windows: use Task Scheduler to run this script hourly.

Usage:
    python3 scripts/backup_db.py                 # keeps the last 30 backups
    python3 scripts/backup_db.py --keep 60
    python3 scripts/backup_db.py --db /path/to/mess.db --out /path/to/backups
"""
import argparse
import sqlite3
import sys
from datetime import datetime
from pathlib import Path

def backup_sqlite(src_path: Path, dest_path: Path):
    # Uses SQLite's Online Backup API (not a plain file copy) so the
    # backup is consistent even if a write is in flight or the DB is
    # in WAL mode -- a plain file copy can capture a torn, unusable
    # snapshot in that situation.
    src = sqlite3.connect(str(src_path))
    dest = sqlite3.connect(str(dest_path))
    with dest:
        src.backup(dest)
    dest.close()
    src.close()

def main():
    parser = argparse.ArgumentParser(description="Back up the mess.db SQLite file.")
    parser.add_argument("--db", default="mess.db", help="Path to the SQLite database file")
    parser.add_argument("--out", default="backups", help="Directory to store backups in")
    parser.add_argument("--keep", type=int, default=30, help="Number of recent backups to keep")
    args = parser.parse_args()

    db_path = Path(args.db)
    out_dir = Path(args.out)
    if not db_path.exists():
        print(f"Database not found at {db_path}, nothing to back up.", file=sys.stderr)
        sys.exit(1)

    out_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
    dest = out_dir / f"mess_{stamp}.db"
    backup_sqlite(db_path, dest)
    print(f"Backed up {db_path} -> {dest}")

    backups = sorted(out_dir.glob("mess_*.db"))
    if len(backups) > args.keep:
        for old in backups[: len(backups) - args.keep]:
            old.unlink()
            print(f"Pruned old backup: {old}")

if __name__ == "__main__":
    main()
