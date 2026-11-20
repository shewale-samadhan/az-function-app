import logging
from datetime import datetime, timezone

from shared.config import required_setting

_AUDIT_TABLE = "dbo.GITHUB_ETL_AUDIT"


def update_audit(connection, audit_payload: dict) -> dict:
    """
    Insert or update one audit row for a (RunID, FunctionName) pair using the
    caller's connection. The caller owns (and closes) the connection.

    "start" is an upsert, so a Durable retry of the same activity resets its
    row to Running instead of creating a duplicate.
    "finish" updates only that function's row.
    """

    action = audit_payload.get("action")

    try:
        cursor = connection.cursor()

        if action == "start":
            cursor.execute(
                f"""
                UPDATE {_AUDIT_TABLE}
                SET SourceType = ?,
                    FileName = ?,
                    TargetDatabase = ?,
                    StartTime = ?,
                    EndTime = NULL,
                    DurationSeconds = NULL,
                    Status = ?,
                    ErrorMessage = NULL
                WHERE RunID = ?
                  AND FunctionName = ?
                """,
                audit_payload["source_type"],
                audit_payload.get("file_name"),
                required_setting("SQL_DATABASE"),
                audit_payload["start_time"],
                "Running",
                audit_payload["run_id"],
                audit_payload["function_name"],
            )

            if cursor.rowcount == 0:
                cursor.execute(
                    f"""
                    INSERT INTO {_AUDIT_TABLE}
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
                    "Running",
                )

        elif action == "finish":
            duration = audit_payload.get("duration_seconds")

            cursor.execute(
                f"""
                UPDATE {_AUDIT_TABLE}
                SET EndTime = ?,
                    DurationSeconds = ?,
                    Status = ?,
                    ErrorMessage = ?
                WHERE RunID = ?
                  AND FunctionName = ?
                """,
                audit_payload["end_time"],
                int(duration) if duration is not None else None,
                audit_payload["status"],
                audit_payload.get("error_message"),
                audit_payload["run_id"],
                audit_payload["function_name"],
            )

            if cursor.rowcount == 0:
                raise ValueError(
                    "Audit record not found for the supplied RunID and function."
                )

        else:
            raise ValueError(f"Unsupported audit action: {action}")

        connection.commit()

        logging.info("Audit %s completed successfully.", action)

        return {"success": True, "action": action}

    except Exception:
        try:
            connection.rollback()
        except Exception:
            pass

        logging.exception("Audit operation failed.")
        raise


def finalize_run(connection, run_id: str, outcomes: list) -> int:
    """
    Called by the orchestrator once every file has finished (or exhausted its
    retries). Any audit row of this run still marked "Running" - because the
    activity crashed, timed out, or its own final audit write failed - is set
    to the final status the orchestrator observed for that function.

    Rows that already carry a final status are left untouched.
    Returns the number of rows reconciled.
    """

    end_time = datetime.now(timezone.utc).isoformat()
    reconciled = 0

    try:
        cursor = connection.cursor()

        for outcome in outcomes:
            function_name = outcome.get("function_name")
            if not function_name:
                continue

            cursor.execute(
                f"""
                UPDATE {_AUDIT_TABLE}
                SET EndTime = ?,
                    Status = ?,
                    ErrorMessage = ?
                WHERE RunID = ?
                  AND FunctionName = ?
                  AND Status = 'Running'
                """,
                end_time,
                outcome["status"],
                outcome.get("error_message"),
                run_id,
                function_name,
            )
            reconciled += max(cursor.rowcount, 0)

        connection.commit()

        logging.info(
            "Run %s finalized; %d audit row(s) reconciled.", run_id, reconciled
        )
        return reconciled

    except Exception:
        try:
            connection.rollback()
        except Exception:
            pass

        logging.exception("Run finalization failed.")
        raise
