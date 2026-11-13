
import logging
import csv
import io
import time
from datetime import datetime, timezone

import azure.durable_functions as df

from services.github_service import download_csv
from services.sql_service import insert_csv
from shared.config import setting

bp = df.Blueprint()


@bp.activity_trigger(input_name="payload")
def customers_activity(payload: dict) -> dict:
    csv_path = setting("CUSTOMERS_CSV_PATH", "olist_customers_dataset.csv")
    table_name = setting("CUSTOMERS_SQL_TABLE", "dbo.customers")

    start_timestamp = datetime.now(timezone.utc)
    start_time = time.perf_counter()

    try:
        logging.info(
            "Starting customers ingestion from GitHub path: %s",
            csv_path
        )

        # Download CSV from GitHub
        csv_content = download_csv(csv_path)

        # Count data rows in GitHub CSV, excluding the header
        reader = csv.reader(
            io.StringIO(csv_content.decode("utf-8-sig"))
        )
        next(reader, None)  # Skip header
        rows_read = sum(1 for row in reader if row)

        # Insert CSV records into Azure SQL
        inserted = insert_csv(csv_content, table_name)

        end_timestamp = datetime.now(timezone.utc)
        duration = time.perf_counter() - start_time

        result = {
            "dataset": "customers",
            "source": csv_path,
            "destination": table_name,
            "rows_read": rows_read,
            "rows_written": inserted,
            "start_timestamp": start_timestamp.isoformat(),
            "end_timestamp": end_timestamp.isoformat(),
            "duration": duration,
            "status": "Success",
            "error_message": None,
        }

        logging.info("Customers ingestion completed: %s", result)
        return result

    except Exception as exc:
        end_timestamp = datetime.now(timezone.utc)
        duration = time.perf_counter() - start_time

        logging.exception("Customers ingestion failed.")

        return {
            "dataset": "customers",
            "source": csv_path,
            "destination": table_name,
            "rows_read": locals().get("rows_read"),
            "rows_written": 0,
            "start_timestamp": start_timestamp.isoformat(),
            "end_timestamp": end_timestamp.isoformat(),
            "duration": duration,
            "status": "Failed",
            "error_message": str(exc),
        }
