import azure.functions as func
import azure.durable_functions as df

from functions.timer_function import bp as timer_bp
from functions.orchestrator_function import bp as orchestrator_bp
from functions.orders_function import bp as orders_bp
from functions.customers_function import bp as customers_bp
from functions.products_function import bp as products_bp
from functions.audit_function import bp as audit_bp
from functions.email_function import bp as email_bp

app = df.DFApp(http_auth_level=func.AuthLevel.FUNCTION)

# Register every modular Durable Functions blueprint.
for blueprint in (
    timer_bp,
    orchestrator_bp,
    orders_bp,
    customers_bp,
    products_bp,
    audit_bp,
    email_bp,
):
    app.register_functions(blueprint)
