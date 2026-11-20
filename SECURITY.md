# Security policy

issue-to-repro executes code from the repositories it analyses, and reads issue text written by
anyone. Problems in either area (sandbox escapes, path traversal, prompt injection that leads
to unintended actions, leaked credentials) are security issues.

## Reporting

Please report vulnerabilities privately through
[GitHub security advisories](https://github.com/learn-dumboo24/issue-to-repro/security/advisories/new),
not as public issues. You can expect an acknowledgement within a few days.

## Isolation

With `SANDBOX=docker`, a reproduction runs in a container with no network, as `nobody` with all
capabilities dropped and `no-new-privileges`, on a read-only filesystem with read-only mounts,
under memory/CPU/process limits and a timeout. The checkout's dependencies are installed before
the container starts, by trusted code, so untrusted code never runs with network access.
`tests/test_docker_sandbox.py` verifies the network and filesystem restrictions with real
containers in CI.

## Current limitations

- `SANDBOX=local` (the default, for development) runs tests directly on the host. Use
  `SANDBOX=docker` for any repository you do not trust.
- Installing a checkout's dependencies runs its build backend (e.g. `setup.py`) on the host,
  with network access. Untrusted repositories should be prepared on a disposable machine
  (planned: Cloud Run jobs).
- Containers share the host kernel; a kernel exploit is out of scope.
