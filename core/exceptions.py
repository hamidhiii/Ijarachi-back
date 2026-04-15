from rest_framework.views import exception_handler
from rest_framework.response import Response
from rest_framework import status
import logging

logger = logging.getLogger(__name__)

def custom_exception_handler(exc, context):
    """
    Consolidates all API errors into a standard format.
    Format:
    {
        "error": "error_code_string",
        "message": "Human readable message",
        "details": { ... }
    }
    """
    # Call DRF's default exception handler first
    response = exception_handler(exc, context)

    # If DRF handled it, refine the response
    if response is not None:
        data = response.data
        
        # Flatten details
        details = data
        if isinstance(data, dict):
            # If the payload has "detail", use it as the main message
            message = data.get('detail', 'Validation failed')
            error_code = data.get('code', 'validation_error')
        else:
            message = 'Validation failed'
            error_code = 'validation_error'

        response.data = {
            'error': error_code,
            'message': message,
            'details': details
        }
    else:
        # Handle unhandled errors (500)
        logger.error(f"Unhandled exception: {str(exc)}", exc_info=True)
        response = Response({
            'error': 'internal_server_error',
            'message': 'Произошла непредвиденная ошибка.',
            'details': None
        }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

    return response
