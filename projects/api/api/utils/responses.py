from http import HTTPStatus
from typing import Any, TypeVar, Optional, Generic

from fastapi import HTTPException
from fastapi.encoders import jsonable_encoder
from starlette.responses import JSONResponse

from core import json as customjson
from database.models import BaseModel

ResultT = TypeVar('ResultT', bound=BaseModel)


class ResponseModel(BaseModel, Generic[ResultT]):
    detail: str
    code: Optional[int]
    result: Optional[ResultT]


def BadRequest(detail: str = None, code: int = None, **kwargs):
    return HTTPException(detail=detail or 'Bad Request', status_code=HTTPStatus.BAD_REQUEST)


def NotFound(detail: str = None, code: int = None, **kwargs):
    return HTTPException(detail=detail or 'Not Found', status_code=HTTPStatus.NOT_FOUND)
    #return Response(detail or 'Not Found', code, HTTPStatus.NOT_FOUND, **kwargs)


def Unauthorized(detail: str = None):
    return HTTPException(detail=detail or 'Unauthorized', status_code=HTTPStatus.UNAUTHORIZED)


def InternalError(detail: str = None, code: int = None, **kwargs):
    return HTTPException(detail=detail or 'Internal Error', status_code=HTTPStatus.INTERNAL_SERVER_ERROR)
    return Response(detail or 'Internal Error', code, HTTPStatus.INTERNAL_SERVER_ERROR, **kwargs)


def OK(detail: str = None, code: int = None, **kwargs):
    return Response(detail or 'OK', code, HTTPStatus.OK, **kwargs)


def Response(detail: str, code: int, status: int, result: Any = None, **kwargs):
    return CustomJSONResponse(jsonable_encoder(result, **kwargs), status_code=status)
    return CustomJSONResponse(
        {'detail': detail, 'code': code, 'result': jsonable_encoder(result), **kwargs},
        status_code=status
    )


class CustomJSONResponse(JSONResponse):
    media_type = "application/json"

    def render(self, content: Any) -> bytes:
        return customjson.dumps(content)
