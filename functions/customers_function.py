import logging

import azure.durable_functions as df

from services.github_service import download_csv
from services.sql_service import insert_csv
from shared.config import setting

bp = df.Blueprint()


@bp.activity_trigger(input_name="payload")
def customers_activity(payload: dict) -> dict:
    csv_path = setting("CUSTOMERS_CSV_PATH", "olist_customers_dataset.csv")
    table_name = setting("CUSTOMERS_SQL_TABLE", "dbo.customers")

    logging.info("Starting customers ingestion from GitHub path: %s", csv_path)
    csv_content = download_csv(csv_path)
    inserted = insert_csv(csv_content, table_name)

    result = {
        "dataset": "customers",
        "source": csv_path,
        "destination": table_name,
        "rows_inserted": inserted,
    }
    logging.info("Customers ingestion completed: %s", result)
    return result
