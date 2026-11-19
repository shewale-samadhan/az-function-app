import azure.functions as func
import msal
import requests
import os
import json
import logging
import hashlib
import time

from azure.identity import DefaultAzureCredential
from azure.storage.blob import BlobServiceClient
from azure.core.exceptions import ResourceExistsError, ResourceNotFoundError


app = func.FunctionApp()

# --------------------------------------------------
# CONFIGURATION
# --------------------------------------------------

AUTHORITY = os.getenv(
    "AUTHORITY",
    "https://login.microsoftonline.com/consumers"
)

GRAPH_SCOPES = ["Mail.Send"]

CLIENT_ID = os.getenv("CLIENT_ID")
CLIENT_SECRET = os.getenv("CLIENT_SECRET")
REDIRECT_URI = os.getenv("REDIRECT_URI")

TOKEN_CONTAINER = os.getenv(
    "TOKEN_CONTAINER",
    "msal-token-cache"
)

FLOW_EXPIRY_SECONDS = 600


# --------------------------------------------------
# CUSTOM EXCEPTIONS
# --------------------------------------------------

class LoginRequiredError(Exception):
    pass


# --------------------------------------------------
# AZURE BLOB STORAGE
# Used for durable MSAL cache and OAuth flow storage
# --------------------------------------------------

def get_blob_container():

    connection_string = os.getenv(
        "TOKEN_STORAGE_CONNECTION_STRING"
    )

    if connection_string:
        # Local development: use Azurite or a storage connection string.
        blob_service = BlobServiceClient.from_connection_string(
            connection_string
        )
    else:
        # Azure production: use the Function App managed identity.
        storage_url = os.getenv("AZURE_STORAGE_ACCOUNT_URL")

        if not storage_url:
            raise RuntimeError(
                "Set AZURE_STORAGE_ACCOUNT_URL or "
                "TOKEN_STORAGE_CONNECTION_STRING."
            )

        credential = DefaultAzureCredential()

        blob_service = BlobServiceClient(
            account_url=storage_url,
            credential=credential
        )

    container = blob_service.get_container_client(TOKEN_CONTAINER)

    try:
        container.create_container()
    except ResourceExistsError:
        pass

    return container


def save_blob(blob_name, content):

    container = get_blob_container()

    container.get_blob_client(blob_name).upload_blob(
        content.encode("utf-8"),
        overwrite=True
    )


def read_blob(blob_name):

    container = get_blob_container()

    try:
        blob = container.get_blob_client(blob_name)
        return blob.download_blob().readall().decode("utf-8")

    except ResourceNotFoundError:
        return None


def delete_blob(blob_name):

    container = get_blob_container()

    try:
        container.get_blob_client(blob_name).delete_blob()
    except ResourceNotFoundError:
        pass


# --------------------------------------------------
# MSAL CLIENT AND TOKEN CACHE
# --------------------------------------------------

def validate_auth_settings():

    required_settings = {
        "CLIENT_ID": CLIENT_ID,
        "CLIENT_SECRET": CLIENT_SECRET,
        "REDIRECT_URI": REDIRECT_URI
    }

    missing = [
        key for key, value in required_settings.items()
        if not value
    ]

    if missing:
        raise RuntimeError(
            "Missing application settings: " + ", ".join(missing)
        )


def load_token_cache():

    cache = msal.SerializableTokenCache()

    serialized_cache = read_blob("msal-cache.json")

    if serialized_cache:
        cache.deserialize(serialized_cache)

    return cache


def save_token_cache(cache):

    if cache.has_state_changed:
        save_blob(
            "msal-cache.json",
            cache.serialize()
        )


def create_msal_client(cache):

    validate_auth_settings()

    return msal.ConfidentialClientApplication(
        client_id=CLIENT_ID,
        authority=AUTHORITY,
        client_credential=CLIENT_SECRET,
        token_cache=cache
    )


# --------------------------------------------------
# 1. START MICROSOFT LOGIN
# URL: GET /api/auth/start?code=FUNCTION_KEY
# --------------------------------------------------

