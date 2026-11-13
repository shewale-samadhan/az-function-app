import azure.durable_functions as df

bp = df.Blueprint()


@bp.orchestration_trigger(context_name="context")
def etl_orchestrator(context: df.DurableOrchestrationContext):
    """
    Coordinates the ETL workflow.

    Keep orchestrator code deterministic: no network, SQL, Key Vault,
    filesystem, email, or direct logging calls here. Put I/O in activities.
    """
    results = []

    try:
        # Sequential ingestion: orders -> customers -> products.
        # results.append(
        #     (yield context.call_activity("orders_activity", {}))
        # )
        results.append(
            (yield context.call_activity("customers_activity", {}))
        )
        results.append(
            (yield context.call_activity("products_activity", {}))
        )

        summary = {
            "status": "Succeeded",
            "results": results,
        }

        yield context.call_activity("audit_activity", summary)
        yield context.call_activity("email_activity", summary)
        return summary

    except Exception as exc:
        # Activity failures are captured here so audit/notification activities
        # still get a chance to run. The orchestration is then marked failed.
        failure = {
            "status": "Failed",
            "completed_results": results,
            "error": str(exc),
        }

        yield context.call_activity("audit_activity", failure)
        yield context.call_activity("email_activity", failure)
        raise
