from aiohttp import ClientResponseError


class UserInputError(Exception):
    def __init__(self, reason: str, user_id: int = None, *args):
        super().__init__(*args)
        self.reason = reason
        self.user_id = user_id


class InternalError(Exception):
    def __init__(self, reason: str, *args):
        super().__init__(*args)
        self.reason = reason


class ResponseError(Exception):
    def __init__(self, root_error: ClientResponseError, human: str):
        self.root_error = root_error
        self.human = human


class CriticalError(ResponseError):
    def __init__(self, retry_ts: int = None, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.retry_ts = retry_ts


class RateLimitExceeded(CriticalError):
    pass


class ExchangeUnavailable(CriticalError):
    pass


class ExchangeMaintenance(CriticalError):
    pass
