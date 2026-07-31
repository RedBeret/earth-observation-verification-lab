# Security Policy

## Supported versions

The current `main` branch is the only supported development version.

## Reporting

Do not open a public issue containing a credential, private key, personal information,
or exploitable detail. Use GitHub's private security advisory workflow for the
repository after publication.

## Project controls

- Local credentials are generated, stored in ignored files, and never embedded in
  commands or evidence.
- Published ports bind to loopback.
- Destructive commands verify the Docker Compose project identity.
- Evidence, logs, and diagnostics pass through credential-pattern redaction.
- Dependencies, container configuration, repository content, and pipeline definitions
  are checked by the security test level.

## Scanner exceptions

The repository secret scanner reports the file, the line number, and the rule. It never
repeats the matched value. It has exactly two documented exceptions, and both are
covered by their own tests.

1. **Non-secret local defaults.** `terrawatch` and `local-placeholder` are permitted as
   credential values in checked-in defaults. They are always overridden by the generated
   `.env.local` and by the Compose environment, so they are never reachable in a running
   environment. Any other credential-shaped value is a finding.
2. **Synthetic redaction fixtures.** A file under `tests/` may declare
   `# secret-scan: synthetic-fixture` in its first twelve lines. The pragma is ignored
   everywhere else in the repository, so shipped code cannot silence the scanner.

An optional `private-prohibited-terms.txt` may add locally sensitive terms. That file is
ignored by Git and its contents are never published.

This lab is not a production deployment and does not provide a production security
guarantee.
