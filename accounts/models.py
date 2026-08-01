from django.contrib.auth.models import AbstractUser
from django.db import models


class Role(models.TextChoices):
    HR = 'HR', 'Human Resources'
    INTERVIEWER = 'IV', 'Interviewer'
    MANAGEMENT = 'MGMT', 'Management'


class User(AbstractUser):
    role = models.CharField(max_length=5, choices=Role.choices, default=Role.HR)

    def is_hr(self) -> bool:
        return self.role == Role.HR

    def is_interviewer(self) -> bool:
        return self.role == Role.INTERVIEWER

    def is_management(self) -> bool:
        return self.role == Role.MANAGEMENT
