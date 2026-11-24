from django.contrib import admin
from .models import Batch, Trainee, Session

admin.site.site_header = "Training register setup"
admin.site.register(Batch)
admin.site.register(Trainee)
admin.site.register(Session)
