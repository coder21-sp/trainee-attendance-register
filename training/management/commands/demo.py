import secrets
from datetime import timedelta
from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand, CommandError
from training.recovery import recovery_requires_review
from django.db import transaction
from django.utils import timezone
from training.models import Attendance, Batch, Trainee, Session


class Command(BaseCommand):
    help = "Seed fictional trainees. Prints passwords only for new demo accounts."

    @transaction.atomic
    def handle(self, *args, **kwargs):
        if recovery_requires_review():
            raise CommandError("Reconciliation required before seeding demo data.")
        def account(username, coordinator=False):
            user, created = get_user_model().objects.get_or_create(username=username)
            if created:
                password = secrets.token_urlsafe(16)
                user.set_password(password)
                user.is_superuser = user.is_staff = coordinator
                user.save()
                self.stdout.write(f"{username}   {password}")
            return user

        account("demo-coordinator", True)
        trainer = account("demo-trainer")
        today = timezone.localdate()
        batch, created = Batch.objects.get_or_create(name="Industrial IT · completed demo")
        if created:
            roster = []
            for code, name, login in [
                ("T-101", "Ananya Das", "demo-regular"),
                ("T-102", "Ravi Sen", "demo-partial"),
                ("T-103", "Meera Roy", "demo-final-day"),
            ]:
                roster.append(Trainee.objects.create(batch=batch,code=code,name=name,account=account(login)))
            for i,title in enumerate(["Safety induction","Support desk","Asset tracking","ERP orientation"]):
                session = Session.objects.create(batch=batch,trainer=trainer,title=title,date=today-timedelta(days=4-i),closed=True)
                for trainee,present in zip(roster,[True,i<2,i==3]):
                    if present:
                        Attendance.objects.create(session=session,trainee=trainee)
        practice, created = Batch.objects.get_or_create(name="Industrial IT · live practice")
        if created:
            Trainee.objects.create(batch=practice,name="Dev Rao",code="P-101",account=account("demo-live"))
            Session.objects.create(batch=practice,trainer=trainer,title="Practice workshop",date=today)

        # Attribute two existing fictional marks without changing demo eligibility.
        from training.models import AuditEntry
        for code, title, reason, note in [
            ("T-101", "Safety induction", "QR Camera Issue", "Badge checked at the induction desk."),
            ("T-102", "Support desk", "Network Error", "Confirmed against the trainer's paper register."),
        ]:
            mark = Attendance.objects.filter(trainee__batch=batch, trainee__code=code,
                                             session__title=title).select_related("trainee","session").first()
            if mark:
                AuditEntry.objects.get_or_create(seed_key=f"demo-manual-{code}", defaults={
                    "timestamp":mark.recorded_at, "trainee_name":str(mark.trainee),
                    "context":f"{batch} · {mark.session} · Manual present mark",
                    "actor":f"{trainer.username} (Trainer)", "reason":reason, "note":note,
                })
