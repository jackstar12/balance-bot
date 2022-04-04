from datetime import datetime
from typing import List

import discord.ext.commands as commands
from discord_slash import cog_ext, SlashContext, SlashCommandOptionType
from discord_slash.utils.manage_commands import create_option

from balancebot import utils
from balancebot.api import dbutils
from balancebot.api.database import session
from balancebot.api.dbmodels.event import Event
from balancebot.errors import UserInputError
from balancebot.utils import create_yes_no_button_row


class EventCog(commands.Cog):

    @cog_ext.cog_subcommand(
        base='event',
        subcommand_group='show'
    )
    @utils.log_and_catch_errors()
    @utils.server_only
    async def event_show(ctx: SlashContext):
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
                    await ctx.send(content='Current Event:', embed=event.get_discord_embed(bot, registrations=True))
                else:
                    await ctx.send(content='Upcoming Event:', embed=event.get_discord_embed(bot, registrations=True))

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

        def register(ctx):
            session.add(event)
            session.commit()
            event_manager.register(event)

        row = create_yes_no_button_row(
            slash=slash,
            author_id=ctx.author_id,
            yes_callback=register,
            yes_message="Event was successfully created",
            no_message="Event creation cancelled",
            hidden=True
        )

        await ctx.send(embed=event.get_discord_embed(dc_client=bot), components=[row], hidden=True)
