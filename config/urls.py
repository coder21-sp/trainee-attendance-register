from django.contrib import admin
from django.contrib.auth import views as auth
from django.urls import path
from training import views

from training.audit import audit_log
from training.recovery import review_recovery
from training.checkpoints import checkpoint
from training.login_throttle import throttle_login

urlpatterns = [
    path("recovery/review/", review_recovery, name="recovery-review"),
    path("audit/checkpoint/", checkpoint, name="checkpoint"),
    path("audit/", audit_log, name="audit"),
    path("audit/export.csv", audit_log, {"export":True}, name="audit-csv"),
    path('api/sessions/<int:pk>/attendance/', views.register, name='mark-api'),
    path('me/', views.progress, name='progress'),
    path('api/me/', views.live, name='my-data'),
    path('api/batches/<int:batch_id>/', views.live, name='batch-data'),
    path('passes/<int:pk>/', views.id_pass, name='pass'),
    path('certificate/<int:pk>.pdf', views.certificate, name='certificate'),
    path('', views.home, name='home'),
    path('login/', throttle_login(auth.LoginView.as_view(template_name='login.html')), name='login'),
    path('logout/', auth.LogoutView.as_view(), name='logout'),
    path('setup/', admin.site.urls),
    path('sessions/<int:pk>/', views.register, name='register'),
    path('review/<int:pk>/', views.review, name='review'),
    path('approve/<int:pk>/', views.approve, name='approve'),
    path('badge/<int:pk>/', views.badge, name='badge'),
]
