import logging
import os

import azure.durable_functions as df

bp = df.Blueprint()

ETL_ORCHESTRATOR = "etl_orchestrator"

# Azure Functions timer schedules use NCRONTAB and are interpreted in UTC
# unless the hosting platform explicitly supports/configures another timezone.
# Format: {second} {minute} {hour} {day} {month} {day-of-week}
# ETL_CRON = os.getenv("ETL_CRON", "0 0 20 * * *")  # Default: daily at 20:00 UTC
ETL_CRON = os.getenv("ETL_CRON", "0 */10 * * * *")  # Every 5 minutes (testing)


@bp.timer_trigger(
    schedule=ETL_CRON,
    arg_name="timer",
    run_on_startup=False,
    use_monitor=True,
)
@bp.durable_client_input(client_name="client")
async def start_etl(timer, client: df.DurableOrchestrationClient):
    """Start the ETL orchestration unless a previous run is still in progress."""

    if timer.past_due:
        logging.warning("ETL timer is running late.")

    # Overlap guard: skip this tick if an ETL run is still Running/Pending.
    active = await client.get_status_by(
        runtime_status=[
            df.OrchestrationRuntimeStatus.Running,
            df.OrchestrationRuntimeStatus.Pending,
        ]
    )
    overlapping = [s.instance_id for s in active if s.name == ETL_ORCHESTRATOR]

    if overlapping:
        logging.warning(
            "Skipping ETL start: previous run still active (instance(s): %s).",
            ", ".join(overlapping),
        )
        return

    instance_id = await client.start_new(
        ETL_ORCHESTRATOR,
        None,
        {},
    )
    logging.info("Started ETL orchestration. Instance ID: %s", instance_id)
