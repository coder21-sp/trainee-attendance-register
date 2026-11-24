from django.contrib.auth import get_user_model
from django.db import IntegrityError, transaction
from django.test import TestCase
from django.utils import timezone
from unittest.mock import patch

from .models import Approval, Attendance, Batch, Session, Trainee


class CertificateSnapshotTests(TestCase):
    def setUp(self):
        users = get_user_model().objects
        self.reviewer = users.create(username="original-reviewer", is_superuser=True)
        self.account = users.create(username="certificate-trainee")
        self.batch = Batch.objects.create(name="Original batch")
        self.trainee = Trainee.objects.create(
            batch=self.batch, account=self.account, name="Original trainee", code="CERT-1")
        self.session = Session.objects.create(
            batch=self.batch, title="Workshop", date=timezone.localdate(),
            trainer=self.reviewer, closed=True)
        Attendance.objects.create(trainee=self.trainee, session=self.session)
        self.client.force_login(self.reviewer)
        self.approve_url = f"/approve/{self.trainee.pk}/"
        self.pdf_url = f"/certificate/{self.trainee.pk}.pdf"
        self.client.post(self.approve_url)
        self.approval = Approval.objects.get(trainee=self.trainee)

    def certificate_text(self):
        # Disable PDF stream compression so that ASCII text can be checked
        # directly in the actual generated PDF without a new dependency.
        with patch("reportlab.rl_config.pageCompression", 0):
            response = self.client.get(self.pdf_url)
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.content.startswith(b"%PDF"))
        return response.content

    def test_trainee_rename_preserves_certificate(self):
        Trainee.objects.filter(pk=self.trainee.pk).update(name="Changed trainee")
        pdf = self.certificate_text()
        self.assertIn(b"Original trainee", pdf)
        self.assertNotIn(b"Changed trainee", pdf)

    def test_batch_rename_preserves_certificate(self):
        Batch.objects.filter(pk=self.batch.pk).update(name="Changed batch")
        pdf = self.certificate_text()
        self.assertIn(b"Original batch", pdf)
        self.assertNotIn(b"Changed batch", pdf)

    def test_reviewer_rename_preserves_certificate(self):
        get_user_model().objects.filter(pk=self.reviewer.pk).update(username="changed-reviewer")
        pdf = self.certificate_text()
        self.assertIn(b"original-reviewer", pdf)
        self.assertNotIn(b"changed-reviewer", pdf)

    def test_duplicate_approval_preserves_original_identity(self):
        Trainee.objects.filter(pk=self.trainee.pk).update(name="Changed trainee")
        self.client.post(self.approve_url)
        self.assertEqual(Approval.objects.filter(trainee=self.trainee).count(), 1)
        self.assertIn(b"Original trainee", self.certificate_text())

    def test_approval_counts_cannot_be_updated(self):
        with self.assertRaises(IntegrityError), transaction.atomic():
            Approval.objects.filter(pk=self.approval.pk).update(attended=0)

    def test_approval_cannot_be_deleted(self):
        with self.assertRaises(IntegrityError), transaction.atomic():
            Approval.objects.filter(pk=self.approval.pk).delete()

    def test_owner_can_download(self):
        self.client.force_login(self.account)
        self.assertIn(b"Original trainee", self.certificate_text())

    def test_unrelated_user_cannot_download(self):
        self.client.force_login(get_user_model().objects.create(username="unrelated"))
        self.assertEqual(self.client.get(self.pdf_url).status_code, 403)
