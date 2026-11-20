import csv
import io
import logging
import re
import time
from dataclasses import dataclass

import pyodbc

from shared.config import required_setting, setting

_IDENTIFIER = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")

DEFAULT_BATCH_SIZE = 2000


@dataclass
class LoadStats:
    """
    Row counters filled in by insert_csv while it parses and loads.

    rows_read    - non-empty data rows parsed so far (header excluded).
    rows_written - rows committed to SQL; stays 0 unless the whole load commits.
    """

    rows_read: int = 0
    rows_written: int = 0


# ---------------------------------------------------------------------------
# Connection handling
# ---------------------------------------------------------------------------

def _connection_string() -> str:
    server = required_setting("SQL_SERVER")
    database = required_setting("SQL_DATABASE")
    username = required_setting("SQL_USERNAME")
    password = required_setting("SQL_PASSWORD")
    driver = setting("SQL_ODBC_DRIVER", "ODBC Driver 18 for SQL Server")

    return (
        f"Driver={{{driver}}};"
        f"Server=tcp:{server},1433;"
        f"Database={database};"
        f"Uid={username};"
        f"Pwd={password};"
        "Encrypt=yes;"
        "TrustServerCertificate=no;"
        "Connection Timeout=60;"
    )


def get_connection(retries: int = 4, delay: int = 15):
    """
    Open a SQL connection, retrying on OperationalError (covers Azure SQL
    serverless resuming from auto-pause). The caller owns the connection and
    must close it (see close_quietly).
    """
    last_exc = None
    for attempt in range(1, retries + 1):
        try:
            return pyodbc.connect(_connection_string(), timeout=60)
        except pyodbc.OperationalError as exc:
            last_exc = exc
            logging.warning("SQL connect %d/%d failed: %s", attempt, retries, exc)
            if attempt < retries:
                time.sleep(delay)
    raise last_exc


def close_quietly(connection) -> None:
    """Close a connection, ignoring any error (already closed / dropped)."""
    if connection is None:
        return
    try:
        connection.close()
    except Exception:
        pass


def ensure_alive(connection):
    """
    Return a usable connection. If the given one has been dropped (for example
    after a long load), close it and open a fresh one.
    """
    try:
        cursor = connection.cursor()
        cursor.execute("SELECT 1")
        cursor.fetchone()
        cursor.close()
        return connection
    except pyodbc.Error:
        logging.warning("SQL connection is no longer usable; reconnecting.")
        close_quietly(connection)
        return get_connection()


# ---------------------------------------------------------------------------
# CSV loading
# ---------------------------------------------------------------------------

def _quote_table_name(table_name: str) -> str:
    """Validate and quote schema.table to avoid SQL identifier injection."""
    parts = table_name.split(".")
    if len(parts) not in (1, 2) or not all(_IDENTIFIER.match(p) for p in parts):
        raise ValueError(
            "SQL table name must be table or schema.table using letters, "
            "numbers and underscores only."
        )
    return ".".join(f"[{part}]" for part in parts)


def insert_csv(
    connection,
    csv_content: bytes,
    table_name: str,
    stats: LoadStats,
    batch_size: int = DEFAULT_BATCH_SIZE,
) -> int:
    """
    Insert CSV rows into an existing SQL table using the supplied connection.

    The destination table must already exist and have columns matching the
    CSV header names. Values are parameterized; table/column identifiers are
    validated before being included in the SQL statement.

    The CSV is parsed exactly once: rows are counted and batched in the same
    pass. The load is atomic - one commit at the end, rollback on any error.
    `stats` is updated as the file is processed so the caller still has
    rows_read if the load fails part-way. The connection is NOT closed here.
    """
    with io.TextIOWrapper(
        io.BytesIO(csv_content), encoding="utf-8-sig", newline=""
    ) as text:
        reader = csv.reader(text)

        try:
            headers = next(reader)
        except StopIteration:
            raise ValueError("CSV file is empty.")

        headers = [header.strip() for header in headers]
        if not headers or any(not _IDENTIFIER.match(h) for h in headers):
            raise ValueError("CSV contains an empty or unsupported column name.")

        quoted_table = _quote_table_name(table_name)
        quoted_columns = ", ".join(f"[{column}]" for column in headers)
        placeholders = ", ".join("?" for _ in headers)

        sql = (
            f"INSERT INTO {quoted_table} ({quoted_columns}) "
            f"VALUES ({placeholders})"
        )

        total_inserted = 0

        try:
            cursor = connection.cursor()
            cursor.fast_executemany = True

            batch = []

            for row in reader:
                if not row:
                    continue

                stats.rows_read += 1

                if len(row) != len(headers):
                    raise ValueError(
                        f"CSV row has {len(row)} values; expected {len(headers)}."
                    )

                batch.append(
                    tuple(value if value != "" else None for value in row)
                )

                if len(batch) >= batch_size:
                    cursor.executemany(sql, batch)
                    total_inserted += len(batch)
                    batch.clear()

            if batch:
                cursor.executemany(sql, batch)
                total_inserted += len(batch)

            connection.commit()
            stats.rows_written = total_inserted
            return total_inserted

        except Exception:
            connection.rollback()
            raise
