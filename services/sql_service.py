import csv
import io
import re

import pyodbc

from shared.config import required_setting, setting

_IDENTIFIER = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


def _quote_table_name(table_name: str) -> str:
    """Validate and quote schema.table to avoid SQL identifier injection."""
    parts = table_name.split(".")
    if len(parts) not in (1, 2) or not all(_IDENTIFIER.match(p) for p in parts):
        raise ValueError(
            "SQL table name must be table or schema.table using letters, "
            "numbers and underscores only."
        )
    return ".".join(f"[{part}]" for part in parts)


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
        "Connection Timeout=30;"
    )


def insert_csv(csv_content: bytes, table_name: str, batch_size: int = 500) -> int:
    """
    Insert CSV rows into an existing SQL table.

    The destination table must already exist and have columns matching
    the CSV header names. Values are parameterized; table/column identifiers
    are validated before being included in the SQL statement.
    """
    text = csv_content.decode("utf-8-sig")
    reader = csv.reader(io.StringIO(text))

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
    connection = pyodbc.connect(_connection_string())
    try:
        cursor = connection.cursor()
        cursor.fast_executemany = True

        batch = []
        for row in reader:
            if not row:
                continue
            if len(row) != len(headers):
                raise ValueError(
                    f"CSV row has {len(row)} values; expected {len(headers)}."
                )

            batch.append(tuple(value if value != "" else None for value in row))

            if len(batch) >= batch_size:
                cursor.executemany(sql, batch)
                total_inserted += len(batch)
                batch.clear()

        if batch:
            cursor.executemany(sql, batch)
            total_inserted += len(batch)

        connection.commit()
        return total_inserted

    except Exception:
        connection.rollback()
        raise
    finally:
        connection.close()
