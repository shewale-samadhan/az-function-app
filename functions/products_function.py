import logging

import azure.durable_functions as df

from services.github_service import download_csv
from services.sql_service import insert_csv
from shared.config import setting

bp = df.Blueprint()


@bp.activity_trigger(input_name="payload")
def products_activity(payload: dict) -> dict:
    csv_path = setting("PRODUCTS_CSV_PATH", "olist_products_dataset.csv")
    table_name = setting("PRODUCTS_SQL_TABLE", "dbo.products")

    logging.info("Starting products ingestion from GitHub path: %s", csv_path)
    csv_content = download_csv(csv_path)
    inserted = insert_csv(csv_content, table_name)

    result = {
        "dataset": "products",
        "source": csv_path,
        "destination": table_name,
        "rows_inserted": inserted,
    }
    logging.info("Products ingestion completed: %s", result)
    return result
