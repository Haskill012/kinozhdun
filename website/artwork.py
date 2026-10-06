"""Reject known incorrect source artwork and unidentifiable sparse records."""
from urllib.parse import urlsplit

# These assets were reviewed against the 1969 film and belong to Pluribus.
# Reject by asset as well as identity so old news and search cannot reuse them.
REJECTED_ASSETS = {'/jWZDC1FhauBSyPuIRT0IWqTFcfN.jpg', '/5cqHto73TU7DH2v4MmRGZMPVTTT.jpg'}
REJECTED_PROJECTS = {('movie', 1426176)}


def allowed_asset(value):
    return bool(value) and '/' + urlsplit(value).path.rsplit('/', 1)[-1] not in REJECTED_ASSETS


def artwork(media, detail):
    # Source search and detail responses use different genre fields.
    identified = bool(str(detail.get('overview') or '').strip() or detail.get('genres') or detail.get('genre_ids'))
    if not identified or (media, detail.get('id')) in REJECTED_PROJECTS:
        return None, None
    poster = detail.get('poster_path')
    backdrop = detail.get('backdrop_path')
    poster = poster if allowed_asset(poster) else None
    backdrop = backdrop if allowed_asset(backdrop) else None
    return poster, backdrop
