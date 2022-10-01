import os
from datetime import datetime
from functools import wraps
from typing import List

import discord.ext.commands
import pytz
from discord_slash import cog_ext, SlashContext
from sqlalchemy import select, insert
from sqlalchemy.ext.asyncio import AsyncSession

from tradealpha.common.messenger import EVENT
from tradealpha.common.redis import TableNames
from tradealpha.bot import config
from tradealpha.bot import utils
from tradealpha.bot.cogs.cogbase import CogBase
from tradealpha.bot.utils import create_complete_history, get_summary_embed, get_leaderboard
from tradealpha.common import dbutils
from tradealpha.common.dbasync import db_all, db_select
from tradealpha.common.dbasync import db_select_all
from tradealpha.common.dbmodels import EventScore, Client
from tradealpha.common.dbmodels.discord.discorduser import DiscordUser
from tradealpha.common.dbmodels.event import Event
from tradealpha.common.dbmodels.event import EventState
from tradealpha.common.dbmodels.user import User
from tradealpha.common.errors import UserInputError
from tradealpha.common.models.selectionoption import SelectionOption


class EventsCog(CogBase):

    async def on_ready(self):
        await self.messenger.bulk_sub(
            Event, {
                EVENT.START: self._wrap_event_coro(self._event_start),
                EVENT.END: self._wrap_event_coro(self._event_end),
                EVENT.REGISTRATION_START: self._wrap_event_coro(self._event_registration_start),
                EVENT.REGISTRATION_END: self._wrap_event_coro(self._event_registration_end)
            }
        )

    def _get_channel(self, event: Event) -> discord.TextChannel:
        guild = self.bot.get_guild(event.guild_id)
        return guild.get_channel(event.channel_id)

    async def _event_start(self, event: Event):
        await self._get_channel(event).send(content=f'Event **{event.name}** just started!',
                                            embed=event.get_discord_embed(title="Event",
                                                                          dc_client=self.bot,
                                                                          registrations=True))

    async def _event_end(self, event: Event):
        await self._get_channel(event).send(
            content=f'Event **{event.name}** just ended! Final standings:',
            embed=await get_leaderboard(self.bot, event.guild_id, event.channel_id, since=event.start)
        )

        complete_history = await create_complete_history(self.bot, event)
        summary = await get_summary_embed(event, self.bot)
        await self._get_channel(event).send(
            embed=summary.set_image(url=f'attachment://{complete_history.filename}'),
            file=complete_history
        )

    async def _event_registration_start(self, event: Event):
        await self._get_channel(event).send(content=f'Registration period for **{event.name}** has started!')

    async def _event_registration_end(self, event: Event):
        await self._get_channel(event).send(content=f'Registration period for **{event.name}** has ended!')

    def _wrap_event_coro(self, coro):
        @wraps(coro)
        async def wrapper(data: dict):
            event = await db_select(Event,
                                    Event.location['platform'] == 'discord',
                                    Event.id == data['id'])
            if event:
                return await coro(event)
        return wrapper


    @cog_ext.cog_subcommand(
        base='event',
        subcommand_group='show'
    )
    @utils.log_and_catch_errors()
    @utils.server_only
    async def event_show(self, ctx: SlashContext):
        now = datetime.now(pytz.utc)

        events = await db_select_all(
            Event,
            Event.guild_id == str(ctx.guild_id),
            ~Event.is_expr(EventState.ARCHIVED),
            eager=[
                (Event.leaderboard, [
                    (EventScore.client, (
                        Client.user, User.oauth_accounts
                    )),
                    EventScore.init_balance
                ])
            ]
        )

        if len(events) == 0:
            await ctx.send(content='There are no events', hidden=True)
        else:
            await ctx.defer()
            for event in events:
                if event.is_active:
                    title = 'Current Event'
                else:
                    title = 'Upcoming Event'
                await ctx.send(embed=event.get_discord_embed(title, self.bot, registrations=True))

    @classmethod
    async def join_event(cls, ctx, event: Event, client: Client, db: AsyncSession):
        await db.execute(
            insert(EventScore).values(event_id=event.id, client_id=client.id)
        )
        await db.commit()
        await ctx.send(f'You are now registered for _{event.name}_!', hidden=True)

    @cog_ext.cog_subcommand(
        base="event",
        name="join",
        description="Registers your global access to an ongoing event.",
        options=[]
    )
    @utils.log_and_catch_errors()
    @utils.server_only
    @utils.with_db
    async def event_join(self, ctx: SlashContext, db: AsyncSession):

        event = await dbutils.get_discord_event(guild_id=ctx.guild_id,
                                                channel_id=ctx.channel_id,
                                                state=EventState.REGISTRATION,
                                                eager_loads=[Event.registrations])

        if event.is_(EventState.REGISTRATION):

            for client in event.registrations:
                if client.discord_user.account_id == ctx.author_id:
                    raise UserInputError('You are already registered for this event!')

            user = await dbutils.get_discord_user(ctx.author_id,
                                                  eager_loads=[(DiscordUser.clients, Client.events),
                                                               DiscordUser.global_associations],
                                                  db=db)
            global_client = await user.get_guild_client(ctx.guild_id, db=db)
            if global_client and False:
                if global_client not in event.registrations:
                    await self.join_event(ctx, event, global_client, db)
                else:
                    raise UserInputError('You are already registered for this event!')
            else:
                ctx, clients = await utils.select_client(
                    ctx=ctx,
                    dc=self.bot,
                    slash=self.slash_cmd_handler,
                    user=user,
                    max_values=1
                )
                await self.join_event(ctx, event, clients[0], db)
        else:
            raise UserInputError(f'Event {event.name} is not available for registration')

    @cog_ext.cog_slash(
        name="archive",
        description="Shows summary of archived event"
    )
    @utils.log_and_catch_errors()
    @utils.server_only
    async def archive(self, ctx: SlashContext):
        now = datetime.now(pytz.utc)

        archived = await db_all(
            select(Event).filter(
                Event.guild_id == ctx.guild_id,
                Event.end < now
            )
        )

        if len(archived) == 0:
            raise UserInputError('There are no archived events')

        async def show_events(ctx, selection: List[Event]):
            for event in selection:
                archive = event.archive

                history = None
                if os.path.exists:
                    history = discord.File(config.DATA_PATH + archive.history_path, "history.png")

                info = archive.db_event.get_discord_embed(
                    self.bot, registrations=False
                ).add_field(name="Registrations", value=archive.registrations, inline=False)

                summary = discord.Embed(
                    title="Summary",
                    description=archive.summary,
                ).set_image(url='attachment://history.png')

                leaderboard = discord.Embed(
                    title="Leaderboard :medal:",
                    description=archive.leaderboard
                )

                await ctx.send(
                    content=f'Archived results for {archive.db_event.name}',
                    embeds=[
                        info, leaderboard, summary
                    ],
                    file=history
                )

        selection_row = utils.create_selection(
            self.slash_cmd_handler,
            author_id=ctx.author_id,
            options=[
                SelectionOption(
                    name=event.name,
                    description=f'From {event.time.strftime("%Y-%m-%d")} to {event.end.strftime("%Y-%m-%d")}',
                    value=str(event.channel_id),
                    object=event,
                )
                for event in archived
            ],
            callback=show_events
        )

        await ctx.send(content='Which events do you want to display', hidden=True, components=[selection_row])

    @cog_ext.cog_slash(
        name="summary",
        description="Show event summary"
    )
    @utils.log_and_catch_errors()
    @utils.server_only
    async def summary(self, ctx: SlashContext):
        event = await dbutils.get_discord_event(ctx.guild_id,
                                                ctx.channel_id,
                                                eager_loads=[
                                                    (Event.leaderboard, [
                                                        (EventScore.client, Client.user),
                                                        EventScore.init_balance
                                                    ])
                                                ])
        await ctx.defer()
        history = await utils.create_complete_history(dc=self.bot, event=event)
        summary = await utils.get_summary_embed(event=event, dc_client=self.bot)
        await ctx.send(
            embeds=[
                await utils.get_leaderboard(self.bot, ctx.guild_id, ctx.channel_id),
                summary.set_image(url=f'attachment://{history.filename}'),
            ],
            file=history
        )
