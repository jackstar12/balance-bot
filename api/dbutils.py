from datetime import datetime

from api.database import db
from api.dbmodels.client import Client
from api.dbmodels.balance import Balance
from api.dbmodels.discorduser import DiscordUser
from api.dbmodels.event import Event
from typing import Optional


def get_client(user_id: int,
               guild_id: int = None,
               throw_exceptions=True) -> Optional[Client]:
    user = DiscordUser.query.filer_by(user_id=user_id)
    if user:
        if guild_id:
            event = Event.query.filter_by(guild_id=guild_id).first()
            if event:
                for client in event.registrations:
                    if client.discorduser.user_id == user_id:
                        return client
                if throw_exceptions:
                    raise ValueError("User {name} is not registered for this event")
        if user.global_client_id:
            return Client.query.filter_by(id=user.global_client_id).first()
        elif throw_exceptions:
            raise ValueError("User {name} does not have a global registration")
    elif throw_exceptions:
        raise ValueError("User {name} is not registered")


def get_active_event(guild_id: int, throw_exceptions=False) -> Optional[Event]:
    event = Event.query.filter_by(guild_id=guild_id).first()
    if not event and throw_exceptions:
        raise ValueError('There is no active event')
    return event


def get_user(user_id: int, throw_exceptions=True) -> Optional[DiscordUser]:
    """
    Tries to find a matching entry for the user and guild id.
    :param user_id: id of user to get
    :param guild_id: guild id of user to get
    :param throw_exceptions: whether to throw exceptions if user isn't registered
    :param exact: whether the global entry should be used if the guild isn't registered
    :return:
    The found user. It will never return None if throw_exceptions is True, since an ValueError exception will be thrown instead.
    """
    result = DiscordUser.query.filter_by(user_id=user_id)
    if not result and throw_exceptions:
        raise ValueError("User {name} does not have a global registration")
    return result
