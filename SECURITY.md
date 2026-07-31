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

This lab is not a production deployment and does not provide a production security
guarantee.
