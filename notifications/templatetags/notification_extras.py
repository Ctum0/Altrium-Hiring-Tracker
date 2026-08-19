from django import template

register = template.Library()


@register.filter
def safe_link(value):
    """Return the link only for internal paths or http(s) URLs.

    Prevents stored notification links with schemes like ``javascript:``
    from being rendered as clickable hrefs.
    """
    if not value:
        return ''
    value = str(value).strip()
    if value.startswith('/') and not value.startswith('//'):
        return value
    if value.startswith(('http://', 'https://')):
        return value
    return ''
