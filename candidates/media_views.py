"""Authenticated media serving for candidate CVs.

CVs are candidate PII. The DEBUG-gated ``static()`` media route in
altrium_tracker/urls.py served every file under MEDIA_ROOT to anonymous
clients (audit SEC-MEDIA-001, critical). This view replaces it for local
development: production uses the private S3 bucket with short-lived
presigned URLs (settings.py STORAGES), so this view is only wired when
DEBUG is on and no S3 backend is configured.
"""
import os

from django.contrib.auth.mixins import LoginRequiredMixin
from django.http import Http404, HttpResponse
from django.views import View

from altrium_tracker import settings as project_settings
from candidates.models import Candidate


class ProtectedMediaView(LoginRequiredMixin, View):
    """Serve one MEDIA_ROOT file after an authz check.

    HR and Management may open any CV. Interviewers may only open the
    resume of a candidate they are assigned to or panel a member of.
    Path traversal is blocked by resolving the requested path against
    MEDIA_ROOT and rejecting anything that escapes it.
    """

    def get(self, request, path):
        media_root = os.path.realpath(project_settings.MEDIA_ROOT)
        full = os.path.realpath(os.path.join(media_root, path))
        if not full.startswith(media_root + os.sep) or not os.path.isfile(full):
            raise Http404()

        if not (request.user.is_hr() or request.user.is_management()):
            assigned = Candidate.objects.filter(
                resume_file=path,
                applications__assigned_to=request.user,
            ).exists() or Candidate.objects.filter(
                resume_file=path,
                applications__panel_interviewers=request.user,
            ).exists()
            if not assigned:
                return HttpResponse('Forbidden', status=403)

        # Small local files; dev-only route. Range requests unnecessary.
        with open(full, 'rb') as fh:
            response = HttpResponse(fh.read())
        # Best-effort content type from extension; browsers handle PDF/DOCX.
        ext = os.path.splitext(full)[1].lower()
        types = {
            '.pdf': 'application/pdf',
            '.docx': 'application/vnd.openxmlformats-officedocument.wordprocessingml.document',
            '.doc': 'application/msword',
        }
        if ext in types:
            response['Content-Type'] = types[ext]
        response['Content-Disposition'] = f'inline; filename="{os.path.basename(full)}"'
        return response
