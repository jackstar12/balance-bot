from functools import wraps

from flask import request
from http import HTTPStatus
from typing import List, Tuple, Union, Callable, Dict
from api.database import app
import flask_jwt_extended as flask_jwt


def check_args_before_call(callback, arg_names, *args, **kwargs):
    for arg_name, required in arg_names:
        if required:
            if (request.args and arg_name not in request.args) \
                    and (request.json and arg_name not in request.json):
                return {'msg': f'Missing parameter {arg_name}'}, HTTPStatus.BAD_REQUEST
    kwargs = {**kwargs, **dict(request.args), **(request.json if request.json else {})}
    return callback(*args, **kwargs)


def require_args(arg_names: List[Tuple[str, bool]]):
    def decorator(fn):
        @wraps(fn)
        def wrapper(*args, **kwargs):
            return check_args_before_call(fn, arg_names, *args, **kwargs)
        return wrapper
    return decorator


def create_endpoint(
        route: str,
        methods: Dict[str, Dict[str, Union[List[Tuple[str, bool]], Callable]]],
        jwt_auth=False):

    def wrapper(*args, **kwargs):
        if request.method in methods:
            arg_names = methods[request.method]['args']
            callback = methods[request.method]['callback']
        else:
            return {'msg': f'This is a bug in the API.'}, HTTPStatus.INTERNAL_SERVER_ERROR
        return check_args_before_call(callback, arg_names, *args, **kwargs)

    wrapper.__name__ = route

    if jwt_auth:
        app.route(route, methods=list(methods.keys()))(
            flask_jwt.jwt_required()(wrapper)
        )
    else:
        app.route(route, methods=list(methods.keys()))(
            wrapper
        )
