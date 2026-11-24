# Trainee Attendance & Certificate Review

A coordinator can see which training sessions a trainee attended before approving a certificate. Trainers take attendance on a phone. Trainees sign in to see their own progress and download an approved PDF. This independent prototype was inspired by industrial vocational training. All demo people, sessions and passes are fictional.

## Architecture

```mermaid
flowchart LR
  C[Coordinator PC] -->|Setup, batch feed, approval| D[Django application]
  T[Trainer phone] -->|Authenticated QR or manual mark| D
  U[Trainee phone or PC] -->|Private progress and PDF| D
  D --> S[(Shared SQLite database)]
```

The phone and desktop use the same server URL. Each trainer mark commits to a single register. Open coordinator review and trainee progress pages poll their authorized JSON feeds every two seconds. QR decoding runs locally on the phone with bundled jsQR. A badge identifies a trainee and an authenticated trainer confirms presence.

## Start locally

Requires Python 3.11+ and a modern browser.

    python -m venv .venv
    source .venv/bin/activate
    pip install -r requirements.txt
    python manage.py migrate
    python manage.py demo
    python manage.py runserver

Open **http://127.0.0.1:8000/**. On Windows use `.venv\Scripts\activate`. The demo command prints a generated password alongside each new username. Save these locally. Running it again preserves existing records and passwords. Reset a forgotten password with `python manage.py changepassword USERNAME`.

## Demo accounts

| Username | View | Initial evidence |
|---|---|---|
| demo-coordinator | Setup, printable passes, live review and approval | Both batches |
| demo-trainer | Mobile register | Assigned sessions |
| demo-regular | Private trainee page | 4/4, eligible for review |
| demo-partial | Private trainee page | 2/4, below threshold |
| demo-final-day | Private trainee page | 1/4, attended only the last session |
| demo-live | Private trainee page | P-101 in the separate open practice session |

## Walk through the system

1. Sign in as coordinator. Open the completed batch. Approve the eligible trainee and download the certificate. Sign in as demo-regular in a separate browser profile to download the same PDF. A partial-attendance trainee can see their progress.
2. Open the live practice batch on the coordinator PC. Select **Print ID pass** for P-101. Print or display the QR and printed fallback ID.
3. In a separate browser session, sign in as demo-trainer and select **Practice workshop**. Scan the badge or type **P-101**. Try it twice. The unique session/trainee pair counts once. Check the open PC review and demo-live progress screens.
4. Close the register after checking the roster. Until closure, unmarked entries are pending. After closure, unmarked entries count as absent. A trainer can correct a mark with a recorded reason before approval.
5. The coordinator reviews eligibility and explicitly approves. The PDF records the attendance fraction at approval. The demo threshold is 75%; coordinators set the actual threshold per batch.

## Setting up your own batch

In **Manage batches, trainees and sessions**, create a batch, add trainees and assign each session a date and trainer. For a trainer, create an ordinary Django user and assign them to sessions. For a trainee, create a separate ordinary user and select it in their trainee record. Coordinator accounts are trusted system administrators. Only assigned trainers can record attendance, and a trainee login can access only its own progress and PDF.

## Connect a phone

On trusted Wi-Fi, set `ALLOWED_HOSTS=localhost,127.0.0.1,YOUR_PC_LAN_IP` and run `python manage.py runserver 0.0.0.0:8000`. Open the PC's LAN address on both devices. Manual entry works over LAN HTTP. For phone camera scanning, serve the app through HTTPS and allow camera access. Localhost is also a secure context for testing on one machine.

## API and storage

| Endpoint | Access and function |
|---|---|
| POST /api/sessions/{id}/attendance/ | Assigned trainer, form data with code and CSRF token, JSON response with Accept: application/json |
| GET /api/batches/{id}/ | Coordinator batch progress and session counts |
| GET /api/me/ | Signed-in trainee's own marks and eligibility |
| POST /approve/{trainee_id}/ | Coordinator approval, server checks threshold and pending registers |
| GET /certificate/{trainee_id}.pdf | Approved trainee or coordinator |

SQLite transactions serialize register writes and approval decisions. A database uniqueness constraint prevents duplicate marks. Approval stores the reviewer, timestamp, threshold and attendance counts. A batch should contain a fixed cohort and planned sessions before final review.