@app.route(
    route="auth/start",
    methods=["GET"],
    auth_level=func.AuthLevel.FUNCTION
)
def auth_start(req: func.HttpRequest) -> func.HttpResponse:

    try:
        validate_auth_settings()

        cache = load_token_cache()
        client = create_msal_client(cache)

        flow = client.initiate_auth_code_flow(
            scopes=GRAPH_SCOPES,
            redirect_uri=REDIRECT_URI
        )

        if "error" in flow:
            logging.error(
                "Could not start authentication: %s",
                flow.get("error")
            )

            return func.HttpResponse(
                "Unable to start Microsoft authentication.",
                status_code=500
            )

        state = flow.get("state")

        if not state:
            return func.HttpResponse(
                "Authentication state was not generated.",
                status_code=500
            )

        # Store the flow server-side. Do not keep it in a global variable.
        flow_document = {
            "flow": flow,
            "created_at": time.time()
        }

        flow_key = hashlib.sha256(
            state.encode("utf-8")
        ).hexdigest()

        save_blob(
            f"flows/{flow_key}.json",
            json.dumps(flow_document)
        )

        return func.HttpResponse(
            status_code=302,
            headers={
                "Location": flow["auth_uri"],
                "Cache-Control": "no-store"
            }
        )

    except Exception:
        logging.exception("Could not start Microsoft login.")

        return func.HttpResponse(
            "Authentication initialization failed. "
            "Check Function App logs.",
            status_code=500
        )


# --------------------------------------------------
# 2. MICROSOFT LOGIN CALLBACK
# URL: GET /api/auth/callback
# --------------------------------------------------

@app.route(
    route="auth/callback",
    methods=["GET"],
    auth_level=func.AuthLevel.ANONYMOUS
)
def auth_callback(req: func.HttpRequest) -> func.HttpResponse:

    state = req.params.get("state")

    if not state:
        return func.HttpResponse(
            "Missing authentication state.",
            status_code=400
        )

    flow_key = hashlib.sha256(
        state.encode("utf-8")
    ).hexdigest()

    blob_name = f"flows/{flow_key}.json"

    try:
        stored_flow = read_blob(blob_name)

        if not stored_flow:
            return func.HttpResponse(
                "Authentication session not found or already used. "
                "Start the login process again.",
                status_code=400
            )

        flow_document = json.loads(stored_flow)

        # Reject old or expired login flows.
        if time.time() - flow_document["created_at"] > FLOW_EXPIRY_SECONDS:
            return func.HttpResponse(
                "Authentication session expired. Start login again.",
                status_code=400
            )

        flow = flow_document["flow"]

        cache = load_token_cache()
        client = create_msal_client(cache)

        # MSAL validates the state returned by Microsoft.
        auth_result = client.acquire_token_by_auth_code_flow(
            flow,
            dict(req.params)
        )

        if "access_token" not in auth_result:

            logging.error(
                "Authentication failed: %s - %s",
                auth_result.get("error"),
                auth_result.get("error_description")
            )

            return func.HttpResponse(
                "Microsoft login failed. Check Function App logs.",
                status_code=401
            )

        # Persist access and refresh tokens securely in the cache.
        save_token_cache(cache)

        logging.info("Microsoft Outlook authentication successful.")

        return func.HttpResponse(
            "Microsoft Outlook authentication successful. "
            "You can now use the send-email endpoint.",
            status_code=200
        )

    except ValueError:
        logging.exception("Invalid OAuth callback or state.")

        return func.HttpResponse(
            "Invalid authentication response. Start login again.",
            status_code=400
        )

    except Exception:
        logging.exception("Microsoft authentication callback failed.")

        return func.HttpResponse(
            "Authentication callback failed. Check Function App logs.",
            status_code=500
        )

    finally:
        # A callback flow is single-use.
        try:
            delete_blob(blob_name)
        except Exception:
            logging.exception("Could not delete authentication flow.")


# --------------------------------------------------
# 3. GET ACCESS TOKEN SILENTLY
# --------------------------------------------------

def get_access_token():

    cache = load_token_cache()
    client = create_msal_client(cache)

    accounts = client.get_accounts()

    if not accounts:
        raise LoginRequiredError(
            "No Outlook account is authenticated. "
            "Visit the auth/start endpoint first."
        )

    if len(accounts) > 1:
        raise RuntimeError(
            "This implementation supports one Outlook account only. "
            "The token cache contains multiple accounts."
        )

    result = client.acquire_token_silent(
        scopes=GRAPH_SCOPES,
        account=accounts[0]
    )

    if not result or "access_token" not in result:

        logging.warning(
            "Silent token acquisition failed: %s",
            result.get("error") if result else "No cached token"
        )

        raise LoginRequiredError(
            "Microsoft login or consent is required again."
        )

    save_token_cache(cache)

    return result["access_token"]


# --------------------------------------------------
# 4. SEND EMAIL USING MICROSOFT GRAPH
# --------------------------------------------------

