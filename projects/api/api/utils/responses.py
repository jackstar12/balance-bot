from http import HTTPStatus
from typing import Dict, Any, TypeVar, Optional, Generic

import orjson
from fastapi.encoders import jsonable_encoder
from fastapi.responses import UJSONResponse
from starlette.responses import JSONResponse

from common.models import BaseModel
from common import customjson


ResultT = TypeVar('ResultT', bound=BaseModel)


class ResponseModel(BaseModel, Generic[ResultT]):
    detail: str
    code: Optional[int]
    result: Optional[ResultT]


def BadRequest(detail: str = None, code: int = None, **kwargs):
    return Response(detail or 'Bad Request', code, HTTPStatus.BAD_REQUEST, **kwargs)


def NotFound(detail: str = None, code: int = None, **kwargs):
    return Response(detail or 'Not Found', code, HTTPStatus.NOT_FOUND, **kwargs)


def InternalError(detail: str = None, code: int = None, **kwargs):
    return Response(detail or 'Internal Error', code, HTTPStatus.INTERNAL_SERVER_ERROR, **kwargs)


def OK(detail: str = None, code: int = None, **kwargs):
    return Response(detail or 'OK', code, HTTPStatus.OK, **kwargs)


def Response(detail: str, code: int, status: int, result: Any = None, **kwargs):
    return CustomJSONResponse(
        {'detail': detail, 'code': code, 'result': jsonable_encoder(result), **kwargs},
        status_code=status
    )


class CustomJSONResponse(JSONResponse):
    media_type = "application/json"

    def render(self, content: Any) -> bytes:
        return customjson.dumps(content)
