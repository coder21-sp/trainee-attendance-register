from django.core.exceptions import ValidationError

from .models import Approval


def is_batch_locked(batch_id: int) -> bool:
    return Approval.objects.filter(trainee__batch_id=batch_id).exists()


def validate_batch_mutation(batch_id: int) -> None:
    if is_batch_locked(batch_id):
        raise ValidationError("This batch has approved certificates. Its roster, sessions and threshold are locked.")
