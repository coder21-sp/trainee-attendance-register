"""Run synthetic endpoint timings with manage.py test training.performance_benchmark."""
from statistics import median
from time import perf_counter

from django.db import connection
from django.test import TestCase
from django.test.utils import CaptureQueriesContext
from django.urls import reverse

from .test_performance import build_register


class RegisterBenchmark(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.coordinator, cls.trainee_account, cls.batch = build_register(
            120, 24, approval_count=30,
        )

    def test_synthetic_requests(self):
        endpoints = (
            ("home", (), self.coordinator),
            ("review", (self.batch.pk,), self.coordinator),
            ("batch-data", (self.batch.pk,), self.coordinator),
            ("my-data", (), self.trainee_account),
        )
        print("\nSynthetic workload: 120 trainees, 24 sessions, 2,160 marks, 30 approvals")
        for name, args, user in endpoints:
            self.client.force_login(user)
            path = reverse(name, args=args)
            with CaptureQueriesContext(connection) as queries:
                self.assertEqual(self.client.get(path).status_code, 200)
            query_count = len(queries)
            elapsed = []
            for _ in range(10):
                start = perf_counter()
                response = self.client.get(path)
                elapsed.append((perf_counter() - start) * 1000)
                self.assertEqual(response.status_code, 200)
            print(f"{name}: {query_count} SQL queries, median {median(elapsed):.2f} ms (10 requests)")
