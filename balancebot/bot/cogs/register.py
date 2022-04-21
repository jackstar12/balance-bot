import logging
from typing import List

import pytz
from asgiref import typing
from datetime import datetime

from discord_slash import cog_ext, SlashContext
from discord_slash.utils.manage_commands import create_option, create_choice
from sqlalchemy import inspect, select, or_

from balancebot.api.database_async import async_session, db_del_filter, db_unique, db_select_first, db_all
from balancebot.api.dbmodels.balance import Balance
from balancebot.api.dbmodels.event import Event
from balancebot.api.dbmodels.guild import Guild
from balancebot.api.dbmodels.guildassociation import GuildAssociation
from balancebot.common import utils
from balancebot.api import dbutils
from balancebot.api.database import session
from balancebot.api.dbmodels.client import Client
from balancebot.api.dbmodels.discorduser import DiscordUser
from balancebot.bot import config
from balancebot.bot.cogs.cogbase import CogBase
from balancebot.bot.config import EXCHANGES
from balancebot.common.errors import UserInputError, InternalError
from balancebot.common.messenger import Category, SubCategory
from balancebot.common.models.selectionoption import SelectionOption
from balancebot.exchangeworker import ExchangeWorker
from balancebot.common.utils import create_yes_no_button_row, create_selection, validate_kwargs