For hosting use a persistent volume for `DATABASE_PATH`, set `APP_ENV=production`, `SECRET_KEY` and `ALLOWED_HOSTS`, run migrations and `collectstatic`, serve static files and Gunicorn behind HTTPS. Back up the database. The development server is for local demos.

## Verification

    python manage.py test

Tests cover role boundaries, repeat scans, correction history, pending registers, attendance thresholds, private trainee feeds and certificate downloads. Camera decoding uses jsQR 1.4.0; its license is included under training/static/vendor.

## Manual attendance and audit review

For a typed trainee ID, select **QR Camera Issue**, **Medical Leave**, **Official Plant Duty**, **Network Error**, or **Roster Correction**. Add a note of up to 240 characters if needed. Camera scanning submits the badge UUID through the scan path; the printed trainee ID is accepted only through manual entry. Badge possession is not proof that a physical camera was used.

The assigned trainer or a coordinator can correct a register with a reason. Once every register is closed, a coordinator may expand **Below threshold · Review override**, document the exception and approve a certificate. The original attendance fraction stays on the certificate. Existing approvals lock subsequent corrections for that trainee.

Open **Audit Log** on the coordinator dashboard for timestamp (IST), trainee, session/action, staff username and role, reason and note. **Download Audit Log (CSV)** exports the full history in the same order, including records beyond the current page. Spreadsheet formula prefixes are escaped. Two fictional manual entries are included by the demo command; reruns preserve them. Existing correction history is imported by the migration.

Attendance changes, overrides and their audit inserts commit together. Historical entries store names, roles and session descriptions as snapshots. SQLite triggers block updates, deletes and replacement inserts, including ordinary direct SQL writes. A host administrator who can replace the database or drop triggers can still alter history. For independently verifiable retention, export to separately controlled immutable storage under the organization's retention policy.

After pulling this version run `python manage.py migrate` and, for demo installations, `python manage.py demo`.

### Detect a database rollback

Opening **Audit Log** saves a signed SHA-256 receipt on that coordinator's browser. On later visits, the app compares the entire previously witnessed prefix, including row IDs, UTC timestamps and snapshot fields. Additional rows are allowed. Missing or changed witnessed rows produce a warning and the browser retains its earlier receipt. Receipts contain a count and digest, without trainee names or notes.

Download the receipt after each review and retain the latest copy on an HR-controlled device. Upload it on the Audit Log page to verify history from another browser. Keep the production signing key stable and backed up separately. First use establishes a baseline. Changes made and lost between reviews are outside its coverage. Clearing browser storage removes its local baseline. A receipt detects differences and cannot recover missing data; maintain separately controlled backups for recovery. This check assumes trusted application code.

### Restore Monday's backup and keep Tuesday's audit entries

Stop application writers before the final recovery. Keep both the current SQLite database and a consistent SQLite backup from the same installation. Both must contain the audit table. From the project directory:

    python manage.py restore_with_audit backups/monday.sqlite3 recovered.sqlite3

The command copies Monday's database to a new file, verifies that its audit history matches the beginning of the current database's history, and appends every later audit row with its original ID, timestamp and staff attribution. The original files stay intact. A conflicting history or an existing output path stops the operation. To supply Tuesday's snapshot separately, add `--current backups/tuesday.sqlite3`.

Start the app with `DATABASE_PATH` set to the absolute path of the recovered file, using the original signing key. Run pending migrations on that file if needed. Audit Log, CSV export and previously saved receipts all use the combined history. Other tables, including attendance marks and certificate approvals, reflect the chosen backup. If you also need Tuesday's operational state, use the intact Tuesday database. A receipt alone cannot reconstruct missing rows.

After a restore, sign in as coordinator and select **Review this restore** in the warning banner. Compare operational attendance, closed registers and certificate approvals with independent records. If there are unresolved differences, keep the copy locked and recover the correct operational data before proceeding. Record what evidence you checked, explain why operations can resume, and confirm reconciliation. The decision is appended to the audit log and unlocks only this restore. Reviewing does not recreate missing attendance or certificates. Each subsequent restore requires its own review.
