from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from .models import Approval, Attendance, AuditEntry, Batch, Session, Trainee


class WorkflowRenderingTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        users = get_user_model().objects
        cls.coordinator = users.create_user("ux-coordinator", is_superuser=True)
        cls.owner = users.create_user("ux-trainee")
        cls.batch = Batch.objects.create(name="Workplace induction", minimum_percent=75)
        cls.trainee = Trainee.objects.create(
            account=cls.owner, batch=cls.batch, name="Private learner", code="UX-1",
        )
        cls.session = Session.objects.create(
            batch=cls.batch, trainer=cls.coordinator, date=timezone.localdate(), title="Safety introduction",
        )
        Attendance.objects.create(trainee=cls.trainee, session=cls.session)

    def approve_certificate(self):
        Session.objects.filter(pk=self.session.pk).update(closed=True)
        return Approval.objects.create(
            trainee=self.trainee, reviewer=self.coordinator, attended=1, total=1, threshold=75,
        )

    def test_private_progress_has_totals_and_session_status_without_javascript(self):
        self.client.force_login(self.owner)
        response = self.client.get(reverse("progress"))
        self.assertContains(response, "0 of 1 sessions confirmed")
        self.assertContains(response, "1 register still open")
        self.assertContains(response, "Safety introduction")
        self.assertContains(response, "Present")

    def test_approved_trainee_can_find_certificate_without_javascript(self):
        approval = self.approve_certificate()
        self.client.force_login(self.owner)
        response = self.client.get(reverse("progress"))
        link = reverse("certificate", args=[self.trainee.pk])
        self.assertContains(response, f'<a id="download" href="{link}">Download my certificate (PDF)</a>', html=True)
        self.assertContains(response, approval.certificate_reference)

    def test_quarantined_trainee_progress_explains_that_totals_are_under_review(self):
        self.approve_certificate()
        AuditEntry.objects.create(reason="Recovery required")
        self.client.force_login(self.owner)

        response = self.client.get(reverse("progress"))
        self.assertContains(response, "Attendance totals are under review.")
        self.assertNotContains(response, reverse("certificate", args=[self.trainee.pk]))

    def test_quarantined_register_omits_write_controls(self):
        AuditEntry.objects.create(reason="Recovery required")
        self.client.force_login(self.coordinator)

        response = self.client.get(reverse("register", args=[self.session.pk]))
        self.assertContains(response, "Reconciliation required")
        self.assertNotContains(response, "Mark present")
        self.assertNotContains(response, "Close register")
        self.assertNotContains(response, "Correct attendance")

    def test_quarantined_review_omits_approval_or_download_actions(self):
        Trainee.objects.create(batch=self.batch, name="Other trainee", code="OTHER-1")
        self.approve_certificate()
        AuditEntry.objects.create(reason="Recovery required")
        self.client.force_login(self.coordinator)

        response = self.client.get(reverse("review", args=[self.batch.pk]))
        self.assertContains(response, "Reconciliation required")
        self.assertNotContains(response, "Download certificate")
        self.assertNotContains(response, "Override and approve")

    def test_coordinator_review_has_search_and_status_filters(self):
        self.client.force_login(self.coordinator)
        response = self.client.get(reverse("review", args=[self.batch.pk]))
        self.assertContains(response, '<label for="review-search">Find a trainee</label>', html=True)
        self.assertContains(response, '<option value="pending">Awaiting registers</option>', html=True)
        self.assertContains(response, 'data-review-status="pending"')
