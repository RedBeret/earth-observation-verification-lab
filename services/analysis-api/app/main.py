"""Analysis API entrypoint."""

from terrawatch.analysis import register_analysis_routes
from terrawatch.api import create_app

app = create_app("analysis-api", ("postgres",))
register_analysis_routes(app)
