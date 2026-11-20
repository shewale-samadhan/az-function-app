import azure.durable_functions as df

from services.ingestion_service import Dataset, run_ingestion

bp = df.Blueprint()

ORDERS = Dataset(
    entity="orders",
    function_name="orders_activity",
    csv_path_setting="ORDERS_CSV_PATH",
    csv_path_default="olist_orders_dataset.csv",
    table_setting="ORDERS_SQL_TABLE",
    table_default="dbo.orders",
)


@bp.activity_trigger(input_name="payload")
def orders_activity(payload: dict) -> dict:
    return run_ingestion(ORDERS, payload["run_id"])
