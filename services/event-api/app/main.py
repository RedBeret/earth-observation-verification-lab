"""Environmental event API entrypoint."""

from terrawatch.api import create_app

app = create_app("event-api", ("postgres", "nats"))
