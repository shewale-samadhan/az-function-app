import logging

import azure.durable_functions as df

from services.github_service import download_csv
from services.sql_service import insert_csv
from shared.config import setting

bp = df.Blueprint()


@bp.activity_trigger(input_name="payload")
def orders_activity(payload: dict) -> dict:
    csv_path = setting("ORDERS_CSV_PATH", "olist_orders_dataset.csv")
    table_name = setting("ORDERS_SQL_TABLE", "dbo.order_items")
    logging.info("============================================================================")
    logging.info("============================================================================")

    logging.info("Starting orders ingestion from GitHub path: %s", csv_path)
    csv_content = download_csv(csv_path)
    inserted = insert_csv(csv_content, table_name)

    result = {
        "dataset": "orders",
        "source": csv_path,
        "destination": table_name,
        "rows_inserted": inserted,
    }
    logging.info("Orders ingestion completed: %s", result)
    return result
