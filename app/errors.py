class AppError(Exception):
    status_code = 500

    def __init__(self, message: str):
        super().__init__(message)
        self.message = message


class ImageValidationError(AppError):
    status_code = 400


class CaptchaError(AppError):
    status_code = 400


class PayloadTooLargeError(AppError):
    status_code = 413


class TooManyRequestsError(AppError):
    status_code = 429


class NotFoundError(AppError):
    status_code = 404


class UpstreamAIError(AppError):
    status_code = 502
