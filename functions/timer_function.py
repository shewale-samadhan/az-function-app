import logging
import os
import azure.functions as func
import azure.durable_functions as df

bp = df.Blueprint()

# Azure Functions timer schedules use NCRONTAB and are interpreted in UTC
# unless the hosting platform explicitly supports/configures another timezone.
ETL_CRON = os.getenv("ETL_CRON", "0 0 2 * * *")  # Default: daily at 02:00 UTC


@bp.timer_trigger(
    schedule=ETL_CRON,
    arg_name="timer",
    run_on_startup=False,
    use_monitor=True,
)
@bp.durable_client_input(client_name="client")
async def start_etl(timer, client: df.DurableOrchestrationClient):
    """Start the ETL orchestration on the configured timer schedule."""
    instance_id = await client.start_new(
        "etl_orchestrator",
        None,
        {},
    )
    logging.info("Started ETL orchestration. Instance ID: %s", instance_id)

@bp.route(route="start-etl", methods=["POST"])
@bp.durable_client_input(client_name="client")
async def start_etl_manually(
    req: func.HttpRequest,
    client: df.DurableOrchestrationClient
):
    instance_id = await client.start_new(
        "etl_orchestrator",
        None,
        {}
    )

    return client.create_check_status_response(
        req,
        instance_id
    )