def send_graph_email(recipients, subject, body):

    if isinstance(recipients, str):
        recipients = [recipients]

    if not isinstance(recipients, list):
        raise ValueError(
            "Recipients must be an email address or a list of addresses."
        )

    recipients = [
        email.strip()
        for email in recipients
        if isinstance(email, str) and email.strip()
    ]

    if not recipients:
        raise ValueError(
            "At least one receiver email address is required."
        )

    access_token = get_access_token()

    email_payload = {
        "message": {
            "subject": subject,
            "body": {
                "contentType": "Text",
                "content": body
            },
            "toRecipients": [
                {
                    "emailAddress": {
                        "address": email
                    }
                }
                for email in recipients
            ]
        },
        "saveToSentItems": True
    }

    graph_url = (
        "https://graph.microsoft.com/v1.0/me/sendMail"
    )

    headers = {
        "Authorization": f"Bearer {access_token}",
        "Content-Type": "application/json"
    }

    response = requests.post(
        graph_url,
        headers=headers,
        json=email_payload,
        timeout=30
    )

    if response.status_code != 202:

        logging.error(
            "Graph sendMail failed. HTTP %s: %s",
            response.status_code,
            response.text
        )

        raise RuntimeError(
            f"Microsoft Graph sendMail failed: HTTP "
            f"{response.status_code}"
        )

    logging.info(
        "Email accepted by Microsoft Graph for %d recipient(s).",
        len(recipients)
    )

    return response.status_code


# --------------------------------------------------
# 5. HTTP EMAIL ENDPOINT
# URL: POST /api/send-email
# --------------------------------------------------

@app.route(
    route="send-email",
    methods=["POST"],
    auth_level=func.AuthLevel.FUNCTION
)
def send_email(req: func.HttpRequest) -> func.HttpResponse:

    try:
        data = req.get_json()

        recipients = (
            data.get("to")
            or os.getenv("RECEIVER_EMAIL")
        )

        subject = data.get("subject")
        body = data.get("body")

        if not recipients or not subject or not body:

            return func.HttpResponse(
                "Required fields: to, subject, body.",
                status_code=400
            )

        if not isinstance(subject, str) or not isinstance(body, str):

            return func.HttpResponse(
                "Subject and body must be strings.",
                status_code=400
            )

        send_graph_email(
            recipients=recipients,
            subject=subject,
            body=body
        )

        return func.HttpResponse(
            json.dumps({
                "status": "success",
                "message": "Email accepted by Microsoft Graph.",
                "to": recipients
            }),
            status_code=200,
            mimetype="application/json"
        )

    except LoginRequiredError as e:

        return func.HttpResponse(
            str(e),
            status_code=401
        )

    except ValueError as e:

        return func.HttpResponse(
            str(e),
            status_code=400
        )

    except Exception:

        logging.exception("Email sending failed.")

        return func.HttpResponse(
            "Email sending failed. Check Function App logs.",
            status_code=500
        )

# --------------------------------------------------
# 6. AUTOMATIC EMAIL TRIGGER
# --------------------------------------------------

@app.timer_trigger(
    schedule="0 */2 * * * *",
    arg_name="mytimer",
    run_on_startup=False,
    use_monitor=True
)
def automatic_email_trigger(mytimer: func.TimerRequest):

    logging.info("Automatic email trigger started.")

    try:
        receiver = os.getenv("RECEIVER_EMAIL")

        if not receiver:
            raise ValueError(
                "RECEIVER_EMAIL is not configured."
            )

        # Existing function retrieves the saved OAuth token.
        # It does not start another Microsoft login.
        send_graph_email(
            recipients=receiver,
            subject="Azure Function Deployment Test",
            body=(
                "Hello!\n\n"
                "Your Azure Function App is running successfully.\n"
                "Microsoft Graph email integration is working."
            )
        )

        logging.info(
            "Automatic email sent successfully to %s",
            receiver
        )

    except LoginRequiredError:
        logging.exception(
            "Microsoft authentication is required. "
            "Complete the initial OAuth login."
        )
        raise

    except Exception:
        logging.exception(
            "Automatic email execution failed."
        )
        raise


# import logging

# import azure.durable_functions as df

# bp = df.Blueprint()


# @bp.activity_trigger(input_name="email_payload")
# def email_activity(email_payload: dict) -> dict:
#     """
#     DEMO ONLY:
#     Logs the notification that would be sent.
#     Later, integrate an email provider (for example, Azure Communication
#     Services or Microsoft Graph) and send the actual message here.
#     """
#     status = email_payload.get("status", "Unknown")
#     logging.info(
#         "DEMO EMAIL: ETL workflow status=%s; details=%s",
#         status,
#         email_payload,
#     )
#     return {"email_simulated": True, "status": status}
