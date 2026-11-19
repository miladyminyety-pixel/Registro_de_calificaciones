"""Errores de dominio que se convierten en respuestas JSON/HTTP."""


class ApiError(Exception):
    def __init__(self, status: int, message: str, field: str | None = None, details=None):
        super().__init__(message)
        self.status = status
        self.message = message
        self.field = field
        self.details = details

    def to_dict(self) -> dict:
        body = {"error": self.message}
        if self.field:
            body["campo"] = self.field
        if self.details:
            body["detalles"] = self.details
        return body


def not_found(message: str = "No encontrado") -> ApiError:
    return ApiError(404, message)


def invalid(message: str, field: str | None = None, details=None) -> ApiError:
    return ApiError(422, message, field, details)
