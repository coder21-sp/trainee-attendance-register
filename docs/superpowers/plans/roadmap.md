# Trainee Attendance Register implementation roadmap

## Baseline

- The feature checkout initially pointed to `268f66f`. Its isolated Django suite ran 54 tests with nine recovery failures.
- The feature branch was fast-forwarded to upstream `e34056a`, which includes `671d553` and a web recovery review. System checks and migration drift checks passed. All 55 tests passed in 8.042 seconds.

## Milestones

- [x] Phase 1. Verified independent reconciliation, migrated restore and database write protection, and six concurrent workflows. Commits `ccbbf02` and `7d2e5c1` are on the feature branch.
- [x] Phase 2. Verified least-privilege coordinator permissions, shared application/admin login throttling, production HTTPS defaults, and private response caching.
- [ ] Phase 3. GitHub Actions on Python 3.12 and 3.13 is verified. Browser verification is tracked below.
- [x] Phase 4. Shipped server-rendered trainee progress, coordinator review controls and search, responsive trainer flows, and a certificate layout update in `f8861d3`.
- [x] Phase 5. Measured and optimized the main endpoints, added polling backoff, verified health and backups, and documented SQLite operating limits and the PostgreSQL migration conditions.

## Recovery evidence contract

An operator selects an intact SQLite snapshot held independently of the restored candidate. Compare operational rows, identity mappings, and the prior audit history in a single recovery transaction. A mismatch leaves the database quarantined. Prepare a fresh candidate from the authoritative source if discrepancies cannot be resolved. Record the authorized reviewer, a review note, and evidence and marker digests in a new append-only event.

The attestation regression failed on the upstream redirect and passed after the review page became read-only. The independent comparison then passed 13 focused recovery tests and the 57-test suite in 7.645 seconds at `ccbbf02`, with clean system, migration drift, and diff checks. The host operator's access and separate evidence custody establish provenance.

Migration 0009 uses the same pending-recovery view for application status and SQLite write guards. The guards cover batch, trainee, session, attendance, approval, and correction inserts, updates, and deletes. The database file and audit writers remain trusted. Six file-backed concurrency tests verify duplicate scans and approvals, closure versus scanning, correction versus approval, threshold changes versus approval, and quarantine versus scanning. The combined recovery and concurrency run passed 21 tests in 0.661 seconds.

A fresh migrated SQLite database completed the restore and reconciliation drill with a synthetic operator. The full Phase 1 regression run passed 65 tests in 7.416 seconds before the final schema comparison tightening. The tightened comparison passed the 21 focused recovery and concurrency tests, including missing schema trigger rejection.

## Security verification

- The coordinator, login and HTTP security tests passed after their expected RED failures. The integrated suite passed 84 tests. The production deploy check reported W005 and W021 for the staged HSTS subdomain and preload policy.
- `pip-audit 2.10.1` reported no known vulnerabilities in the eight pinned Python packages on 24 November 2026. The scan scope was the pinned Python requirements. The bundled jsQR file was outside that scan.
- The setup administrator and host operator remain trusted. Login throttling does not track a username globally across distributed sources. Under reverse proxies, address isolation relies on the trusted server supplying the client address.

## Quality, workflows, and operations

- Phase 2 commit `fe7bfd9` is on the feature branch. Regression CI was added in `df010ec`; its first submission failed workflow validation. The corrected `f63415c` run succeeded on GitHub Actions (run 45357721413) after local actionlint verification.
- The exact staged Phase 4 snapshot passed all 91 Django tests in 8.538 seconds. Certificate reference and historical snapshot fields are retained. Dates display in the register timezone.
- The same-template synthetic benchmark reduced coordinator review from 395 to seven SQL queries and from 187.78 ms to 23.90 ms median. Visible-tab polling drops from 30 to 12 scheduled requests per minute. The README records the other endpoints and measurement conditions.
- A synthetic file-backed drill applied migrations through 0011, created a verified backup, restored to a separate file, and reconciled against the independent backup. The backup command rejects unrelated SQLite files. Readiness returns a generic 503 for quarantine or unavailable required database state. Production load testing and PostgreSQL compatibility remain outside the verified evidence.
