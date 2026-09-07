"""One error shape for the whole API:

    { "error": { "code": "VALIDATION", "message": "...", "details": [...] } }
"""

from flask import jsonify, request
from werkzeug.exceptions import HTTPException


class ApiError(Exception):
    status = 400
    code = "BAD_REQUEST"

    def __init__(self, message: str, details: list | None = None, status: int | None = None,
                 code: str | None = None):
        super().__init__(message)
        self.message = message
        self.details = details or []
        if status is not None:
            self.status = status
        if code is not None:
            self.code = code

    def to_response(self):
        payload = {"error": {"code": self.code, "message": self.message, "details": self.details}}
        return jsonify(payload), self.status


class ValidationError(ApiError):
    status = 422
    code = "VALIDATION"


class NotFoundError(ApiError):
    status = 404
    code = "NOT_FOUND"


def _is_api_request() -> bool:
    return request.path.startswith("/api/")


def register(app) -> None:
    @app.errorhandler(ApiError)
    def _api_error(exc: ApiError):
        return exc.to_response()

    @app.errorhandler(HTTPException)
    def _http_error(exc: HTTPException):
        # Page routes keep Flask's HTML error pages; the API always answers JSON.
        if not _is_api_request():
            return exc
        payload = {
            "error": {
                "code": exc.name.upper().replace(" ", "_"),
                "message": exc.description,
                "details": [],
            }
        }
        return jsonify(payload), exc.code

    if not app.config.get("TESTING"):
        # Left unregistered under TESTING so pytest reports the real traceback
        # instead of a tidy 500.
        @app.errorhandler(Exception)
        def _unexpected(exc: Exception):
            app.logger.exception("Unhandled error")
            payload = {
                "error": {
                    "code": "INTERNAL",
                    "message": "Something went wrong handling this request.",
                    "details": [],
                }
            }
            return jsonify(payload), 500
