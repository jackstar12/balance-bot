from http import HTTPStatus
from typing import Dict

from starlette.responses import JSONResponse


def BadRequest(msg: str, code: int = None, **kwargs):
    return Response(msg, code, HTTPStatus.BAD_REQUEST, **kwargs)


def InternalError(msg: str, code: int = None, **kwargs):
    return Response(msg, code, HTTPStatus.INTERNAL_SERVER_ERROR, **kwargs)


def OK(msg: str, code: int = None, **kwargs):
    return Response(msg, code, HTTPStatus.OK, **kwargs)


def Response(msg: str, code: int, status: int, **kwargs):
    return JSONResponse(
        {'msg': msg, 'code': code, **kwargs},
        status_code=status
    )
