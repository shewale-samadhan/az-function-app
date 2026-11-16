import logging
import azure.durable_functions as df
from services.sql_service import get_sql_connection
from shared.config import required_setting

bp = df.Blueprint()


@bp.activity_trigger(input_name="audit_payload")
def audit_activity(audit_payload: dict) -> dict:
    """
    Insert or update overall ETL execution details in the Audit table.
    """

    action = audit_payload.get("action")
    connection = None

    try:
        connection = get_sql_connection()
        cursor = connection.cursor()

        if action == "start":
            cursor.execute(
                """
                INSERT INTO GITHUB_ETL_MONITORING.GITHUB_ETL_AUDIT
                (
                    RunID,
                    FunctionName,
                    SourceType,
                    FileName,
                    TargetDatabase,
                    StartTime,
                    Status
                )
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                audit_payload["run_id"],
                audit_payload["function_name"],
                audit_payload["source_type"],
                audit_payload.get("file_name"),
                required_setting("SQL_DATABASE"),
                audit_payload["start_time"],
                "Running"
            )

        elif action == "finish":
            duration = audit_payload.get("duration_seconds")

            cursor.execute(
                """
                UPDATE GITHUB_ETL_MONITORING.GITHUB_ETL_AUDIT
                SET EndTime = ?,
                    DurationSeconds = ?,
                    Status = ?,
                    ErrorMessage = ?
                WHERE RunID = ?
                """,
                audit_payload["end_time"],
                int(duration) if duration is not None else None,
                audit_payload["status"],
                audit_payload.get("error_message"),
                audit_payload["run_id"]
            )

            if cursor.rowcount == 0:
                raise ValueError(
                    "Audit record not found for the supplied RunID."
                )

        else:
            raise ValueError(
                f"Unsupported audit action: {action}"
            )

        connection.commit()

        logging.info(
            "Audit %s completed successfully.",
            action
        )

        return {
            "success": True,
            "action": action
        }

    except Exception:
        if connection:
            connection.rollback()

        logging.exception("Audit operation failed.")
        raise

    finally:
        if connection:
            connection.close()


@bp.activity_trigger(input_name="log_payload")
def log_activity(log_payload: dict) -> dict:
    """
    Insert dataset-level execution details into the Execution Log table.
    """

    connection = None

    try:
        connection = get_sql_connection()
        cursor = connection.cursor()

        duration = log_payload.get("duration")

        cursor.execute(
            """
            INSERT INTO GITHUB_ETL_MONITORING.GITHUB_ETL_EXECUTION_LOG
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
            log_payload.get("error_message")
        )

        connection.commit()

        logging.info(
            "Execution log inserted for dataset: %s",
            log_payload["entity_name"]
        )

        return {
            "success": True,
            "entity_name": log_payload["entity_name"]
        }

    except Exception:
        if connection:
            connection.rollback()

        logging.exception("Execution log insertion failed.")
        raise

    finally:
        if connection:
            connection.close()
