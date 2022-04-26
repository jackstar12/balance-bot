from http import HTTPStatus
from typing import Dict

from starlette.responses import JSONResponse


def BadRequest(detail: str, code: int = None, **kwargs):
    return Response(detail, code, HTTPStatus.BAD_REQUEST, **kwargs)


def InternalError(detail: str, code: int = None, **kwargs):
    return Response(detail, code, HTTPStatus.INTERNAL_SERVER_ERROR, **kwargs)


def OK(detail: str, code: int = None, **kwargs):
    return Response(detail, code, HTTPStatus.OK, **kwargs)


def Response(detail: str, code: int, status: int, **kwargs):
    return JSONResponse(
        {'detail': detail, 'code': code, **kwargs},
        status_code=status
    )
