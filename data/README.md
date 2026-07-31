# Deterministic synthetic test data

All required data is produced by the scripts in `data/generators/` with seed `240729`.
No network access or external imagery is used.

Run:

```bash
./scripts/terra.sh seed
```

The generator creates:

- `valid/scene-wgs84.tif`: 64×64 EPSG:4326 raster with the known synthetic footprint
  `[-120.10, 37.10, -119.90, 37.30]`;
- `valid/scene-projected.tif`: 64×64 EPSG:3857 raster;
- `invalid/no-crs.tif`: a readable raster intentionally missing CRS metadata;
- `invalid/truncated-raster.tif`: a deterministic truncation of the valid WGS84 file;
- valid and invalid scene metadata;
- inside, outside, boundary, before, during, after, duplicate, and endpoint events; and
- expected STAC and correlation JSON.

The ISO timestamp in the raster `CAPTURE_TIME` tag is fixed at
`2026-07-29T18:30:00Z`. All geometry and coordinates are fictional test values.

Tests regenerate the entire set in two temporary directories, compare relative file
lists and SHA-256 digests, and compare calculated results with `expected/`.
