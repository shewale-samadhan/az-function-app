import logging

from shared.config import required_setting


def insert_execution_log(connection, log_payload: dict) -> dict:
    """
    Insert dataset-level execution details into the Execution Log table using
    the caller's connection. The caller owns (and closes) the connection.

    One row is written per attempt, so a retried activity leaves a visible
    history (e.g. Failed, then Succeeded).
    """

    try:
        cursor = connection.cursor()

        duration = log_payload.get("duration")

        cursor.execute(
            """
            INSERT INTO dbo.GITHUB_ETL_EXECUTION_LOG
            (
                RunID,
                FunctionName,
                EntityName,
                SourceType,
                SourceFileName,
                TargetDatabase,
                TargetSchema,
                TargetTable,
                StartTimestamp,
                EndTimestamp,
                Duration,
                RowsRead,
                RowsWritten,
                Status,
                ErrorMessage
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            log_payload["run_id"],
            log_payload["function_name"],
            log_payload["entity_name"],
            log_payload["source_type"],
            log_payload.get("source_file_name"),
            required_setting("SQL_DATABASE"),
            log_payload["target_schema"],
            log_payload["target_table"],
            log_payload["start_timestamp"],
            log_payload.get("end_timestamp"),
            int(duration) if duration is not None else None,
            log_payload.get("rows_read"),
            log_payload.get("rows_written"),
            log_payload["status"],
            log_payload.get("error_message"),
        )

        connection.commit()

        logging.info(
            "Execution log inserted for dataset: %s", log_payload["entity_name"]
        )

        return {"success": True, "entity_name": log_payload["entity_name"]}

    except Exception:
        try:
            connection.rollback()
        except Exception:
            pass

        logging.exception("Execution log insertion failed.")
        raise
