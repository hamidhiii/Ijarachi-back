from rest_framework.views import exception_handler as drf_exception_handler

# Раньше detail был единственным способом фронта понять причину ошибки, а он
# на русском — на узбекском экране это выглядит чужеродно. code — стабильный
# машиночитаемый слаг, по нему фронт сам пишет текст на нужном языке; detail
# остаётся для логов и как запасной вариант.
_CODE_BY_EXCEPTION = {
    'NotAuthenticated': 'not_authenticated',
    'AuthenticationFailed': 'authentication_failed',
    'PermissionDenied': 'permission_denied',
    'NotFound': 'not_found',
    'MethodNotAllowed': 'method_not_allowed',
    'NotAcceptable': 'not_acceptable',
    'Throttled': 'throttled',
    'ParseError': 'parse_error',
    'UnsupportedMediaType': 'unsupported_media_type',
    'ValidationError': 'validation_error',
}


def exception_handler(exc, context):
    response = drf_exception_handler(exc, context)
    if response is None:
        return None
    if isinstance(response.data, dict) and 'code' not in response.data:
        response.data['code'] = _CODE_BY_EXCEPTION.get(type(exc).__name__, 'error')
    return response
