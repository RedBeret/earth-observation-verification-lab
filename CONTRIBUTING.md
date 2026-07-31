# Contributing

Contributions must preserve the synthetic, public-safe boundary and the single
repository entrypoint.

1. Create or update a requirement and its verification mapping when behavior changes.
2. Add tests that include at least one relevant error path.
3. Run `./scripts/terra.sh validate` and the affected test levels.
4. Do not add real credentials, coordinates, internal domains, private datasets, or
   unverifiable operational claims.
5. Record user-visible changes in `CHANGELOG.md`.

Generated evidence and local credentials must not be committed.
