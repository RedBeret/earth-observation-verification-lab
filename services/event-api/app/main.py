"""Environmental event API entrypoint."""

from terrawatch.api import create_app
from terrawatch.events import register_event_routes

app = create_app("event-api", ("postgres", "nats"))
register_event_routes(app)
