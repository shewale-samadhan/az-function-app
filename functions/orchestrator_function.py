import azure.durable_functions as df
from datetime import timedelta
import logging
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

        # =======================================================================
        # =======================================================================

        yield context.call_activity("orders_activity", {"run_id": context.instance_id} )


        # =======================================================================
        # =======================================================================

        yield context.call_activity( "customers_activity", {"run_id": context.instance_id } )
        
        
        # =======================================================================
        # =======================================================================

        yield context.call_activity( "products_activity", {"run_id": context.instance_id } )

        success = {
                    "status": "success",
                    "completed_results": results,
                    "error": "",
                }
        
        yield context.call_activity("email_activity", success)

    except Exception as exc:
        # Activity failures are captured here so audit/notification activities
        # still get a chance to run. The orchestration is then marked failed.
        failure = {
            "status": "Failed",
            "completed_results": results,
            "error": str(exc),
        }

        yield context.call_activity("email_activity", failure)
        raise
