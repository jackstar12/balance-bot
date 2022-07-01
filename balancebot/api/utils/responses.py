from http import HTTPStatus
from typing import Dict, Any

import orjson
from fastapi.responses import UJSONResponse
from starlette.responses import JSONResponse

from balancebot.common import customjson


def BadRequest(detail: str, code: int = None, **kwargs):
    return Response(detail, code, HTTPStatus.BAD_REQUEST, **kwargs)


def NotFound(detail: str, code: int = None, **kwargs):
    return Response(detail, code, HTTPStatus.NOT_FOUND, **kwargs)


def InternalError(detail: str, code: int = None, **kwargs):
    return Response(detail, code, HTTPStatus.INTERNAL_SERVER_ERROR, **kwargs)


def OK(detail: str, code: int = None, **kwargs):
    return Response(detail, code, HTTPStatus.OK, **kwargs)


def Response(detail: str, code: int, status: int, **kwargs):
    return CustomJSONResponse(
        {'detail': detail, 'code': code, **kwargs},
        status_code=status
    )


class CustomJSONResponse(JSONResponse):
    media_type = "application/json"

    def render(self, content: Any) -> bytes:
        return customjson.dumps(content)
