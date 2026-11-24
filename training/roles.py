from django.contrib.auth.decorators import user_passes_test


COORDINATE_REGISTER = "training.coordinate_register"


def is_coordinator(user):
    return user.has_perm(COORDINATE_REGISTER)


coordinator_required = user_passes_test(is_coordinator)
