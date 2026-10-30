"""Static public job categories, independent of provider bodies/exception text."""

_CATEGORIES = frozenset({'configuration', 'authentication', 'rate_limit', 'transient',
    'model_missing', 'identity_mismatch', 'unsupported_capability', 'invalid_response', 'capacity'})
PROVIDER_FAILURE_CODES = frozenset('provider_' + code for code in _CATEGORIES)


def failure_code(error, fallback):
    code = getattr(error, 'code', None)
    return 'provider_' + code if isinstance(code, str) and code in _CATEGORIES else fallback
