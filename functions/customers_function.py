import logging
import csv
import io
import time
from datetime import datetime, timezone

import azure.durable_functions as df

from services.github_service import download_csv
from services.sql_service import insert_csv
from services.audit_service import update_audit
from services.logging_service import insert_execution_log
from shared.config import setting

bp = df.Blueprint()


@bp.activity_trigger(input_name="payload")
def customers_activity(payload: dict) -> dict:

    csv_path = setting(
        "CUSTOMERS_CSV_PATH",
        "olist_customers_dataset.csv"
    )

    table_name = setting(
        "CUSTOMERS_SQL_TABLE",
        "dbo.customers"
    )

    run_id = payload["run_id"]
    logging.info("RunID received by customers_activity: %r", run_id)


    start_timestamp = datetime.now(timezone.utc)
    start_time = time.perf_counter()

    rows_read = 0
    inserted = 0
    error_message = None
    status = "Failed"

    audit_started = False

    # Extract schema and table name
    target_schema, target_table = table_name.split(".", 1)

    # 1. Start audit
    try:
        update_audit({
            "action": "start",
            "run_id": run_id,
            "function_name": "customers_activity",
            "source_type": "GitHub",
            "file_name": csv_path,
            "start_time": start_timestamp.isoformat()
        })

        audit_started = True

    except Exception:
        logging.exception("Failed to create customers audit record.")

    try:
        logging.info(
            "Starting customers ingestion from GitHub path: %s",
            csv_path
        )

        # 2. Download CSV
        csv_content = download_csv(csv_path)

        # 3. Count CSV rows
        reader = csv.reader(
            io.StringIO(csv_content.decode("utf-8-sig"))
        )

        next(reader, None)

        rows_read = sum(1 for row in reader if row)

        # 4. Insert into Azure SQL
        inserted = insert_csv(csv_content, table_name)

        status = "Succeeded"

        logging.info(
            "Customers ingestion completed. Rows inserted: %s",
            inserted
        )

    except Exception as exc:

        error_message = str(exc)

        logging.exception("Customers ingestion failed.")

    finally:

        end_timestamp = datetime.now(timezone.utc)
        duration = time.perf_counter() - start_time

        # 5. Update audit record
        if audit_started:
            try:
                update_audit({
                    "action": "finish",
                    "run_id": run_id,
                    "end_time": end_timestamp.isoformat(),
                    "duration_seconds": int(duration),
                    "status": status,
                    "error_message": error_message
                })

            except Exception:
                logging.exception("Failed to update customers audit record.")

        # 6. Insert dataset execution log
        try:
            insert_execution_log({
                "run_id": run_id,
                "function_name": "customers_activity",
                "entity_name": "customers",
                "source_type": "GitHub",
                "source_file_name": csv_path,
                "target_schema": target_schema,
                "target_table": target_table,
                "start_timestamp": start_timestamp.isoformat(),
                "end_timestamp": end_timestamp.isoformat(),
                "duration": duration,
                "rows_read": rows_read,
                "rows_written": inserted,
                "status": status,
                "error_message": error_message
            })

        except Exception:
            logging.exception("Failed to insert customers execution log.")

    return {
        "dataset": "customers",
        "source": csv_path,
        "destination": table_name,
        "rows_read": rows_read,
        "rows_written": inserted,
        "start_timestamp": start_timestamp.isoformat(),
        "end_timestamp": end_timestamp.isoformat(),
        "duration": duration,
        "status": status,
        "error_message": error_message
    }
