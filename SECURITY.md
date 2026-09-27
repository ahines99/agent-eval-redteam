# Security policy

This is a local-first portfolio implementation with synthetic fixtures. An implemented
control is not a security certification. Read the [threat model](docs/threat_model.md)
and [deployment guide](docs/deployment.md) before exposing the HTTP transport or introducing
real data. Stdio trusts the local process owner.

## Supported code

Security fixes target the current development version. No long-term support or backport
schedule is promised for historical versions. Check the published release/commit and its
validation record before relying on a result.

## Report a vulnerability privately

Use [GitHub private vulnerability reporting](https://github.com/ahines99/agent-eval-redteam/security/advisories/new)
for this repository. You may need to sign in to GitHub. Do not put credentials, personal
data, private traces or a sensitive exploit description in a public issue. If the private
form is unavailable, request a private route without disclosing sensitive details; do not
substitute a public exploit report. No response-time commitment is implied by this policy.

A useful private report includes:

- Affected commit/version and environment.
- Expected boundary and observed behavior.
- Minimal synthetic reproduction and relevant error or trace identifiers.
- Whether any real data or credentials may have been exposed; omit the secret values.
- Suggested mitigation, if known.

Use only systems and accounts you are authorized to test. Prefer the synthetic sandbox.
Avoid destructive operations, resource-exhaustion tests against shared services and tests
that send data to real recipients. A finding can be reported without demonstrating harm
against another person's system.

## If credentials or data may be exposed

Stop the affected shared service, revoke the relevant token or provider credential, and
preserve protected evidence for investigation. Do not commit a database or raw trace dump
as a bug reproduction. Operators own secret rotation, TLS, access controls, backups and
data-retention policy; the application does not implement those procedures for them.

Content hashes detect corruption but do not protect against a database writer who can
replace both content and hash. Scorer and PII checks are bounded heuristics; a clean suite
result is not proof that every attack or disclosure is prevented.
