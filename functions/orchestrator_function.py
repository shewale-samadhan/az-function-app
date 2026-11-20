import logging

import azure.durable_functions as df

bp = df.Blueprint()

# One activity per source file.
INGESTION_ACTIVITIES = (
    "orders_activity",
    "customers_activity",
    "products_activity",
)

# Each ingestion activity is attempted up to 2 times, 30 seconds apart.
RETRY_OPTIONS = df.RetryOptions(
    first_retry_interval_in_milliseconds=30_000,
    max_number_of_attempts=2,
)


@bp.orchestration_trigger(context_name="context")
def ingest_file_orchestrator(context: df.DurableOrchestrationContext):
    """
    Runs ONE ingestion activity with the retry policy and always returns an
    outcome dict (never raises). This lets the parent wait for every file to
    finish and see all outcomes, even when one file fails after its retries.
    """

    payload = context.get_input()
    activity_name = payload["activity_name"]

    try:
        result = yield context.call_activity_with_retry(
            activity_name,
            RETRY_OPTIONS,
            {"run_id": payload["run_id"]},
        )
        return {"function_name": activity_name, **result}

    except Exception as exc:
        return {
            "function_name": activity_name,
            "status": "Failed",
            "error_message": str(exc),
        }


@bp.orchestration_trigger(context_name="context")
def etl_orchestrator(context: df.DurableOrchestrationContext):
    run_id = context.instance_id

    if not context.is_replaying:
        logging.info("ETL run %s started.", run_id)

    # =========================================================
    # Run all ingestion activities in parallel (each with retries)
    # =========================================================
    outcomes = yield context.task_all([
        context.call_sub_orchestrator(
            "ingest_file_orchestrator",
            {"run_id": run_id, "activity_name": activity_name},
        )
        for activity_name in INGESTION_ACTIVITIES
    ])

    # =========================================================
    # The orchestrator decides the final run status
    # =========================================================
    failed = [o for o in outcomes if o["status"] != "Succeeded"]
    final_status = "Failed" if failed else "Succeeded"
    error = "; ".join(
        f"{o['function_name']}: {o.get('error_message')}" for o in failed
    )

    if not context.is_replaying:
        logging.info("ETL run %s finished with status %s.", run_id, final_status)

    # Close out any audit rows still left as "Running".
    try:
        yield context.call_activity_with_retry(
            "finalize_run_activity",
            RETRY_OPTIONS,
            {"run_id": run_id, "status": final_status, "outcomes": outcomes},
        )
    except Exception as exc:
        if not context.is_replaying:
            logging.error("Run finalization failed for %s: %s", run_id, exc)

    # Notification must never change the run's outcome.
    try:
        yield context.call_activity(
            "email_activity",
            {
                "status": final_status,
                "completed_results": outcomes,
                "error": error,
            },
        )
    except Exception as exc:
        if not context.is_replaying:
            logging.error("Email notification failed for %s: %s", run_id, exc)

    # Make the orchestration instance itself show as Failed (alertable).
    if failed:
        raise RuntimeError(f"ETL run {run_id} failed: {error}")

    return {"run_id": run_id, "status": final_status, "outcomes": outcomes}
