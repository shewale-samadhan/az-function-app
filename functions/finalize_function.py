import logging

import azure.durable_functions as df

from services.audit_service import finalize_run
from services.sql_service import close_quietly, get_connection

bp = df.Blueprint()


@bp.activity_trigger(input_name="payload")
def finalize_run_activity(payload: dict) -> dict:
    """
    Record the final run status decided by the orchestrator.

    Any audit row of this run still marked "Running" (activity crashed, timed
    out, or its own final audit write failed) is set to the status the
    orchestrator observed for that function.
    """

    run_id = payload["run_id"]
    logging.info("Finalizing run %s with status %s", run_id, payload["status"])

    connection = get_connection()
    try:
        reconciled = finalize_run(connection, run_id, payload["outcomes"])
    finally:
        close_quietly(connection)

    return {"run_id": run_id, "status": payload["status"], "reconciled": reconciled}
