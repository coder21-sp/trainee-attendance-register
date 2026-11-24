import json

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group, Permission
from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from .models import Approval, Attendance, AuditEntry, Batch, Session, Trainee


class RolePermissionsTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        users = get_user_model().objects
        cls.coordinator = users.create_user("coordinator")
        cls.trainer = users.create_user("trainer")
        cls.other_trainer = users.create_user("other-trainer")
        cls.owner = users.create_user("trainee")
        cls.staff = users.create_user("staff", is_staff=True)
        batch = Batch.objects.create(name="Training cohort")
        cls.trainee = Trainee.objects.create(batch=batch, name="Private learner", code="PRIVATE", account=cls.owner)
        cls.session = Session.objects.create(batch=batch, title="Workshop", trainer=cls.trainer,
                                             date=timezone.localdate())
        cls.other_session = Session.objects.create(batch=Batch.objects.create(name="Other cohort"),
                                                   title="Other workshop", trainer=cls.other_trainer,
                                                   date=timezone.localdate())

    def grant_coordinator_permission(self):
        permission = Permission.objects.get(
            content_type__app_label="training", content_type__model="batch", codename="coordinate_register",
        )
        group = Group.objects.create(name="Register coordinators")
        group.permissions.add(permission)
        self.coordinator.groups.add(group)

    def test_coordinator_can_review_without_setup_or_user_admin_access(self):
        self.grant_coordinator_permission()
        self.client.force_login(self.coordinator)

        review_url = reverse("review", args=[self.trainee.batch_id])
        self.assertContains(self.client.get(review_url), self.trainee.name)
        self.assertContains(self.client.get(reverse("home")), review_url)
        for name, args in (("register", [self.session.pk]), ("batch-data", [self.trainee.batch_id]),
                           ("pass", [self.trainee.pk]), ("badge", [self.trainee.pk]),
                           ("audit", []), ("audit-csv", []), ("recovery-review", [])):
            with self.subTest(name=name):
                self.assertEqual(self.client.get(reverse(name, args=args)).status_code, 200)
        self.assertEqual(self.client.post(reverse("checkpoint")).status_code, 200)
        self.assertEqual(self.client.get(reverse("admin:auth_user_changelist")).status_code, 302)
        self.assertNotContains(self.client.get(reverse("home")), reverse("admin:index"))

    def test_coordinator_can_approve_and_is_attributed_in_the_audit(self):
        self.grant_coordinator_permission()
        self.client.force_login(self.coordinator)
        Attendance.objects.create(session=self.session, trainee=self.trainee)
        Session.objects.filter(pk=self.session.pk).update(closed=True)

        self.client.post(reverse("approve", args=[self.trainee.pk]))

        self.assertTrue(Approval.objects.filter(trainee=self.trainee, reviewer=self.coordinator).exists())
        payload = json.loads(AuditEntry.objects.get().context.split("\n", 1)[1])
        self.assertEqual(payload["actor_role"], "Coordinator")
        self.assertEqual(self.client.get(reverse("certificate", args=[self.trainee.pk])).status_code, 200)

    def test_reconciliation_accepts_coordinator_permission_and_rejects_staff_alone(self):
        self.grant_coordinator_permission()
        with self.assertRaisesMessage(CommandError, "No restore awaits review"):
            call_command("reconcile_recovery", "unused.sqlite3", actor=self.coordinator.username, note="Reviewed")
        with self.assertRaisesMessage(CommandError, "An active coordinator is required"):
            call_command("reconcile_recovery", "unused.sqlite3", actor=self.staff.username, note="Reviewed")

    def test_trainers_see_only_assigned_sessions_and_cannot_approve(self):
        self.client.force_login(self.trainer)
        self.assertEqual(self.client.get(reverse("register", args=[self.session.pk])).status_code, 200)
        self.assertEqual(self.client.get(reverse("register", args=[self.other_session.pk])).status_code, 404)
        self.assertEqual(self.client.post(reverse("approve", args=[self.trainee.pk])).status_code, 302)
        self.assertFalse(Approval.objects.exists())

    def test_trainee_can_view_own_progress_without_batch_access(self):
        self.client.force_login(self.owner)
        response = self.client.get(reverse("my-data"))
        self.assertEqual([row["id"] for row in response.json()["rows"]], [self.trainee.pk])
        self.assertEqual(self.client.get(reverse("batch-data", args=[self.trainee.batch_id])).status_code, 403)
        self.assertEqual(self.client.get(reverse("badge", args=[self.trainee.pk])).status_code, 302)
