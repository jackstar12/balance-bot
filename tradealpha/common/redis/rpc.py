import json
import uuid
from typing import Type, NamedTuple, Callable

import logging

from aioredis import Redis

from tradealpha.common import utils
from tradealpha.common.models import BaseModel

logger = logging.getLogger('rpc')


class Error(Exception):
    '''parent class for all pyredisrpc errors'''
    pass


class BadRequest(Error):
    '''any problem in request from json parse error to method not found raises this error'''
    pass


class CallError(Error):
    '''if any error occur inside called method it raises this error'''
    pass


class TimeoutError(Error):
    '''if server doesn't response in call timeout time client raises this error'''
    pass

class Unauthorized(Error):
    pass


class Method(NamedTuple):
    model: Type[BaseModel]
    fn: Callable


class Server:
    '''redis rpc server'''

    def __init__(self, queue, redis: Redis, prefix='rpc:', response_expire_time=60):
        '''
        redis_url: url to redis server
        queue: a name to generate server listening queue based on it
        prefix: use as a prefix to generate needed redis keys
        response_expire_time: response will expire if client doesn't fetch it in this time (seconds)
        '''
        self.redis = redis
        self.prefix = prefix
        self.queue = prefix + queue
        self.response_expire_time = response_expire_time
        self.methods: dict[str, Method] = {}

    async def run(self):
        '''
        run main loop of server: receive, parse, call
        '''
        while True:
            _, req_data = await self.redis.blpop(self.queue)
            req_data = req_data.decode()
            req_args = await self.parse_request(req_data)
            if req_args is None:
                continue
            req_id, method, params, timeout_check = req_args
            if timeout_check and await self.is_timeout_expired(req_id):
                continue
            await self.call_method(req_id, method, params)

    async def parse_request(self, req_data):
        '''
        parse request and returns request id, method name and params
        if error, sends error response to client and returns None
        req_data: a string contins json request
        '''
        try:
            req = json.loads(req_data)  # TODO: check unicode data
        except json.JSONDecodeError:
            logger.error('request contains invalid json data: %s', req_data)
            return
        try:
            req_id = req['id']
        except KeyError:
            logger.error('id not found in request: %s', req)
            return
        try:
            method = req['method']
            params = req['params']
        except KeyError as e:
            key = e.args[0]
            logger.error('BadRequest: missing request key: %s', key)
            await self.send_response(req_id, None, BadRequest('missing request key', key))
            return
        if method not in self.methods:
            logger.error('BadRequest: method not found: %s', method)
            await self.send_response(req_id, None, BadRequest('method not found', method))
            return
        if type(params) != dict:
            logger.error('BadRequest: invalid params: %s', params)
            await self.send_response(req_id, None, BadRequest('invalid params', params))
            return
        timeout_check = req.get('tmchk') == 1
        return req_id, method, params, timeout_check

    async def is_timeout_expired(self, req_id):
        timeout_key = self.prefix + req_id + ':tmchk'
        return await self.redis.get(timeout_key) is None

    async def call_method(self, req_id, method_name: str, params: dict):
        '''
        calls the required client method and send response to client
        if error, sends a CallError response
        '''
        method = self.methods[method_name]
        try:
            val = await utils.call_unknown_function(
                method.fn,
                method.model(**params)
            )
        except Exception as e:
            logger.exception('CallError: %s', e)
            await self.send_response(req_id, None, CallError(repr(e)))
            return
        logger.info('Success: method=%s, params=%s, result=%s', method_name, params, val)
        await self.send_response(req_id, val, None)

    async def send_response(self, req_id, result, error):
        '''
        sends a success or error response to client
        result: the result value of called method (any json serializable value), or None if error
        error: an Error object to send to client or None if success
        '''
        if error is not None:
            error = [error.__class__.__name__, error.args]
        result = {'id': req_id, 'result': result, 'error': error}
        key = self.prefix + req_id
        await self.redis.rpush(key, json.dumps(result))
        await self.redis.expire(key, self.response_expire_time)


    def method(self, input_model: Type[BaseModel]):
        def decorate(f):
            '''
            a decorator to define server methods
            '''
            self.methods[f.__name__] = Method(model=input_model, fn=f)

        return decorate


class Client:
    '''redis rpc client'''

    def __init__(self, queue, redis: Redis, prefix='rpc:', timeout=2):
        '''
        redis_url: url to redis server
        queue: a name to generate server listening queue based on it
        prefix: use as a prefix to generate needed redis keys
        timeout: request timeout in seconds
        '''
        self.redis = redis
        self.prefix = prefix
        self.queue = prefix + queue
        self.timeout = timeout

    async def call(self, method, request: BaseModel):
        '''
        method: method name to call
        params: a list with exactly two items: [[args], {keywords}]
        '''
        req_id = uuid.uuid4().hex
        req = {'id': req_id, 'method': method, 'params': request.dict()}
        if self.timeout != 0:
            req['tmchk'] = 1
            timeout_key = self.prefix + req_id + ':tmchk'
            await self.redis.set(timeout_key, 1, self.timeout)
        await self.redis.rpush(self.queue, json.dumps(req))
        key = self.prefix + req_id
        res = await self.redis.blpop(key, self.timeout)
        if not res:
            raise TimeoutError(req, key)
        _, response_data = res
        response = json.loads(response_data.decode())
        if response['error'] is not None:
            self.raise_error(response['error'])
        return response['result']

    def raise_error(self, error):
        '''
        parse and raise received error from server
        error: a list contines two items: [error_name, error_args]
        '''
        err_name, err_args = error
        classes = {'BadRequest': BadRequest, 'CallError': CallError}
        err_class = classes[err_name]
        err = err_class(*err_args)
        raise err

    def __call__(self, method, request: BaseModel):
        return self.call(method, request)
