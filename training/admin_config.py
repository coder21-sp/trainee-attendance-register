from django.contrib.admin.apps import AdminConfig


class ThrottledAdminConfig(AdminConfig):
    default_site = "training.login_throttle.ThrottledAdminSite"
