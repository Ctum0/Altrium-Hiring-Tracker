"""Template context: cache-busting version for the app stylesheet.

Dev mode serves static files unversioned (StaticFilesStorage), so browsers
hold a stale app.css after CSS changes until a hard refresh — which
manifested as "layout bugs that fix themselves when you resize the
window" (the resize forced the cached rules to re-evaluate against new
markup). Appending the file's mtime as ?v= makes every CSS change a new
URL: browsers fetch fresh rules immediately, no manual hard-refresh.
"""
from pathlib import Path

from django.conf import settings

_css_mtime_cache = None


def _css_version():
    global _css_mtime_cache
    if _css_mtime_cache is None:
        try:
            p = Path(settings.BASE_DIR) / 'static' / 'css' / 'app.css'
            _css_mtime_cache = str(int(p.stat().st_mtime))
        except OSError:
            _css_mtime_cache = '0'
    return _css_mtime_cache


def asset_version(request):
    return {'app_css_version': _css_version()}
