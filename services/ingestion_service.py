import logging
import time
from dataclasses import dataclass
from datetime import datetime, timezone

from services.audit_service import update_audit
from services.github_service import download_csv
from services.logging_service import insert_execution_log
from services.sql_service import (
    LoadStats,
    close_quietly,
    ensure_alive,
    get_connection,
    insert_csv,
)
from shared.config import setting

SOURCE_TYPE = "GitHub"


@dataclass(frozen=True)
class Dataset:
    """Describes one source CSV file and its target table."""

    entity: str               # e.g. "orders"
    function_name: str        # activity name, used in audit / log tables
    csv_path_setting: str     # app setting holding the GitHub path
    csv_path_default: str
    table_setting: str        # app setting holding the target table
    table_default: str


def _best_effort(description: str, func, *args) -> None:
    """Run bookkeeping that must never mask the real outcome of the load."""
    try:
        func(*args)
    except Exception:
        logging.exception("Failed to %s.", description)


def run_ingestion(dataset: Dataset, run_id: str) -> dict:
    """
    GitHub CSV -> Azure SQL for one dataset.

    - Uses ONE SQL connection for audit, load and execution log.
    - Parses the CSV once (row counts come from the load itself).
    - Raises on failure so the orchestrator's retry policy can kick in.
      Audit and execution log are written either way.
    """

    name = dataset.function_name
    logging.info("RunID received by %s: %r", name, run_id)

    csv_path = setting(dataset.csv_path_setting, dataset.csv_path_default)
    table_name = setting(dataset.table_setting, dataset.table_default)

    # Extract schema and table name
    target_schema, target_table = table_name.split(".", 1)

    start_timestamp = datetime.now(timezone.utc)
    start_time = time.perf_counter()

    stats = LoadStats()
    status = "Failed"
    error_message = None
    audit_started = False

    # If this fails after its own retries, the activity fails and the
    # orchestrator retries the whole activity.
    connection = get_connection()

    try:
        # 1. Start audit
        try:
            update_audit(connection, {
                "action": "start",
                "run_id": run_id,
                "function_name": name,
                "source_type": SOURCE_TYPE,
                "file_name": csv_path,
                "start_time": start_timestamp.isoformat(),
            })
            audit_started = True
        except Exception:
            logging.exception("Failed to create %s audit record.", dataset.entity)

        try:
            logging.info(
                "Starting %s ingestion from GitHub path: %s",
                dataset.entity,
                csv_path,
            )

            # 2. Download CSV
            csv_content = download_csv(csv_path)

            # 3. Parse once + insert into Azure SQL
            inserted = insert_csv(connection, csv_content, table_name, stats)

            status = "Succeeded"

            logging.info(
                "%s ingestion completed. Rows inserted: %s",
                dataset.entity.capitalize(),
                inserted,
            )

        except Exception as exc:
            error_message = str(exc)
            logging.exception("%s ingestion failed.", dataset.entity.capitalize())
            raise  # let the orchestrator retry; bookkeeping runs in `finally`

        finally:
            end_timestamp = datetime.now(timezone.utc)
            duration = time.perf_counter() - start_time

            # The connection may have dropped during a long load.
            try:
                connection = ensure_alive(connection)
            except Exception:
                logging.exception("Could not re-establish SQL connection for bookkeeping.")
            else:
                # 4. Finish audit
                if audit_started:
                    _best_effort(
                        f"update {dataset.entity} audit record",
                        update_audit,
                        connection,
                        {
                            "action": "finish",
                            "run_id": run_id,
                            "function_name": name,
                            "end_time": end_timestamp.isoformat(),
                            "duration_seconds": int(duration),
                            "status": status,
                            "error_message": error_message,
                        },
                    )

                # 5. Dataset execution log
                _best_effort(
                    f"insert {dataset.entity} execution log",
                    insert_execution_log,
                    connection,
                    {
                        "run_id": run_id,
                        "function_name": name,
                        "entity_name": dataset.entity,
                        "source_type": SOURCE_TYPE,
                        "source_file_name": csv_path,
                        "target_schema": target_schema,
                        "target_table": target_table,
                        "start_timestamp": start_timestamp.isoformat(),
                        "end_timestamp": end_timestamp.isoformat(),
                        "duration": duration,
                        "rows_read": stats.rows_read,
                        "rows_written": stats.rows_written,
                        "status": status,
                        "error_message": error_message,
                    },
                )

    finally:
        close_quietly(connection)

    return {
        "dataset": dataset.entity,
        "source": csv_path,
        "destination": table_name,
        "rows_read": stats.rows_read,
        "rows_written": stats.rows_written,
        "start_timestamp": start_timestamp.isoformat(),
        "end_timestamp": end_timestamp.isoformat(),
        "duration": duration,
        "status": status,
        "error_message": error_message,
    }
