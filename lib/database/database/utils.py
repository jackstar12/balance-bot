from __future__ import annotations
from datetime import datetime

import pytz
from sqlalchemy import select, desc, JSON, or_
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.sql import Select, Delete, Update

import database.dbmodels.client as db_client

from database.dbmodels.user import User
from database.dbasync import db_first, db_all, \
    db_select, async_session, time_range
from database.dbmodels.balance import Balance
from database.dbmodels.discord.discorduser import DiscordUser
import database.dbmodels.event as db_event
from typing import Optional, Union, TYPE_CHECKING
from database.errors import UserInputError
from database.models.history import History

if TYPE_CHECKING:
    from database.dbmodels.event import EventState, LocationModel


async def get_client_history(client: db_client.Client,
                             init_time: datetime = None,
                             since: datetime = None,
                             to: datetime = None,
                             currency: str = None) -> History:

    if currency is None:
        currency = 'USD'

    initial = None

    history = await db_all(client.history.statement.filter(
        time_range(Balance.time, since, to),
        Balance.extra_currencies[currency] != JSON.NULL if currency != client.currency else True
    ))

    if init_time and init_time != since:
        initial = await client.get_balance_at_time(client.id, init_time, async_session)

    if not initial:
        try:
            initial = history[0]
        except (ValueError, IndexError):
            pass

    return History(
        data=history,
        initial=initial
    )


async def get_discord_client(user_id: int,
                             guild_id: int = None,
                             registration=False,
                             throw_exceptions=True,
                             client_eager=None,
                             discord_user_eager=None) -> Optional[db_client.Client]:
    discord_user_eager = discord_user_eager or []
    client_eager = client_eager or []

    user = await get_discord_user(
        user_id,
        throw_exceptions=throw_exceptions,
        eager_loads=[
            DiscordUser.global_associations,
            *discord_user_eager
        ]
    )
    if user:
        if guild_id:
            event = await get_discord_event(guild_id,
                                            state=db_event.EventState.REGISTRATION if registration else db_event.EventState.ACTIVE,
                                            throw_exceptions=False,
                                            eager_loads=[db_event.Event.registrations])
            if event:
                for client in event.registrations:
                    if client.discord_user_id == user_id:
                        return client
                if throw_exceptions:
                    raise UserInputError("User {name} is not registered for this event", user_id)

        client = await user.get_guild_client(guild_id, *client_eager, db=async_session)
        if client:
            return client
        elif throw_exceptions:
            raise UserInputError("User {name} does not have a global registration", user_id)
    elif throw_exceptions:
        raise UserInputError("User {name} is not registered", user_id)


async def get_event(location: LocationModel | dict,
                    state: EventState = None,
                    throw_exceptions=True,
                    eager_loads=None,
                    db: AsyncSession = None) -> Optional[db_event.Event]:
    state = state or db_event.EventState.ACTIVE
    eager_loads = eager_loads or []

    stmt = select(
        db_event.Event
    ).filter(
        db_event.Event.location == location,
        db_event.Event.is_expr(state)
    )

    if state == db_event.EventState.ARCHIVED:
        stmt = stmt.order_by(
            desc(db_event.Event.end)
        ).limit(1)

    event = await db_first(stmt, *eager_loads, session=db)

    if not event and throw_exceptions:
        raise UserInputError(
            f'There is no {"event you can register for" if state == "registration" else "active event"}')
    return event


def get_discord_event(guild_id: int,
                      channel_id: int = None,
                      state: EventState = None,
                      throw_exceptions=True,
                      eager_loads=None):
    return get_event(
        {
            'platform': 'discord',
            'data': {
                'guild_id': str(guild_id),
                'channel_id': str(channel_id)
            }
        },
        state=state, throw_exceptions=throw_exceptions, eager_loads=eager_loads
    )


def add_client_filters(stmt: Union[Select, Delete, Update], user: User, client_ids: list[int] = None) -> Union[
    Select, Delete, Update]:
    """
    Commonly used utility to add filters that ensure authorized client access
    :param stmt: stmt to add filters to
    :param user: desired user
    :param client_ids: possible client ids. If None, all clients will be used
    :return:
    """
    # user_checks = [Client.user_id == user.id]
    # if user.discord_user_id:
    #    user_checks.append(Client.discord_user_id == user.discord_user_id)
    return stmt.filter(
        db_client.Client.id.in_(client_ids) if client_ids else True,
        or_(
            db_client.Client.user_id == user.id,
            # db_client.Client.discord_user_id == user.discord_user_id if user.discord_user_id else False
        )
    )


def get_all_events(guild_id: int, channel_id):
    pass


async def get_discord_user(user_id: int,
                           throw_exceptions=True,
                           require_clients=True,
                           eager_loads=None,
                           db: AsyncSession = None) -> Optional[DiscordUser]:
    """
    Tries to find a matching entry for the user and guild id.
    :param user_id: id of user to get
    :param guild_id: guild id of user to get
    :param throw_exceptions: whether to throw exceptions if user isn't registered
    :param exact: whether the global entry should be used if the guild isn't registered
    :return:
    The found user. It will never return None if throw_exceptions is True, since an ValueError exception will be thrown instead.
    """
    eager = eager_loads or []
    eager.append(DiscordUser.clients)
    result = await db_select(DiscordUser, eager=eager, account_id=str(user_id), session=db)

    if not result:
        if throw_exceptions:
            raise UserInputError("User {name} is not registered", user_id)
    elif len(result.clients) == 0 and throw_exceptions and require_clients:
        raise UserInputError("User {name} does not have any registrations", user_id)
    return result
