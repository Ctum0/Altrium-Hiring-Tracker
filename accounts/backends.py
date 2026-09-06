"""Axes backend tolerant of request-less ``authenticate()`` calls.

Django's test client (``self.client.login()``) invokes
``django.contrib.auth.authenticate(**credentials)`` without a request,
which makes ``AxesStandaloneBackend`` raise
``AxesBackendRequestParameterRequired``. This subclass keeps full lockout
protection for real requests while letting request-less calls fall through
to the following backends (ModelBackend).
"""
from axes.backends import AxesStandaloneBackend


class AxesTolerantBackend(AxesStandaloneBackend):
    def authenticate(self, request, username=None, password=None, **kwargs):
        if request is None:
            # No request context (programmatic auth / test client):
            # skip lockout monitoring and let the next backend authenticate.
            return None
        return super().authenticate(request, username=username, password=password, **kwargs)
