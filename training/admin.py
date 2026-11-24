from django.contrib import admin
from django import forms

from .integrity import is_batch_locked, validate_batch_mutation
from .models import Batch, Trainee, Session
from .recovery import recovery_requires_review


class BatchForm(forms.ModelForm):
    def clean(self):
        data = super().clean()
        if self.instance.pk and "minimum_percent" in self.changed_data:
            validate_batch_mutation(self.instance.pk)
        return data


class RosterForm(forms.ModelForm):
    def clean(self):
        data = super().clean()
        batch = data.get("batch")
        if not batch:
            return data
        if not self.instance.pk or "batch" in self.changed_data:
            if self.instance.pk:
                validate_batch_mutation(self.instance.batch_id)
            validate_batch_mutation(batch.pk)
        return data


class SessionForm(RosterForm):
    def clean(self):
        data = super().clean()
        if self.instance.pk and self.changed_data:
            validate_batch_mutation(self.instance.batch_id)
        return data


class LockedDeleteAdmin(admin.ModelAdmin):
    actions = None

    def has_add_permission(self, request):
        return not recovery_requires_review() and super().has_add_permission(request)

    def has_change_permission(self, request, obj=None):
        return not recovery_requires_review() and super().has_change_permission(request, obj)

    def has_delete_permission(self, request, obj=None):
        if recovery_requires_review():
            return False
        if obj is not None:
            batch_id = obj.pk if isinstance(obj, Batch) else obj.batch_id
            if is_batch_locked(batch_id):
                return False
        return super().has_delete_permission(request, obj)


@admin.register(Batch)
class BatchAdmin(LockedDeleteAdmin):
    form = BatchForm


@admin.register(Trainee)
class TraineeAdmin(LockedDeleteAdmin):
    form = RosterForm


@admin.register(Session)
class SessionAdmin(LockedDeleteAdmin):
    form = SessionForm


admin.site.site_header = "Training register setup"
