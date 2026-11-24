import os
import runpy
from pathlib import Path
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.test import SimpleTestCase, TestCase
from django.urls import reverse

from .models import Batch, Trainee


class TransportSettingsTests(SimpleTestCase):
    def load_settings(self, **overrides):
        environment = {
            "APP_ENV": "production",
            "SECRET_KEY": "test-only-settings-key",
            "ALLOWED_HOSTS": "register.example.test",
            **overrides,
        }
        with patch.dict(os.environ, environment, clear=True):
            return runpy.run_path(str(Path(__file__).resolve().parents[1] / "config" / "settings.py"))

    def test_production_defaults_require_secure_transport(self):
        settings = self.load_settings()
        self.assertIs(settings.get("SECURE_SSL_REDIRECT"), True)
        self.assertTrue(settings["SESSION_COOKIE_SECURE"])
        self.assertTrue(settings["CSRF_COOKIE_SECURE"])
        self.assertIs(settings.get("CSRF_COOKIE_HTTPONLY"), True)
        self.assertEqual(settings.get("SECURE_HSTS_SECONDS"), 300)
        self.assertIs(settings.get("SECURE_HSTS_INCLUDE_SUBDOMAINS"), False)

    def test_development_can_use_local_http(self):
        settings = self.load_settings(APP_ENV="development", ALLOWED_HOSTS="")
        self.assertIs(settings.get("SECURE_SSL_REDIRECT"), False)
        self.assertFalse(settings["CSRF_COOKIE_SECURE"])
        self.assertEqual(settings.get("SECURE_HSTS_SECONDS"), 0)
        self.assertIn("127.0.0.1", settings["ALLOWED_HOSTS"])

    def test_production_requires_a_specific_host(self):
        for hosts in ("", "*", "register.example.test, *"):
            with self.subTest(hosts=hosts), self.assertRaisesRegex(ValueError, "ALLOWED_HOSTS"):
                self.load_settings(ALLOWED_HOSTS=hosts)

    def test_proxy_https_header_requires_opt_in(self):
        settings = self.load_settings(SECURITY_TRUST_PROXY_HTTPS="0")
        self.assertIsNone(settings.get("SECURE_PROXY_SSL_HEADER"))
        settings = self.load_settings(SECURITY_TRUST_PROXY_HTTPS="1")
        self.assertEqual(settings.get("SECURE_PROXY_SSL_HEADER"), ("HTTP_X_FORWARDED_PROTO", "https"))

    def test_hsts_scope_and_csrf_origins_are_explicit(self):
        settings = self.load_settings(
            SECURITY_HSTS_SECONDS="86400",
            SECURITY_HSTS_INCLUDE_SUBDOMAINS="1",
            CSRF_TRUSTED_ORIGINS=" https://register.example.test, https://portal.example.test ",
        )
        self.assertEqual(settings.get("SECURE_HSTS_SECONDS"), 86400)
        self.assertIs(settings.get("SECURE_HSTS_INCLUDE_SUBDOMAINS"), True)
        self.assertEqual(settings.get("CSRF_TRUSTED_ORIGINS"), [
            "https://register.example.test", "https://portal.example.test",
        ])

    def test_invalid_hsts_age_stops_startup(self):
        for seconds in ("-1", "disabled"):
            with self.subTest(seconds=seconds), self.assertRaisesRegex(ValueError, "SECURITY_HSTS_SECONDS"):
                self.load_settings(SECURITY_HSTS_SECONDS=seconds)


class PrivateResponseTests(TestCase):
    def test_trainee_progress_page_and_feed_are_private_and_uncacheable(self):
        user = get_user_model().objects.create_user(username="private-progress")
        batch = Batch.objects.create(name="Private response batch")
        Trainee.objects.create(batch=batch, account=user, name="Private trainee", code="PR-1")
        self.client.force_login(user)

        for route in ("progress", "my-data"):
            with self.subTest(route=route):
                response = self.client.get(reverse(route))
                self.assertEqual(response.status_code, 200)
                directives = {directive.strip() for directive in response.get("Cache-Control", "").split(",")}
                self.assertTrue({"no-store", "private"} <= directives, directives)
