# Security policy

issue-to-repro executes code from the repositories it analyses, and reads issue text written by
anyone. Problems in either area (sandbox escapes, path traversal, prompt injection that leads
to unintended actions, leaked credentials) are security issues.

## Reporting

Please report vulnerabilities privately through
[GitHub security advisories](https://github.com/learn-dumboo24/issue-to-repro/security/advisories/new),
not as public issues. You can expect an acknowledgement within a few days.

## Current limitations

Until the Docker / Cloud Run job sandbox lands, reproductions run the target repository's
tests directly on the host. Only use the tool on repositories you trust.
