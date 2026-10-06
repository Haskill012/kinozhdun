"""Shared audience policy and website article pagination."""
from shared.audience import audience_metadata, exclusion_reason, audience_items

def audience_articles(store, config, *, category=None, query='', limit=24, offset=0):
    """Filter before pagination, while preserving individual article URLs and history."""
    selected, position = [], 0
    while len(selected) < offset + limit:
        batch = store.articles(category=category, query=query, limit=100, offset=position)
        for article in batch:
            item = store.catalog_item(f"{article.get('media_type')}:{article.get('tmdb_id')}", False) or {}
            if not exclusion_reason(item, config):
                selected.append(article)
        position += len(batch)
        if len(batch) < 100:
            break
    return selected[offset:offset + limit]
