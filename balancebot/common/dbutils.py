from __future__ import annotations
from datetime import datetime

import pytz
from sqlalchemy import select, desc, JSON

import balancebot.common.dbmodels.client as db_client
from balancebot.common.database_async import async_session, db_first, db_eager, db_del_filter, db_unique, db_all, \
    db_select
from balancebot.common.dbmodels.balance import Balance
from balancebot.common.dbmodels.discorduser import DiscordUser
import balancebot.common.dbmodels.event as db_event
from typing import Optional
from balancebot.common.errors import UserInputError
from balancebot.common.messenger import Messenger, NameSpace, Category
from balancebot.common.models.history import History


async def get_client_history(client: db_client.Client,
                             event: db_event.Event,
                             since: datetime = None,
                             to: datetime = None,
                             currency: str = None) -> History:
    since = since or datetime.fromtimestamp(0, tz=pytz.utc)
    to = to or datetime.now(pytz.utc)

    if event:
        # When custom times are given make sure they don't exceed event boundaries (clients which are global might have more data)
        since = max(since, event.start)
        to = min(to, event.end)

    if currency is None:
        currency = '$'

    results = []
    initial = None

    filter_time = event.start if event else since

    history = await db_all(client.history.statement.filter(
        Balance.time > filter_time,
        Balance.time < to,
        Balance.extra_currencies[currency] != JSON.NULL if currency != client.currency else True
    ))

    for balance in history:
        if since <= balance.time:
            results.append(balance)
        elif event and event.start <= balance.time and not initial:
            initial = balance

    #if results:
    #    results.insert(0, Balance(
    #        time=since,
    #        unrealized=results[0].unrealized,
    #        realized=results[0].realized,
    #    ))

    if not initial:
        try:
            initial = results[0]
        except (ValueError, IndexError):
            pass

    return History(
        data=results,
        initial=initial
    )


async def get_client(user_id: int,
                     guild_id: int = None,
                     registration=False,
                     throw_exceptions=True,
                     client_eager=True,
                     discord_user_eager=None) -> Optional[db_client.Client]:
    discord_user_eager = discord_user_eager or []
    user = await get_discord_user(
        user_id,
        throw_exceptions=throw_exceptions,
        eager_loads=[(DiscordUser.clients, client_eager), DiscordUser.guilds, *discord_user_eager])
    if user:
        if guild_id:
            if registration:
                event = await get_event(guild_id, state='registration', throw_exceptions=False,
                                        eager_loads=[db_event.Event.registrations])
                if event:
                    for client in event.registrations:
                        if client.discord_user_id == user_id:
                            return client

            event = await get_event(guild_id, state='active', throw_exceptions=False,
                                    eager_loads=[db_event.Event.registrations])
            if event:
                for client in event.registrations:
                    if client.discord_user_id == user_id:
                        return client

            if event and throw_exceptions:
                raise UserInputError("User {name} is not registered for this event", user_id)

        client = await user.get_global_client(guild_id)
        if client:
            return client
        elif throw_exceptions:
            raise UserInputError("User")
        elif throw_exceptions:
            raise UserInputError("User {name} does not have a global registration", user_id)
    elif throw_exceptions:
        raise UserInputError("User {name} is not registered", user_id)


async def get_event(guild_id: int, channel_id: int = None, state: str = 'active',
                    throw_exceptions=True,
                    eager_loads=None) -> Optional[db_event.Event]:

    if not state:
        state = 'active'

    if not guild_id:
        return None

    eager_loads = eager_loads or []

    now = datetime.now(pytz.utc)

    stmt = select(db_event.Event).filter(db_event.Event.guild_id == guild_id)

    if state == 'archived':
        stmt.filter(db_event.Event.end < now)
    elif state == 'active':
        stmt.filter(db_event.Event.start <= now)
        stmt.filter(now <= db_event.Event.end)
    elif state == 'registration':
        stmt.filter(db_event.Event.registration_start <= now)
        stmt.filter(now <= db_event.Event.registration_end)

    if state == 'archived':
        events = await db_first(
            stmt.order_by(desc(db_event.Event.end)),
            *eager_loads
        )
        events.sort(key=lambda x: x.end, reverse=True)
        event = events[0]
    else:
        event = await db_first(stmt, *eager_loads)

    if not event and throw_exceptions:
        raise UserInputError(f'There is no {"event you can register for" if state == "registration" else "active event"}')
    return event


async def delete_client(client: db_client.Client, messenger: Messenger, commit=False):
    await db_del_filter(db_client.Client, id=client.id)
    messenger.pub_channel(NameSpace.CLIENT, Category.DELETE, obj={'id': client.id})
    if commit:
        await async_session.commit()


def add_client(client: db_client.Client, messenger: Messenger):
    messenger.pub_channel(NameSpace.CLIENT, Category.NEW, obj={'id': client.id})


def get_all_events(guild_id: int, channel_id):
    pass


async def get_discord_user(user_id: int, throw_exceptions=True, require_registrations=True, eager_loads=None) -> Optional[DiscordUser]:
    """
    Tries to find a matching entry for the user and guild id.
    :param user_id: id of user to get
    :param guild_id: guild id of user to get
    :param throw_exceptions: whether to throw exceptions if user isn't registered
    :param exact: whether the global entry should be used if the guild isn't registered
    :return:
    The found user. It will never return None if throw_exceptions is True, since an ValueError exception will be thrown instead.
    """
    eager = eager_loads or [DiscordUser.clients]
    result = await db_select(DiscordUser, eager=eager, id=user_id)

    #result = session.query(DiscordUser).filter_by(user_id=user_id).first()
    if not result:
        if throw_exceptions:
            raise UserInputError("User {name} is not registered", user_id)
    elif len(result.clients) == 0 and throw_exceptions and require_registrations:
        raise UserInputError("User {name} does not have any registrations", user_id)
    return result


async def get_guild_start_end_times(event: db_event.Event, start: datetime, end: datetime, archived=False):

    start = datetime.fromtimestamp(0, pytz.utc) if not start else start
    end = datetime.now(pytz.utc) if not end else end

    if event:
        # When custom times are given make sure they don't exceed event boundaries (clients which are global might have more data)
        return max(start, event.start), min(end, event.end)
    else:
        return start, end
