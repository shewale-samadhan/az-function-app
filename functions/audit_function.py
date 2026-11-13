import logging

import azure.durable_functions as df

bp = df.Blueprint()


@bp.activity_trigger(input_name="audit_payload")
def audit_activity(audit_payload: dict) -> dict:
    """
    DEMO ONLY:
    Writes an audit summary to Application Insights / Function logs.
    Later, replace this with an INSERT into a dedicated SQL audit table.
    """
    logging.info("ETL AUDIT: %s", audit_payload)
    return {"audit_logged": True, "status": audit_payload.get("status")}
