"""Run the Chromium workflow with manage.py test training.browser_checks."""
import json
import os
from pathlib import Path
import sqlite3
import subprocess
import sys
from contextlib import closing
from tempfile import TemporaryDirectory
from unittest import TestCase

from playwright.sync_api import expect, sync_playwright


PASSWORD = "Browser-fixture-password-only"


class RegisterBrowserTests(TestCase):
    @classmethod
    def setUpClass(cls):
        workspace = TemporaryDirectory()
        cls.addClassCleanup(workspace.cleanup)
        cls.database = Path(workspace.name) / "browser.sqlite3"
        process = subprocess.Popen(
            [sys.executable, "-m", "training.browser_checks"],
            stdout=subprocess.PIPE,
            text=True,
            encoding="utf-8",
            env={
                **os.environ,
                "APP_ENV": "development",
                "ALLOWED_HOSTS": "127.0.0.1",
                "DJANGO_SETTINGS_MODULE": "config.settings",
                "DATABASE_PATH": str(cls.database),
                "SECRET_KEY": "browser-synthetic-fixture-key-only",
                "PYTHONIOENCODING": "utf-8",
            },
        )
        cls.addClassCleanup(cls.stop_server, process)
        cls.base = f"http://127.0.0.1:{int(process.stdout.readline())}"
        playwright = sync_playwright().start()
        cls.addClassCleanup(playwright.stop)
        channel = os.environ.get("REGISTER_BROWSER_CHANNEL")
        cls.browser = playwright.chromium.launch(channel=channel)
        cls.addClassCleanup(cls.browser.close)

    @staticmethod
    def stop_server(process):
        process.terminate()
        try:
            process.wait(timeout=10)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(timeout=10)
        finally:
            process.stdout.close()

    def login(self, username, **settings):
        context = self.browser.new_context(**settings)
        self.addCleanup(context.close)
        page = context.new_page()
        page.goto(self.base + "/login/")
        page.get_by_label("Username").fill(username)
        page.get_by_label("Password").fill(PASSWORD)
        page.get_by_role("button", name="Sign in").click()
        expect(page.get_by_role("button", name="Sign out")).to_be_visible()
        return page

    def test_mobile_trainer_to_coordinator_and_private_certificate(self):
        trainer = self.login("browser-trainer", viewport={"width": 360, "height": 760}, is_mobile=True)
        trainer.add_init_script("""
            navigator.mediaDevices.getUserMedia = async () => {
                throw new DOMException('Permission denied', 'NotAllowedError');
            };
        """)
        trainer.goto(self.base + "/sessions/1/")
        self.assertTrue(trainer.evaluate("document.documentElement.scrollWidth <= innerWidth"))
        trainer.get_by_role("button", name="Scan QR badge").click()
        expect(trainer.locator("#camera")).to_have_text("Camera unavailable. Enter the printed ID.")

        form = trainer.locator("#entry")
        field = form.get_by_label("Trainee ID")
        field.fill("WEB-1")
        form.get_by_label("Reason").select_option("Network Error")
        trainer.route("**/api/sessions/1/attendance/", lambda route: route.abort())
        form.get_by_role("button", name="Mark present").click()
        expect(trainer.locator("#camera")).to_contain_text("Could not verify the mark")
        trainer.unroute("**/api/sessions/1/attendance/")
        field.press("Enter")
        expect(trainer.get_by_role("heading", name="Present (1)")).to_be_visible()
        expect(field).to_be_focused()
        field.fill("WEB-1")
        field.press("Enter")
        expect(trainer.locator("#camera")).to_contain_text("already")
        expect(trainer.get_by_role("heading", name="Present (1)")).to_be_visible()

        trainer.get_by_text("Correct attendance", exact=True).click()
        correction = trainer.locator("details")
        correction.get_by_label("Trainee ID").fill("WEB-1")
        correction.get_by_label("Status").select_option("absent")
        correction.get_by_label("Reason").select_option("Roster Correction")
        correction.get_by_role("button", name="Record correction").click()
        expect(trainer.get_by_role("heading", name="Present (0)")).to_be_visible()

        coordinator = self.login("browser-coordinator")
        badge = coordinator.request.get(self.base + "/badge/1/")
        self.assertEqual(badge.status, 200)
        trainer.evaluate("""svg => {
            navigator.mediaDevices.getUserMedia = async () => {
                const url = URL.createObjectURL(new Blob([svg], {type: 'image/svg+xml'}));
                const image = new Image();
                try {
                    image.src = url;
                    await image.decode();
                } finally {
                    URL.revokeObjectURL(url);
                }
                const canvas = document.createElement('canvas');
                canvas.width = canvas.height = 360;
                const context = canvas.getContext('2d');
                context.fillStyle = 'white';
                context.fillRect(0, 0, 360, 360);
                const stream = canvas.captureStream(30);
                const [track] = stream.getVideoTracks();
                function draw() {
                    if (track.readyState === 'ended') return;
                    context.drawImage(image, 30, 30, 300, 300);
                    requestAnimationFrame(draw);
                }
                draw();
                return stream;
            };
        }""", badge.text())
        scan = trainer.get_by_role("button", name="Scan QR badge")
        scan.click()
        expect(trainer.locator("#camera")).to_have_text("First trainee: present.")
        expect(trainer.get_by_role("heading", name="Present (1)")).to_be_visible()
        scan.click()
        expect(trainer.locator("#camera")).to_contain_text("already marked")
        expect(trainer.get_by_role("heading", name="Present (1)")).to_be_visible()
        with closing(sqlite3.connect(self.database)) as database:
            contexts = database.execute(
                "SELECT context FROM training_auditentry WHERE reason = ?",
                ("QR present mark",),
            ).fetchall()
        self.assertEqual(len(contexts), 1)
        event = json.loads(contexts[0][0].split("\n", 1)[1])
        self.assertEqual((event["action"], event["source"]), ("attendance_marked", "qr"))
        trainer.get_by_role("checkbox", name="I checked the roster", exact=False).check()
        trainer.get_by_role("button", name="Close register").click()
        expect(trainer.get_by_text("Register closed.", exact=True)).to_be_visible()

        coordinator.goto(self.base + "/review/1/")
        coordinator.get_by_label("Find a trainee").fill("WEB-1")
        expect(coordinator.get_by_text("Second trainee", exact=True)).to_be_hidden()
        coordinator.get_by_role("button", name="Approve certificate").click()
        expect(coordinator.get_by_role("link", name="Download certificate")).to_be_visible()

        trainee = self.login("browser-trainee", accept_downloads=True)
        trainee.goto(self.base + "/me/")
        expect(trainee.get_by_text("1 of 1 sessions confirmed")).to_be_visible()
        expect(trainee.get_by_text("Second trainee", exact=True)).to_have_count(0)
        self.assertEqual(trainee.request.get(self.base + "/api/batches/1/").status, 403)
        with trainee.expect_download() as result:
            trainee.get_by_role("link", name="Download my certificate (PDF)").click()
        self.assertTrue(result.value.path().read_bytes().startswith(b"%PDF"))
        with closing(sqlite3.connect(self.database)) as database, database:
            database.execute(
                """INSERT INTO training_auditentry (timestamp, trainee_name, context, actor, reason, note)
                   VALUES (CURRENT_TIMESTAMP, '', '', 'Browser fixture', 'Recovery required', '')"""
            )
        trainee.reload()
        expect(trainee.get_by_role("alert")).to_contain_text("Reconciliation required")
        expect(trainee.get_by_role("link", name="Download my certificate (PDF)")).to_have_count(0)


def serve_fixture():
    import django
    from django.contrib.auth import get_user_model
    from django.contrib.staticfiles.handlers import StaticFilesHandler
    from django.core.management import call_command
    from django.core.wsgi import get_wsgi_application
    from django.utils import timezone
    from wsgiref.simple_server import make_server

    django.setup()
    from .models import Batch, Session, Trainee

    call_command("migrate", verbosity=0, interactive=False)
    users = get_user_model().objects
    trainer = users.create_user("browser-trainer", password=PASSWORD)
    trainee = users.create_user("browser-trainee", password=PASSWORD)
    users.create_superuser("browser-coordinator", password=PASSWORD)
    batch = Batch.objects.create(name="Browser training")
    Session.objects.create(batch=batch, trainer=trainer, date=timezone.localdate(), title="Browser workshop")
    Trainee.objects.create(batch=batch, name="First trainee", code="WEB-1", account=trainee)
    Trainee.objects.create(batch=batch, name="Second trainee", code="WEB-2")

    with make_server("127.0.0.1", 0, StaticFilesHandler(get_wsgi_application())) as server:
        print(server.server_port, flush=True)
        server.serve_forever()


if __name__ == "__main__":
    serve_fixture()
