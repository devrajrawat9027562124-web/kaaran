"""Copy the accounts database to a dated backup file, keeping the newest few.

    python3 backup.py /var/lib/kaaran/kaaran.db /var/backups/kaaran 14

Uses SQLite's own backup, which is safe while the server is running (a plain
file copy taken mid-write can be broken). Run daily by kaaran-backup.timer.
"""
import datetime
import pathlib
import sqlite3
import sys


def backup(database, folder, keep):
    folder.mkdir(parents=True, exist_ok=True)
    target = folder / f"kaaran-{datetime.datetime.now():%Y-%m-%d-%H%M}.db"
    source = sqlite3.connect(f"file:{database}?mode=ro", uri=True)
    copy = sqlite3.connect(target)
    with copy:
        source.backup(copy)
    source.close()
    copy.close()
    # Oldest first; names sort by date
    old = sorted(folder.glob("kaaran-*.db"))[:-keep]
    for path in old:
        path.unlink()
    return target, len(old)


def main():
    if len(sys.argv) != 4:
        print(__doc__)
        return 2
    database, folder, keep = pathlib.Path(sys.argv[1]), pathlib.Path(sys.argv[2]), int(sys.argv[3])
    if not database.exists():
        print(f"No database at {database} yet: nothing to back up.")
        return 0
    target, removed = backup(database, folder, max(keep, 1))
    print(f"Backed up to {target}" + (f", removed {removed} old backup(s)" if removed else ""))
    return 0


if __name__ == "__main__":
    sys.exit(main())