class RegisterCog(CogBase):

    @cog_ext.cog_subcommand(
        base="register",
        name="new",
        description="Register you for tracking.",
        options=[
            create_option(
                name="exchange_name",
                description="Name of exchange you are using",
                required=True,
                option_type=3,
                choices=[
                    create_choice(
                        name=key,
                        value=key
                    ) for key in EXCHANGES.keys()
                ]
            ),
            create_option(
                name="api_key",
                description="Your api Key",
                required=True,
                option_type=3
            ),
            create_option(
                name="api_secret",
                description="Your api Secret",
                required=True,
                option_type=3
            ),
            create_option(
                name="subaccount",
                description="Subaccount for api Access",
                required=False,
                option_type=3
            ),
            create_option(
                name="args",
                description="Additional arguments",
                required=False,
                option_type=3
            )
        ]
    )
    @utils.log_and_catch_errors(log_args=False)
    async def register_new(self,
                           ctx: SlashContext,
                           exchange_name: str,
                           api_key: str,
                           api_secret: str,
                           subaccount: typing.Optional[str] = None,
                           args: str = None):
        await ctx.defer(hidden=True)

        kwargs = {}
        if args:
            args = args.split(' ')
            if len(args) > 0:
                for arg in args:
                    try:
                        name, value = arg.split('=')
                        kwargs[name] = value
                    except UserInputError:
                        await ctx.send(
                            f'Invalid keyword argument: {arg}\nSyntax for keyword arguments: key1=value1 key2=value2 ...',
                            hidden=True)
                        logging.error(f'Invalid Keyword Arg {arg} passed in')

        try:
            exchange_name = exchange_name.lower()
            exchange_cls = EXCHANGES[exchange_name]
            if issubclass(exchange_cls, ExchangeWorker):
                if validate_kwargs(kwargs, exchange_cls.required_extra_args):

                    event = await dbutils.get_event(ctx.guild_id,
                                                    ctx.channel_id,
                                                    state='registration',
                                                    throw_exceptions=False,
                                                    registrations=True)

                    discord_user = await dbutils.get_discord_user(
                        ctx.author_id, throw_exceptions=False, guilds=True, global_associations=True,
                    )

                    guilds = []
                    available_guilds = []

                    if not event:
                        available_guilds = discord_user.guilds
                        if not ctx.guild_id:
                            if not available_guilds:
                                raise UserInputError("You are not in any servers you can register for")
                        else:
                            available_guilds = list(filter(lambda guild: guild.id == ctx.guild_id, available_guilds))

                    async def registration(ctx):
                        nonlocal discord_user, guilds, event

                        existing_clients = None
                        if not discord_user:
                            guilds = await db_all(
                                select(Guild).filter(
                                    or_(*[guild.id for guild in ctx.author.mutual_guilds])
                                )
                            )
                            discord_user = DiscordUser(
                                id=ctx.author.id,
                                name=ctx.author.name,
                                guilds=guilds
                            )
                        else:
                            if event:
                                for client in event.registrations:
                                    if client.discord_user_id == ctx.author_id:
                                        existing_clients = [client]
                                        break
                            else:
                                existing_clients = [await discord_user.get_global_client(guild.id, events=True) for guild in guilds]

                        def get_new_client() -> Client:
                            new_client = Client(
                                api_key=api_key,
                                api_secret=api_secret,
                                subaccount=subaccount,
                                extra_kwargs=kwargs,
                                exchange=exchange_name,
                                discorduser=discord_user
                            )
                            if event:
                                new_client.events.append(event)
                            return new_client

                        async def start_registration(ctx):

                            new_client = get_new_client()
                            worker: ExchangeWorker = exchange_cls(new_client, self.user_manager.session)
                            init_balance = await worker.get_balance(time=datetime.now(tz=pytz.UTC))

                            button_row = None
                            if init_balance.error is None:
                                if init_balance.amount < config.REGISTRATION_MINIMUM:
                                    message = f'You do not have enough balance in your account ' \
                                              f'(Minimum: {config.REGISTRATION_MINIMUM}$, Your Balance: {init_balance.amount}$).\n' \
                                              f'Please fund your account before registering.'
                                else:
                                    message = f'Your balance: **{init_balance.to_string()}**. This will be used as your initial balance. Is this correct?\nYes will register you, no will cancel the process.'

                                    button_row = create_yes_no_button_row(
                                        slash=self.slash_cmd_handler,
                                        author_id=ctx.author.id,
                                        yes_callback=lambda: self.register_user(
                                            existing_clients, get_new_client(), discord_user, init_balance, guilds,
                                            event,
                                        ),
                                        yes_message="You were successfully registered!",
                                        no_message="Registration cancelled",
                                        hidden=True
                                    )
                            else:
                                message = f'An error occured while getting your balance: {init_balance.error}.'

                            await ctx.send(
                                content=message,
                                embed=await new_client.get_discord_embed(is_global=event is None),
                                hidden=True,
                                components=[button_row] if button_row else None
                            )

                            # The new client has to be removed and can't be reused for register_user because in this case it would persist in memory
                            # if the registration is cancelled, causing bugs
                            session.add(new_client)
                            session.expunge(new_client)
                            await async_session.commit()

                        if not existing_clients:
                            await start_registration(ctx)
                        else:
                            buttons = create_yes_no_button_row(
                                slash=self.slash_cmd_handler,
                                author_id=ctx.author_id,
                                yes_callback=start_registration,
                                no_message="Registration cancelled",
                                hidden=True
                            )
                            existing = ", ".join(
                                [await existing_client.get_event_string() for existing_client in existing_clients]
                            )
                            await ctx.send(
                                content=f'You are already registered for _{existing}_.\n'
                                        f'Continuing the registration will delete your old data for _{existing}_.\n'
                                        f'Do you want to proceed?',
                                components=[buttons],
                                hidden=True
                            )

                    if not event and len(available_guilds) > 1:
                        async def on_guilds_select(ctx, selected_guilds):
                            nonlocal guilds
                            guilds = selected_guilds
                            await registration(ctx)

                        guild_selection = create_selection(
                            self.slash_cmd_handler,
                            author_id=ctx.author_id,
                            callback=on_guilds_select,
                            options=[
                                SelectionOption(
                                    name=guild.name,
                                    value=str(guild.id),
                                    description=guild.name,
                                    object=guild
                                )
                                for guild in discord_user.guilds
                            ]
                        )
                        await ctx.send(
                            content="Please select the guild you want to register for first",
                            components=[guild_selection],
                            hidden=False
                        )
                    else:
                        guilds = available_guilds
                        await registration(ctx)

                else:
                    logging.error(
                        f'Not enough kwargs for exchange {exchange_cls.exchange} were given.\nGot: {kwargs}\nRequired: {exchange_cls.required_extra_args}')
                    args_readable = ''
                    for arg in exchange_cls.required_extra_args:
                        args_readable += f'{arg}\n'
                    raise UserInputError(
                        f'Need more keyword arguments for exchange {exchange_cls.exchange}.\nRequirements:\n{args_readable}')
            else:
                raise InternalError(f'Class {exchange_cls} is no subclass of ClientWorker!')
        except KeyError:
            raise UserInputError(f'Exchange {exchange_name} unknown')

    async def register_user(self,
                            existing_clients: List[Client],
                            new_client: Client,
                            discord_user: DiscordUser,
                            init_balance: Balance,
                            guilds: List[Guild],
                            event: Event):

        if existing_clients:
            for existing_client in existing_clients:
                await dbutils.delete_client(existing_client, self.messenger, commit=False)

        new_client.discord_user_id = discord_user.id
        dbutils.add_client(new_client, self.messenger)

        if inspect(discord_user).transient:
            async_session.add(discord_user)

        async_session.add(new_client)
        await async_session.commit()
        await async_session.refresh(new_client)

        for guild in guilds:
            async_session.add(GuildAssociation(
                guild_id=guild.id,
                client_id=new_client.id,
                discorduser_id=discord_user.id
            ))

        await async_session.commit()
        await async_session.refresh(new_client)

        init_balance.client_id = new_client.id

        dbutils.add_client(new_client, self.messenger)

        await async_session.commit()

    @cog_ext.cog_subcommand(
        base="register",
        name="existing",
        description="Registers your global access to an ongoing event.",
        options=[]
    )
    @utils.log_and_catch_errors()
    @utils.server_only
    async def register_existing(self, ctx: SlashContext):
        event = await dbutils.get_event(guild_id=ctx.guild_id, state='registration')
        user = await dbutils.get_discord_user(ctx.author_id, clients=True)

        if user and event.is_free_for_registration():
            for client in user.clients:
                if client in event.registrations:
                    raise UserInputError('You are already registered for this event!')
            if user.global_client:
                if user.global_client not in event.registrations:
                    event.registrations.append(user.global_client)
                    await async_session.commit()
                    await ctx.send(f'You are now registered for _{event.name}_!', hidden=True)
                else:
                    raise UserInputError('You are already registered for this event!')
            else:
                raise UserInputError('You do not have a global access to use')
        else:
            raise UserInputError(f'Event {event.name} is not available for registration')

    @cog_ext.cog_slash(
        name="unregister",
        description="Unregisters you from tracking",
        options=[]
    )
    @utils.log_and_catch_errors()
    async def unregister(self, ctx):
        client = await dbutils.get_client(
            ctx.author.id, ctx.guild_id,
            events=True,
            discorduser=dict(global_associations=True)
        )
        event = await dbutils.get_event(ctx.guild_id, ctx.channel_id, state='registration', throw_exceptions=False,
                                        registrations=True)

        if not event or client not in event.registrations:
            event = await dbutils.get_event(ctx.guild_id, ctx.channel_id, state='active', throw_exceptions=False)

        await ctx.defer(hidden=True)

        async def start_unregistration(ctx, selections: List[Client]):

            if not selections:
                return

            selection = selections[0]

            async def unregister_user(ctx):

                # When unregistering, one of the 2 cases applies:
                # - Unregister a server bound global client
                # - Unregister an event bound client
                # - Unregister a server bound client from event

                if event:
                    selection.events.remove(event)
                    if not selection.is_active and not selection.is_global(ctx.guild_id):
                        await dbutils.delete_client(selection, self.messenger)
                else:
                    await dbutils.delete_client(selection, self.messenger)
                await async_session.commit()

                discord_user = await db_unique(
                    select(DiscordUser).filter_by(id=ctx.author_id),
                    clients=True, user=True
                )
                if len(discord_user.clients) == 0 and not discord_user.user:
                    await db_del_filter(DiscordUser, user_id=ctx.author_id)
                await async_session.commit()
                logging.info(f'Successfully unregistered user {ctx.author.display_name}')

            buttons = create_yes_no_button_row(
                slash=self.slash_cmd_handler,
                author_id=ctx.author.id,
                yes_callback=unregister_user,
                yes_message="You were succesfully unregistered!",
                no_message="Unregistration cancelled",
                hidden=True
            )
            await ctx.send(
                content=f'Do you really want to unregister from {event.name if event else await client.get_event_string()}? This will **delete all your data**.',
                embed=await client.get_discord_embed(),
                components=[buttons],
                hidden=True)

        if not ctx.guild_id:
            user = await dbutils.get_discord_user(ctx.author_id, clients=dict(events=True))
            client_select = create_selection(
                self.slash_cmd_handler,
                ctx.author_id,
                options=[
                    SelectionOption(
                        name=client.name if client.name else client.exchange,
                        value=str(client.id),
                        description=f'{f"{client.name}, " if client.name else ""}{client.exchange}, from {await client.get_event_string()}',
                        object=client
                    )
                    for client in user.clients
                ],
                callback=start_unregistration
            )
            await ctx.send(
                content=f'Please select the client you want to delete',
                components=[client_select],
                hidden=True
            )
        else:
            await start_unregistration(ctx, [client])
