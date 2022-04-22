from __future__ import annotations
from datetime import datetime

import pytz
from sqlalchemy import select, desc
from sqlalchemy.orm import joinedload
from sqlalchemy.sql import Select

from balancebot.api.database import session
import balancebot.api.dbmodels.client as db_client
from balancebot.api.database_async import async_session, db_first, db_eager, db, db_del_filter, db_unique, db_all, \
    db_select
from balancebot.api.dbmodels.guildassociation import GuildAssociation
from balancebot.api.dbmodels.discorduser import DiscordUser
import balancebot.api.dbmodels.event as db_event
from typing import Optional
from balancebot.common.errors import UserInputError
from balancebot.common.messenger import Messenger, Category, SubCategory


async def get_client(user_id: int,
                     guild_id: int = None,
                     registration=False,
                     throw_exceptions=True,
                     client_eager=True,
                     discord_user_eager=None) -> Optional[db_client.Client]:
    discord_user_eager = discord_user_eager or {}
    user = await get_discord_user(user_id, throw_exceptions=throw_exceptions, clients=client_eager, global_client=True, guilds=True, **discord_user_eager)
    if user:
        if guild_id:
            if registration:
                event = await get_event(guild_id, state='registration', throw_exceptions=False, registrations=True)
                if event:
                    for client in event.registrations:
                        if client.discord_user_id == user_id:
                            return client

            event = await get_event(guild_id, state='active', throw_exceptions=False, registrations=True)
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

        if len(user.global_associations) == 1:
            return
        if user.global_client:
            if not guild_id:
                return user.global_client
            for guild in user.global_client.guilds:
                if guild.id == guild_id:
                    return user.global_client
        elif throw_exceptions:
            raise UserInputError("User {name} does not have a global registration", user_id)
    elif throw_exceptions:
        raise UserInputError("User {name} is not registered", user_id)


async def get_event(guild_id: int, channel_id: int = None, state: str = 'active',
                    throw_exceptions=True,
                    **eager_loads) -> Optional[db_event.Event]:

    if not state:
        state = 'active'

    if not guild_id:
        return None

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
            **eager_loads
        )
        events.sort(key=lambda x: x.end, reverse=True)
        event = events[0]
    else:
        event = await db_first(stmt, **eager_loads)

    if not event and throw_exceptions:
        raise UserInputError(f'There is no {"event you can register for" if state == "registration" else "active event"}')
    return event


async def delete_client(client: db_client.Client, messenger: Messenger, commit=False):
    await db_del_filter(db_client.Client, id=client.id)
    #session.query(db_client.Client).filter_by(id=client.id).delete()
    messenger.pub_channel(Category.CLIENT, SubCategory.DELETE, obj=client.id)
    if commit:
        await async_session.commit()


def add_client(client: db_client.Client, messenger: Messenger):
    messenger.pub_channel(Category.CLIENT, SubCategory.NEW, obj=client.id)


def get_all_events(guild_id: int, channel_id):
    pass


async def get_discord_user(user_id: int, throw_exceptions=True, clients=True, **kwargs) -> Optional[DiscordUser]:
    """
    Tries to find a matching entry for the user and guild id.
    :param user_id: id of user to get
    :param guild_id: guild id of user to get
    :param throw_exceptions: whether to throw exceptions if user isn't registered
    :param exact: whether the global entry should be used if the guild isn't registered
    :return:
    The found user. It will never return None if throw_exceptions is True, since an ValueError exception will be thrown instead.
    """
    result = await db_unique(
        db_eager(
            select(DiscordUser),
            clients=clients,
            **kwargs
        ),
    )

    #result = session.query(DiscordUser).filter_by(user_id=user_id).first()
    if not result and throw_exceptions:
        raise UserInputError("User {name} is not registered", user_id)
    if len(result.clients) == 0 and throw_exceptions:
        raise UserInputError("User {name} does not have any registrations", user_id)
    return result


async def get_guild_start_end_times(guild_id, start, end, archived=False):

    start = datetime.fromtimestamp(0) if not start else start
    end = datetime.now(pytz.utc) if not end else end
    event = await get_event(guild_id, state='archived' if archived else 'active', throw_exceptions=False)

    if event:
        # When custom times are given make sure they don't exceed event boundaries (clients which are global might have more data)
        return max(start, event.start), min(end, event.end)
    else:
        return start, end
