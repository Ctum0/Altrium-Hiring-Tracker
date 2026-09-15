"""Fuzzy duplicate detection for CV intake (Phase 3: name + phone match).

Email-exact matching stays the PRIMARY dedup mechanism: both intake paths
(``CandidateUploadView``, ``CandidateImportView``) still resolve
``Candidate.objects.get_or_create(email=...)`` first and that path is
untouched. This module closes the remaining gap — the same human
re-applying with a DIFFERENT email address (new personal address, work
vs. private, abandoned old one), and email-less CVs.

Matching rule (strict v1)
-------------------------
A parsed CV matches an existing candidate when BOTH hold:

1. Normalized first+last name equality. Normalization lowercases, strips,
   and collapses internal whitespace. Name ORDER matters ("Smith Jane" !=
   "Jane Smith") — a reversed/permuted-name pass was deliberately left out
   of v1: it multiplies false positives, and a wrong match silently files
   one person's CV under another person's record.
2. Normalized phone equality (digits only). BOTH sides must have a phone:
   an incoming CV without one, or an existing candidate without one, never
   matches. Letting "both phones empty" match would merge every same-named
   pair in the database — too ambiguous for v1.

False-positive risk (documented): name collisions. Two different people
named "Jane Smith" who also share one phone line (family/couple plans)
would be treated as one person. The name+phone PAIR is the mitigation —
name alone never matches, and phone digits must be identical.
False-negative risks accepted in v1: swapped name order, missing phones on
either side, country-code variants ("+1 555…" vs "555…"), and trigram-
adjacent spellings ("Jon Smith" vs "John Smith"). A Postgres trigram index
(pg_trgm + GIN on a normalized name column) plus a country-code-aware
phone normalizer is the documented later optimization.

Scale: the lookup pre-filters the queryset with ``iexact`` on the parsed
first_name (last_name when the parse produced no first name) and scans
only that subset in Python. At Phase 3 scale (1000+ candidates) this
per-upload scan of the pre-filtered subset is acceptable; beyond ~10k
candidates move the comparison into the database with the trigram index
above.
"""
from .models import Candidate


def _normalize_name(*parts):
    """Lowercase, strip, and collapse internal whitespace of name parts."""
    return ' '.join(
        collapsed
        for collapsed in (' '.join((part or '').split()).lower() for part in parts)
        if collapsed
    )


def _normalize_phone(value):
    """Keep digits only: '+1 (555) 123-4567' -> '15551234567'."""
    return ''.join(ch for ch in (value or '') if ch.isdigit())


def find_fuzzy_match(parsed, exclude_pk=None):
    """Return the existing Candidate that looks like the same person, or None.

    ``parsed`` is a ``parse_cv`` result dict; only ``first_name``,
    ``last_name``, and ``phone`` are read. ``exclude_pk`` skips one record —
    the email-path secondary check passes the just-created candidate's pk so
    it cannot match itself. When several candidates match, the most recently
    updated one wins (deterministic pick).
    """
    first = (parsed.get('first_name') or '').strip()
    last = (parsed.get('last_name') or '').strip()
    if not first and not last:
        # A nameless parse can never be told apart from anyone else.
        return None
    phone = _normalize_phone(parsed.get('phone'))
    if not phone:
        # Strict v1: without a phone the name alone is too ambiguous.
        return None

    wanted_name = _normalize_name(first, last)
    # SQL pre-filter narrows the pool; the normalized name+phone comparison
    # below is the authoritative check.
    if first:
        qs = Candidate.objects.filter(first_name__iexact=first)
    else:
        qs = Candidate.objects.filter(last_name__iexact=last)
    qs = qs.exclude(phone='')
    if exclude_pk is not None:
        qs = qs.exclude(pk=exclude_pk)
    for cand in qs.order_by('-updated_at'):
        if _normalize_name(cand.first_name, cand.last_name) != wanted_name:
            continue
        if _normalize_phone(cand.phone) == phone:
            return cand
    return None
