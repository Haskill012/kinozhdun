"""Shared accessible rating presentation; numbers remain the primary signal."""
def rating_class(value):
    value = float(value or 0)
    return 'rating-good' if value >= 7 else 'rating-medium' if value >= 5 else 'rating-low'
