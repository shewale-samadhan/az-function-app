import logging

import azure.durable_functions as df

bp = df.Blueprint()


@bp.activity_trigger(input_name="email_payload")
def email_activity(email_payload: dict) -> dict:
    """
    DEMO ONLY:
    Logs the notification that would be sent.
    Later, integrate an email provider (for example, Azure Communication
    Services or Microsoft Graph) and send the actual message here.
    """
    status = email_payload.get("status", "Unknown")
    logging.info(
        "DEMO EMAIL: ETL workflow status=%s; details=%s",
        status,
        email_payload,
    )
    return {"email_simulated": True, "status": status}
