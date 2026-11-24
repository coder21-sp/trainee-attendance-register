from django.contrib.auth import get_user_model
from django.db import connection
from django.test import TestCase
from django.test.utils import CaptureQueriesContext
from django.urls import reverse
from django.utils import timezone

from .models import Approval, Attendance, Batch, Session, Trainee


def build_register(trainee_count, session_count, *, approval_count=0, pending_count=0):
    users = get_user_model().objects
    coordinator = users.create(username="query-coordinator", is_superuser=True)
    trainer = users.create(username="query-trainer")
    trainee_account = users.create(username="query-trainee")
    batch = Batch.objects.create(name="Synthetic query batch")
    trainees = Trainee.objects.bulk_create([
        Trainee(
            batch=batch, name=f"Trainee {index:03d}", code=f"Q-{index:03d}",
            account=trainee_account if index == 0 else None,
        )
        for index in range(trainee_count)
    ])
    sessions = Session.objects.bulk_create([
        Session(
            batch=batch, trainer=trainer, title=f"Session {index:03d}",
            date=timezone.localdate(), closed=index < session_count - pending_count,
        )
        for index in range(session_count)
    ])
    Attendance.objects.bulk_create([
        Attendance(trainee=trainee, session=session)
        for trainee_index, trainee in enumerate(trainees)
        for session_index, session in enumerate(sessions)
        if (trainee_index + session_index) % 4 != 0
    ])
    for trainee in trainees[:approval_count]:
        Approval.objects.create(
            trainee=trainee, reviewer=coordinator, total=session_count,
            attended=Attendance.objects.filter(trainee=trainee).count(),
            threshold=batch.minimum_percent, approval_method="standard", snapshot_origin="original",
        )
    return coordinator, trainee_account, batch


class RegisterQueryTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.coordinator, cls.trainee_account, cls.batch = build_register(
            12, 12, approval_count=6,
        )

    def get_with_queries(self, name, *args):
        with CaptureQueriesContext(connection) as queries:
            response = self.client.get(reverse(name, args=args))
        self.assertEqual(response.status_code, 200)
        return response, [query["sql"] for query in queries]

    def test_review_query_count_is_bounded_with_many_approved_trainees(self):
        self.client.force_login(self.coordinator)
        response, queries = self.get_with_queries("review", self.batch.pk)
        self.assertLessEqual(len(queries), 9)
        rows = response.context["rows"]
        self.assertEqual(len(rows), 12)
        for _, summary in rows:
            self.assertEqual(summary, {"total": 12, "pending": 0, "attended": 9, "eligible": True})

    def test_home_query_count_is_bounded_with_many_sessions(self):
        self.client.force_login(self.coordinator)
        response, queries = self.get_with_queries("home")
        self.assertLessEqual(len(queries), 8)
        self.assertContains(response, "query-trainer", count=12)

    def test_private_feed_only_reads_attendance_for_the_signed_in_trainee(self):
        self.client.force_login(self.trainee_account)
        response, queries = self.get_with_queries("my-data")
        sql = next(sql for sql in queries if 'FROM "training_attendance"' in sql)
        self.assertRegex(sql.split("WHERE", 1)[1], r'"training_attendance"\."trainee_id" = \d+')
        self.assertLessEqual(len(queries), 6)
        data = response.json()
        self.assertEqual(len(data["rows"]), 1)
        self.assertEqual(data["rows"][0]["marked"], 9)
        self.assertEqual(data["rows"][0]["status"], "Approved")
        self.assertEqual(data["sessions"][0]["status"], "Absent")
        self.assertEqual(data["sessions"][1]["status"], "Present")
        self.assertTrue(all(session.get("closed") for session in data["sessions"]))

    def test_coordinator_feed_groups_session_and_trainee_counts_in_one_statement(self):
        self.client.force_login(self.coordinator)
        response, queries = self.get_with_queries("batch-data", self.batch.pk)
        attendance_queries = [sql for sql in queries if '"training_attendance"' in sql]
        self.assertEqual(len(attendance_queries), 1)
        self.assertEqual(attendance_queries[0].count("GROUP BY"), 2)
        self.assertLessEqual(len(queries), 8)
        data = response.json()
        self.assertEqual([session["count"] for session in data["sessions"]], [9] * 12)
        self.assertEqual([row["marked"] for row in data["rows"]], [9] * 12)
        self.assertEqual([row["status"] for row in data["rows"]], ["Approved"] * 6 + ["Eligible"] * 6)


class PrivateFeedPendingTests(TestCase):
    def test_marked_open_session_retains_pending_register_state(self):
        _, account, _ = build_register(6, 4, pending_count=1)
        self.client.force_login(account)
        data = self.client.get(reverse("my-data")).json()
        self.assertEqual(data["sessions"][-1], {
            "title": "Session 003", "status": "Present", "closed": False,
        })
        self.assertEqual(data["rows"][0]["attended"], 2)
        self.assertEqual(data["rows"][0]["marked"], 3)
        self.assertEqual(data["rows"][0]["status"], "Pending registers")
