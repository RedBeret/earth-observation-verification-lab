"""Analysis API entrypoint."""

from terrawatch.api import create_app

app = create_app("analysis-api", ("postgres",))
