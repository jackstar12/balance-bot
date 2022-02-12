class UserInputError(Exception):
    def __init__(self, reason: str, user_id: int = None, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.reason = reason
        self.user_id = user_id
