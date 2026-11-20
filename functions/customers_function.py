import azure.durable_functions as df

from services.ingestion_service import Dataset, run_ingestion

bp = df.Blueprint()

CUSTOMERS = Dataset(
    entity="customers",
    function_name="customers_activity",
    csv_path_setting="CUSTOMERS_CSV_PATH",
    csv_path_default="olist_customers_dataset.csv",
    table_setting="CUSTOMERS_SQL_TABLE",
    table_default="dbo.customers",
)


@bp.activity_trigger(input_name="payload")
def customers_activity(payload: dict) -> dict:
    return run_ingestion(CUSTOMERS, payload["run_id"])
