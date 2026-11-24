# Trainee Attendance Register implementation roadmap

## Baseline

- The feature checkout initially pointed to `268f66f`. Its isolated Django suite ran 54 tests with nine recovery failures.
- The feature branch was fast-forwarded to upstream `e34056a`, which includes `671d553` and a web recovery review. System checks and migration drift checks passed. All 55 tests passed in 8.042 seconds.

## Milestones

- [ ] Phase 1. Replace attestation-only unlock with a comparison against independently held SQLite evidence. Verify migration, restore, database write protection, and concurrent workflows.
- [ ] Phase 2. Verify the authorization matrix and implement least privilege, login protection, deployment settings, and privacy controls. Run a dependency audit.
- [ ] Phase 3. Add CI, regression coverage, and browser validation.
- [ ] Phase 4. Improve coordinator, trainer, and trainee workflows and certificates. Verify desktop, mobile, and keyboard behavior.
- [ ] Phase 5. Measure load, optimize bottlenecks, evaluate database options, and verify health checks and backup procedures.

## Recovery evidence contract

An operator selects an intact SQLite snapshot held independently of the restored candidate. Compare operational rows, identity mappings, and the prior audit history in a single recovery transaction. A mismatch leaves the database quarantined. Prepare a fresh candidate from the authoritative source if discrepancies cannot be resolved. Record the authorized reviewer, a review note, and evidence and marker digests in a new append-only event.

The attestation regression failed on the upstream redirect and passed after the review page became read-only. The independent comparison then passed 13 focused recovery tests and the 57-test suite in 7.645 seconds at `ccbbf02`, with clean system, migration drift, and diff checks. The host operator's access and separate evidence custody establish provenance.

Migration 0009 uses the same pending-recovery view for application status and SQLite write guards. The guards cover batch, trainee, session, attendance, approval, and correction inserts, updates, and deletes. The database file and audit writers remain trusted. Six file-backed concurrency tests verify duplicate scans and approvals, closure versus scanning, correction versus approval, threshold changes versus approval, and quarantine versus scanning. The combined recovery and concurrency run passed 21 tests in 0.661 seconds.
