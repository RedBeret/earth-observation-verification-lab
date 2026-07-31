# Data Provenance

All required test data originates from deterministic generators committed under
`data/generators/`.

The canonical data set contains:

- small synthetic GeoTIFF scenes in geographic and projected coordinate systems;
- intentionally invalid rasters for negative verification;
- synthetic telemetry located inside, outside, and on a known footprint boundary;
- timestamps before, inside, and after the correlation window; and
- generated expected STAC and correlation results.

The generators use a fixed seed. Tests regenerate inputs in a temporary directory and
compare their hashes and semantic results with the canonical committed examples.

No external imagery, live service, real sensor feed, or private dataset is required.
Optional public examples, if documented later, remain outside all automated tests.
