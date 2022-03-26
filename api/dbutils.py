from datetime import datetime

from api.dbmodels.client import Client
from api.dbmodels.discorduser import DiscordUser
from api.dbmodels.event import Event
from typing import Optional
from errors import UserInputError


def get_client(user_id: int,
               guild_id: int = None,
               throw_exceptions=True) -> Optional[Client]:
    user = DiscordUser.query.filter_by(user_id=user_id).first()
    if user:
        if guild_id:
            event = get_event(guild_id, state='registration', throw_exceptions=False)
            if event:
                for client in event.registrations:
                    if client.discorduser.user_id == user_id:
                        return client

            event = get_event(guild_id, state='active', throw_exceptions=False)
            if event:
                for client in event.registrations:
                    if client.discorduser.user_id == user_id:
                        return client

            if throw_exceptions:
                raise UserInputError("User {name} is not registered for this event", user_id)
        if user.global_client:
            return user.global_client
        elif throw_exceptions:
            raise UserInputError("User {name} does not have a global registration", user_id)
    elif throw_exceptions:
        raise UserInputError("User {name} is not registered", user_id)


def get_event(guild_id: int, channel_id: int = None, state: str = 'active',
              throw_exceptions=True) -> Optional[Event]:

    if not state:
        state = 'active'

    now = datetime.now()

    filters = [Event.guild_id == guild_id]
    if state == 'archived':
        filters.append(Event.end < now)
    elif state == 'active':
        filters.append(Event.start <= now)
        filters.append(now <= Event.end)
    elif state == 'registration':
        filters.append(Event.registration_start <= now)
        filters.append(now <= Event.registration_end)

    if state == 'archived':
        events = Event.query.filter(*filters).all()
        events.sort(key=lambda x: x.end, reverse=True)
        event = events[0]
    else:
        event = Event.query.filter(*filters).first()

    if not event and throw_exceptions:
        raise UserInputError(f'There is no {"event you can register for" if state == "registration" else "active event"}')
    return event


def get_all_events(guild_id: int, channel_id):
    pass


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
    result = DiscordUser.query.filter_by(user_id=user_id).first()
    if not result and throw_exceptions:
        raise UserInputError("User {name} is not registered", user_id)
    if len(result.clients) == 0 and throw_exceptions:
        raise UserInputError("User {name} does not have any registrations", user_id)
    return result


def get_guild_start_end_times(guild_id, start, end, archived=False):

    start = datetime.fromtimestamp(0) if not start else start
    end = datetime.now() if not end else end
    event = get_event(guild_id, state='archived' if archived else 'active', throw_exceptions=False)

    if event:
        # When custom times are given make sure they don't exceed event boundaries (clients which are global might have more data)
        return max(start, event.start), min(end, event.end)
    else:
        return start, end
