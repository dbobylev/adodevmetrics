import sqlite3


class CommitCache:
    """SQLite-кэш для хранения статистики изменений коммитов.

    Ключ: (repository, commit_id) — значения: lines_added, lines_deleted.
    Коммиты неизменяемы, поэтому кэш никогда не инвалидируется.
    """

    _DDL = """
    CREATE TABLE IF NOT EXISTS commit_changes (
        repository    TEXT    NOT NULL,
        commit_id     TEXT    NOT NULL,
        lines_added   INTEGER NOT NULL,
        lines_deleted INTEGER NOT NULL,
        PRIMARY KEY (repository, commit_id)
    )
    """

    def __init__(self, db_path: str = "commit_cache.db") -> None:
        self._conn = sqlite3.connect(db_path)
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.execute(self._DDL)
        self._conn.commit()

    # ------------------------------------------------------------------
    def get(self, repository: str, commit_id: str) -> tuple[int, int] | None:
        row = self._conn.execute(
            "SELECT lines_added, lines_deleted FROM commit_changes "
            "WHERE repository = ? AND commit_id = ?",
            (repository, commit_id),
        ).fetchone()
        return (row[0], row[1]) if row else None

    def put(self, repository: str, commit_id: str,
            lines_added: int, lines_deleted: int) -> None:
        self._conn.execute(
            "INSERT OR REPLACE INTO commit_changes "
            "(repository, commit_id, lines_added, lines_deleted) VALUES (?, ?, ?, ?)",
            (repository, commit_id, lines_added, lines_deleted),
        )
        self._conn.commit()

    # ------------------------------------------------------------------
    def close(self) -> None:
        self._conn.close()

    def __enter__(self):
        return self

    def __exit__(self, *_):
        self.close()
