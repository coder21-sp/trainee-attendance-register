from django.contrib.auth import get_user_model
from django.test import TestCase
from django.utils import timezone
from .models import Approval, Attendance, Batch, Correction, Session, Trainee


class RegisterFlow(TestCase):
    def test_register_to_review(self):
        users = get_user_model().objects
        trainer = users.create(username="trainer")
        coordinator = users.create(username="coordinator", is_superuser=True)
        batch = Batch.objects.create(name="Demo")
        trainee = Trainee.objects.create(batch=batch, name="Alex", code="T101")
        absent = Trainee.objects.create(batch=batch, name="Sam", code="T102")
        session = Session.objects.create(batch=batch, title="Workshop", trainer=trainer, date=timezone.localdate())
        route = f"/sessions/{session.pk}/"
        review = f"/review/{batch.pk}/"
        confirm = f"/approve/{trainee.pk}/"
        self.client.force_login(coordinator)
        self.assertContains(self.client.get(review), "Awaiting registers")
        self.assertContains(self.client.get(f"/badge/{trainee.pk}/"), "svg")
        self.client.post(confirm)
        self.assertFalse(Approval.objects.exists())
        self.client.force_login(users.create(username="other-trainer"))
        self.assertEqual(self.client.post(route, {"code": trainee.code}).status_code, 404)
        self.client.force_login(trainer)
        self.assertContains(self.client.get(route), "Mark present")
        for code in [trainee.code, str(trainee.badge)]:
            self.client.post(route, {"code":code})
        self.assertEqual(Attendance.objects.count(), 1)
        self.client.post(route, {"action":"close"})
        self.client.post(route, {"code":absent.code})
        self.assertFalse(Attendance.objects.filter(trainee=absent).exists())
        for status in ["present","absent"]:
            self.client.post(route, {"action":"correct","code":absent.code,"status":status,"reason":"Roster checked"})
        self.assertEqual(Correction.objects.count(), 2)
        self.client.post(confirm)
        self.assertFalse(Approval.objects.exists())
        self.client.force_login(coordinator)
        self.assertContains(self.client.get(review), "Below threshold")
        self.client.post(f"/approve/{absent.pk}/")
        self.assertFalse(Approval.objects.exists())
        self.client.post(confirm)
        self.assertEqual(Approval.objects.get().attended, 1)

    def test_trainee_private_progress_and_certificate(self):
        from django.core.management import call_command
        from io import StringIO
        call_command("demo",stdout=StringIO())
        users = get_user_model().objects
        regular = Trainee.objects.get(code="T-101")
        url = f"/certificate/{regular.pk}.pdf"
        self.client.force_login(regular.account)
        self.assertRedirects(self.client.get("/"), "/me/")
        self.assertEqual(self.client.get("/api/me/").json()["rows"][0]["status"], "Eligible")
        self.assertEqual(self.client.get(url).status_code,404)
        self.assertEqual(self.client.get(f"/api/batches/{regular.batch_id}/").status_code,403)
        self.client.force_login(users.get(username="demo-coordinator"))
        self.client.post(f"/approve/{regular.pk}/")
        self.client.force_login(regular.account)
        self.assertTrue(self.client.get(url).content.startswith(b"%PDF"))
        self.client.force_login(users.get(username="demo-partial"))
        self.assertEqual(self.client.get(url).status_code,403)
        self.assertEqual(self.client.get("/api/me/").json()["rows"][0]["status"], "Below threshold")
        live = Trainee.objects.get(code="P-101")
        session = Session.objects.get(batch=live.batch)
        self.client.force_login(session.trainer)
        self.client.post(f"/sessions/{session.pk}/", {"code":str(live.badge)})
        self.client.force_login(live.account)
        self.assertEqual(self.client.get("/api/me/").json()["sessions"][0]["status"],"Present")
        self.assertEqual(self.client.get("/api/me/").json()["rows"][0]["status"],"Pending registers")
