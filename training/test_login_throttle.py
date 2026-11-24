from datetime import timedelta
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.test import Client, TestCase, override_settings
from django.urls import reverse
from django.utils import timezone


@override_settings(PASSWORD_HASHERS=["django.contrib.auth.hashers.MD5PasswordHasher"])
class LoginThrottleTests(TestCase):
    def setUp(self):
        self.password = "generated-test-phrase-38"
        get_user_model().objects.create_user(
            "staff-test", password=self.password, is_staff=True,
        )
        self.login_url = reverse("login")
        self.admin_url = reverse("admin:login")

    def login(self, username="staff-test", password="wrong", *, url=None, **headers):
        return self.client.post(
            url or self.login_url, {"username": username, "password": password}, **headers,
        )

    def test_failed_attempts_lock_both_login_entry_points(self):
        for index in range(5):
            url = self.login_url if index % 2 else self.admin_url
            self.assertEqual(self.login(url=url).status_code, 200)
        for url in (self.login_url, self.admin_url):
            response = self.login(password=self.password, url=url)
            self.assertEqual(response.status_code, 429)
            self.assertGreater(int(response.headers["Retry-After"]), 0)
            self.assertNotContains(response, "staff-test", status_code=429)
        self.assertNotIn("_auth_user_id", self.client.session)

    def test_unknown_username_has_the_same_throttle_response(self):
        responses = []
        for username in ("staff-test", "nonexistent"):
            for _ in range(5):
                self.assertEqual(self.login(username=username).status_code, 200)
            responses.append(self.login(username=username))
        self.assertEqual([response.status_code for response in responses], [429, 429])
        self.assertEqual(responses[0].content, responses[1].content)

    def test_account_and_address_buckets_are_isolated(self):
        get_user_model().objects.create_user("other-user", password=self.password)
        for attempt in range(5):
            self.assertEqual(
                self.login(HTTP_X_FORWARDED_FOR=f"192.0.2.{attempt + 1}").status_code, 200,
            )
        self.assertEqual(self.login(HTTP_X_FORWARDED_FOR="192.0.2.99").status_code, 429)
        self.assertEqual(self.login(username="other-user", password=self.password).status_code, 302)
        self.client = Client()
        self.assertEqual(self.login(password=self.password, REMOTE_ADDR="192.0.2.99").status_code, 302)

    def test_address_limit_applies_when_usernames_change(self):
        for attempt in range(30):
            self.assertEqual(self.login(username=f"random-{attempt}").status_code, 200)
        self.assertEqual(self.login(password=self.password).status_code, 429)

    def test_successful_login_resets_the_account_bucket(self):
        for _ in range(4):
            self.assertEqual(self.login().status_code, 200)
        self.assertEqual(self.login(password=self.password).status_code, 302)
        self.client = Client()
        for _ in range(5):
            self.assertEqual(self.login().status_code, 200)
        self.assertEqual(self.login().status_code, 429)

    def test_attempts_are_allowed_after_the_window_expires(self):
        for _ in range(5):
            self.assertEqual(self.login().status_code, 200)
        self.assertEqual(self.login().status_code, 429)
        later = timezone.now() + timedelta(minutes=16)
        with patch("django.utils.timezone.now", return_value=later):
            self.assertEqual(self.login(password=self.password).status_code, 302)

    def test_csrf_failure_does_not_consume_an_attempt(self):
        self.client = Client(enforce_csrf_checks=True)
        for _ in range(5):
            self.assertEqual(self.login().status_code, 403)
            self.assertEqual(self.login(url=self.admin_url).status_code, 403)
        self.client = Client()
        self.assertEqual(self.login(password=self.password).status_code, 302)
