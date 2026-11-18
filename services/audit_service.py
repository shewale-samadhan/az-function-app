
import logging

from services.sql_service import _get_connection
from shared.config import required_setting


def update_audit(audit_payload: dict) -> dict:
    """
    Insert or update overall ETL execution details
    in the Audit table.
    """

    action = audit_payload.get("action")
    connection = None

    try:
        connection = _get_connection()
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
