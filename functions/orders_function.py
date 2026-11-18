# import logging
# import time 
# import azure.durable_functions as df

# from services.github_service import download_csv
# from services.sql_service import insert_csv
# from shared.config import setting

# bp = df.Blueprint()


# @bp.activity_trigger(input_name="payload")
# def orders_activity(payload: dict) -> dict:
#     csv_path = setting("ORDERS_CSV_PATH", "olist_orders_dataset.csv")
#     table_name = setting("ORDERS_SQL_TABLE", "dbo.orders")
    
#     logging.info("Starting orders ingestion from GitHub path: %s", csv_path)
#     csv_content = download_csv(csv_path)
#     inserted = insert_csv(csv_content, table_name)

#     result = {
#         "dataset": "orders",
#         "source": csv_path,
#         "destination": table_name,
#         "rows_inserted": inserted,
#     }
#     logging.info("Orders ingestion completed: %s", result)
#     return result
# ================================================================================


import csv
import io
import logging
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
def orders_activity(payload: dict) -> dict:

    run_id = payload["run_id"]

    csv_path = setting("ORDERS_CSV_PATH", "olist_orders_dataset.csv")
    table_name = setting("ORDERS_SQL_TABLE", "dbo.orders")

    target_database = setting("SQL_DATABASE")
    target_schema, target_table = table_name.split(".", 1)

    function_name = "orders_activity"
    start_timestamp = datetime.now(timezone.utc)
    start_time = start_timestamp.isoformat()
    execution_start = time.time()

    rows_read = 0
    rows_written = 0
    status = "Failed"
    error_message = None
    audit_started = False

    logging.info("Starting orders ingestion. RunID: %s", run_id)

    # 1. Start audit record
    try:
        update_audit({
            "action": "start",
            "run_id": run_id,
            "function_name": function_name,
            "source_type": "GitHub",
            "file_name": csv_path,
            "start_time": start_time
        })
        audit_started = True

    except Exception:
        logging.exception("Failed to create orders audit start record")

    try:
        # 2. Download CSV from GitHub
        logging.info("Downloading orders CSV: %s", csv_path)
        csv_content = download_csv(csv_path)

        # 3. Count CSV rows
        reader = csv.reader(
            io.StringIO(csv_content.decode("utf-8-sig"))
        )
                
        next(reader, None)
                
        rows_read = sum(1 for row in reader if row)

        # 4. Insert data into SQL
        rows_written = insert_csv(csv_content, table_name)

        status = "Succeeded"

        logging.info(
            "Orders ingestion completed. Rows read: %s, Rows written: %s",
            rows_read,
            rows_written
        )

    except Exception as exc:
        error_message = str(exc)
        logging.exception("Orders ingestion failed")

    finally:
        end_timestamp = datetime.now(timezone.utc)
        end_time = end_timestamp.isoformat()
        duration = round(time.time() - execution_start, 2)

        # 5. Finish audit record
        if audit_started:
            try:
                update_audit({
                    "action": "finish",
                    "run_id": run_id,
                    "end_time": end_time,
                    "duration": duration,
                    "status": status,
                    "error_message": error_message
                })
            except Exception:
                logging.exception("Failed to update orders audit record")

        # 6. Insert execution log
        try:
            insert_execution_log({
                "run_id": run_id,
                "function_name": function_name,
                "entity_name": "orders",
                "source_type": "GitHub",
                "source_file_name": csv_path,
                "target_database": target_database,
                "target_schema": target_schema,
                "target_table": target_table,
                "start_timestamp": start_time,
                "end_timestamp": end_time,
                "duration": duration,
                "rows_read": rows_read,
                "rows_written": rows_written,
                "status": status,
                "error_message": error_message
            })
        except Exception:
            logging.exception("Failed to insert orders execution log")

    return {
        "dataset": "orders",
        "source": csv_path,
        "destination": table_name,
        "rows_read": rows_read,
        "rows_written": rows_written,
        "start_timestamp": start_time,
        "end_timestamp": end_time,
        "duration": duration,
        "status": status,
        "error_message": error_message
    }
