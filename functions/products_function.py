import azure.durable_functions as df

from services.ingestion_service import Dataset, run_ingestion

bp = df.Blueprint()

PRODUCTS = Dataset(
    entity="products",
    function_name="products_activity",
    csv_path_setting="PRODUCTS_CSV_PATH",
    csv_path_default="olist_products_dataset.csv",
    table_setting="PRODUCTS_SQL_TABLE",
    table_default="dbo.products",
)


@bp.activity_trigger(input_name="payload")
def products_activity(payload: dict) -> dict:
    return run_ingestion(PRODUCTS, payload["run_id"])
