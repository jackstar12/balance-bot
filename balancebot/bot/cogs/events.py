import os
from datetime import datetime
from typing import List

import discord.ext.commands
from discord_slash import cog_ext, SlashContext, SlashCommandOptionType
from discord_slash.utils.manage_commands import create_option

from balancebot.api.database_async import async_session
from balancebot.common import utils
from balancebot.api import dbutils
from balancebot.api.database import session
from balancebot.api.dbmodels.event import Event
from balancebot.bot import config
from balancebot.bot.cogs.cogbase import CogBase
from balancebot.common.errors import UserInputError
from balancebot.common.models.selectionoption import SelectionOption
from balancebot.common.utils import create_yes_no_button_row


class EventsCog(CogBase):

    @cog_ext.cog_subcommand(
        base='event',
        subcommand_group='show'
    )
    @utils.log_and_catch_errors()
    @utils.server_only
    async def event_show(self, ctx: SlashContext):
        now = datetime.now()

        events: List[Event] = session.query(Event).filter(
            Event.guild_id == ctx.guild_id,
            Event.end > now
        ).all()

        if len(events) == 0:
            await ctx.send(content='There are no events', hidden=True)
        else:
            await ctx.defer()
            for event in events:
                if event.is_active:
                    await ctx.send(content='Current Event:', embed=event.get_discord_embed(self.bot, registrations=True))
                else:
                    await ctx.send(content='Upcoming Event:', embed=event.get_discord_embed(self.bot, registrations=True))

    @cog_ext.cog_subcommand(
        base="event",
        name="register",
        options=[
            create_option(
                name=name,
                description=description,
                required=True,
                option_type=SlashCommandOptionType.STRING
            )
            for name, description in
            [
                ("name", "Name of the event"),
                ("description", "Description of the event"),
                ("start", "Start of the event"),
                ("end", "End of the event"),
                ("registration_start", "Start of registration period"),
                ("registration_end", "End of registration period")
            ]
        ]
    )
    @utils.log_and_catch_errors()
    @utils.server_only
    @utils.admin_only
    @utils.time_args(names=[('start', None), ('end', None), ('registration_start', None), ('registration_end', None)],
                     allow_future=True)
    async def register_event(self, ctx: SlashContext, name: str, description: str, start: datetime, end: datetime,
                             registration_start: datetime, registration_end: datetime):
        if start >= end:
            raise UserInputError("Start time can't be after end time.")
        if registration_start >= registration_end:
            raise UserInputError("Registration start can't be after registration end")
        if registration_end < start:
            raise UserInputError("Registration end should be after or at event start")
        if registration_end > end:
            raise UserInputError("Registration end can't be after event end.")
        if registration_start > start:
            raise UserInputError("Registration start should be before event start.")

        active_event = dbutils.get_event(ctx.guild_id, ctx.channel_id, throw_exceptions=False)

        if active_event:
            if start < active_event.end:
                raise UserInputError(f"Event can't start while other event ({active_event.name}) is still active")
            if registration_start < active_event.registration_end:
                raise UserInputError(
                    f"Event registration can't start while other event ({active_event.name}) is still open for registration")

        active_registration = dbutils.get_event(ctx.guild_id, ctx.channel_id, state='registration',
                                                throw_exceptions=False)

        if active_registration:
            if registration_start < active_registration.registration_end:
                raise UserInputError(
                    f"Event registration can't start while other event ({active_registration.name}) is open for registration")

        event = Event(
            name=name,
            description=description,
            start=start,
            end=end,
            registration_start=registration_start,
            registration_end=registration_end,
            guild_id=ctx.guild_id,
            channel_id=ctx.channel_id
        )

        async def register(ctx: SlashContext):
            session.add(event)
            await async_session.commit()
            self.event_manager.register(event)

        row = create_yes_no_button_row(
            slash=self.slash_cmd_handler,
            author_id=ctx.author_id,
            yes_callback=register,
            yes_message="Event was successfully created",
            no_message="Event creation cancelled",
            hidden=True
        )

        await ctx.send(embed=event.get_discord_embed(dc_client=self.bot), components=[row], hidden=True)

    @cog_ext.cog_slash(
        name="archive",
        description="Shows summary of archived event"
    )
    @utils.log_and_catch_errors()
    @utils.server_only
    async def archive(self, ctx: SlashContext):
        now = datetime.now()

        archived = session.query(Event).filter(
            Event.guild_id == ctx.guild_id,
            Event.end < now
        ).all()

        if len(archived) == 0:
            raise UserInputError('There are no archived events')

        async def show_events(ctx, selection: List[Event]):
            for event in selection:
                archive = event.archive

                history = None
                if os.path.exists:
                    history = discord.File(config.DATA_PATH + archive.history_path, "history.png")

                info = archive.event.get_discord_embed(
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
                    content=f'Archived results for {archive.event.name}',
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
                    description=f'From {event.start.strftime("%Y-%m-%d")} to {event.end.strftime("%Y-%m-%d")}',
                    value=str(event.id),
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
        event = dbutils.get_event(ctx.guild_id, ctx.channel_id, state='active')
        await ctx.defer()
        history = await event.create_complete_history(dc_client=self.bot)
        await ctx.send(
            embeds=[
                await event.create_leaderboard(self.bot),
                await event.get_summary_embed(dc_client=self.bot).set_image(url=f'attachment://{history.filename}'),
            ],
            file=history
        )

    @cog_ext.cog_subcommand(
        base="leaderboard",
        name="balance",
        description="Shows you the highest ranked users by $ balance",
        options=[]
    )
    @utils.log_and_catch_errors()
    @utils.server_only
    async def leaderboard_balance(self, ctx: SlashContext):
        await ctx.defer()
        await ctx.send(content='',
                       embed=await utils.create_leaderboard(dc_client=self.bot, guild_id=ctx.guild_id, mode='balance',
                                                            time=None))

    @cog_ext.cog_subcommand(
        base="leaderboard",
        name="gain",
        description="Shows you the highest ranked users by % gain",
        options=[
            create_option(
                name="time",
                description="Timeframe for gain. If not specified, gain since start will be used.",
                required=False,
                option_type=SlashCommandOptionType.STRING
            )
        ]
    )
    @utils.log_and_catch_errors()
    @utils.time_args(names=[('time', None)])
    @utils.server_only
    async def leaderboard_gain(self, ctx: SlashContext, time: datetime = None):
        await ctx.defer()
        await ctx.send(content='',
                       embed=await utils.create_leaderboard(dc_client=self.bot, guild_id=ctx.guild_id, mode='gain',
                                                            time=time))

