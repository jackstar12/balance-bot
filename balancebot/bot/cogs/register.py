import logging
from typing import List

import aiohttp
import pytz
from asgiref import typing
from datetime import datetime

from discord_slash import cog_ext, SlashContext
from discord_slash.utils.manage_commands import create_option, create_choice
from sqlalchemy import inspect, select, or_, update, insert

from balancebot.common.database_async import async_session, db_unique, db_all, db, db_select, async_maker
from balancebot.common.dbmodels.balance import Balance
from balancebot.common.dbmodels.event import Event, event_association
from balancebot.common.dbmodels.guild import Guild
from balancebot.common.dbmodels.guildassociation import GuildAssociation
from balancebot.common import dbutils
from balancebot.common.dbmodels.client import Client
from balancebot.common.dbmodels.discorduser import DiscordUser
from balancebot.bot import config, utils
from balancebot.bot.cogs.cogbase import CogBase
from balancebot.common.exchanges import EXCHANGES
from balancebot.common.errors import UserInputError, InternalError
from balancebot.common.models.selectionoption import SelectionOption
from balancebot.common.exchanges.exchangeworker import ExchangeWorker


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
        slash = ctx.slash
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
                if utils.validate_kwargs(kwargs, exchange_cls.required_extra_args):

                    event = await dbutils.get_event(ctx.guild_id,
                                                    ctx.channel_id,
                                                    state='registration',
                                                    throw_exceptions=False,
                                                    eager_loads=[Event.registrations])

                    discord_user = await dbutils.get_discord_user(
                        ctx.author_id, throw_exceptions=False,
                        eager_loads=[DiscordUser.guilds, DiscordUser.global_associations],
                    )

                    guilds = []
                    existing_clients = []

                    if discord_user:
                        if event:
                            for client in event.registrations:
                                if client.discord_user_id == ctx.author_id:
                                    existing_clients = [client]
                                    break
                        else:
                            available_guilds = discord_user.guilds
                            if not ctx.guild_id:
                                if not available_guilds:
                                    raise UserInputError("You are not in any servers you can register for")
                            else:
                                available_guilds = list(filter(lambda guild: guild.id == ctx.guild_id, available_guilds))
                            if len(available_guilds) > 1:
                                ctx, guilds = await utils.new_create_selection(
                                    ctx,
                                    options=[
                                        SelectionOption(
                                            name=guild.name,
                                            value=str(guild.id),
                                            description=guild.name,
                                            object=guild
                                        )
                                        for guild in discord_user.guilds
                                    ],
                                    msg_content="Please select the guild you want to register for first",
                                )
                            else:
                                guilds = available_guilds
                            for guild in guilds:
                                existing_client = await discord_user.get_global_client(guild.id, Client.events)
                                if existing_client:
                                    existing_clients.append(existing_client)
                    else:
                        guilds = await db_all(
                            select(Guild).filter(
                                or_(*[Guild.id == guild.id for guild in ctx.author.mutual_guilds])
                            )
                        )
                        discord_user = DiscordUser(
                            id=ctx.author.id,
                            name=ctx.author.name,
                            guilds=guilds
                        )

                    new_client = Client(
                        api_key=api_key,
                        api_secret=api_secret,
                        subaccount=subaccount,
                        extra_kwargs=kwargs,
                        exchange=exchange_name
                    )

                    if existing_clients:
                        existing = ", ".join(
                            [await existing_client.get_events_and_guilds_string() for existing_client in existing_clients]
                        )
                        ctx, consent = await utils.ask_for_consent(
                            ctx, slash,
                            msg_content=f'You are already registered for _{existing}_.\n'
                                        f'Continuing the registration will delete your old data for _{existing}_.\n'
                                        f'Do you want to proceed?',
                            no_message="Registration cancelled",
                            hidden=True
                        )
                        if not consent:
                            return

                    async with aiohttp.ClientSession() as session, async_maker() as db_session:
                        worker: ExchangeWorker = exchange_cls(new_client, session, db_session)
                        init_balance = await worker.get_balance(date=datetime.now(tz=pytz.UTC), return_cls=Balance)

                    button_row = None
                    if init_balance.error is None:
                        if init_balance.unrealized < config.REGISTRATION_MINIMUM:
                            error = f'You do not have enough balance in your account ' \
                                    f'(Minimum: {config.REGISTRATION_MINIMUM}$, Your Balance: {init_balance.unrealized}$).\n' \
                                    f'Please fund your account before registering.'
                        else:
                            ctx, consent = await utils.ask_for_consent(
                                ctx, slash,
                                msg_content=f'Your balance: **{init_balance.to_string()}**.\n'
                                            f'This will be used as your initial balance. Is this correct?\n'
                                            f'Yes will register you, no will cancel the process.',
                                msg_embeds=[await new_client.get_discord_embed(guilds=guilds)],
                                yes_message="You were successfully registered!",
                                no_message="Registration cancelled",
                                hidden=True,
                                timeout_seconds=90
                            )
                            if consent:
                                await self.register_user(
                                    existing_clients, new_client, discord_user, init_balance, guilds, event
                                )
                            return
                            #button_row = create_yes_no_button_row(
                            #    slash=self.slash_cmd_handler,
                            #    author_id=ctx.author.id,
                            #    yes_callback=lambda component_ctx: self.register_user(
                            #        existing_clients, new_client, discord_user, init_balance, guilds,
                            #        event,
                            #    ),
                            #    yes_message="You were successfully registered!",
                            #    no_message="Registration cancelled",
                            #    hidden=True
                            #)
                    else:
                        error = f'An error occured while getting your balance: {init_balance.error}.'

                    await ctx.send(
                        content=error,
                        embed=await new_client.get_discord_embed(guilds=guilds),
                        hidden=True,
                    )

                    # The new client has to be removed and can't be reused for register_user because in this case it would persist in memory
                    # if the registration is cancelled, causing bugs
                    async_session.add(new_client)
                    async_session.expunge(new_client)
                    await async_session.commit()
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

        if inspect(discord_user).transient:
            async_session.add(discord_user)

        async_session.add(new_client)
        await async_session.commit()
        await async_session.refresh(new_client)

        for guild in guilds:
            await db(
                update(GuildAssociation).where(
                    GuildAssociation.discord_user_id == new_client.discord_user_id,
                    GuildAssociation.guild_id == guild.id
                ).values(client_id=new_client.id)
            )

        await async_session.commit()
        if event:
            await db(
                insert(event_association).values(event_id=event.id, client_id=new_client.id)
            )
        init_balance.client_id = new_client.id

        dbutils.add_client(new_client, self.messenger)

        await async_session.commit()

    async def register_client(self, ctx, event: Event, client: Client):
        await db(
            insert(event_association).values(event_id=event.id, client_id=client.id)
        )
        await async_session.commit()
        await ctx.send(f'You are now registered for _{event.name}_!', hidden=True)

    @cog_ext.cog_subcommand(
        base="register",
        name="existing",
        description="Registers your global access to an ongoing event.",
        options=[]
    )
    @utils.log_and_catch_errors()
    @utils.server_only
    async def register_existing(self, ctx: SlashContext):
        event = await dbutils.get_event(guild_id=ctx.guild_id, state='registration', eager_loads=[Event.registrations])

        if event.is_free_for_registration():
            for client in event.registrations:
                if client.discord_user_id == ctx.author_id:
                    raise UserInputError('You are already registered for this event!')
            user = await dbutils.get_discord_user(ctx.author_id, eager_loads=[(DiscordUser.clients, Client.events),
                                                                              DiscordUser.global_associations])
            global_client = await user.get_global_client(ctx.guild_id)
            if global_client:
                if global_client not in event.registrations:
                    await self.register_client(ctx, event, global_client)
                else:
                    raise UserInputError('You are already registered for this event!')
            else:
                await ctx.send(
                    content='Please select the client you want to register for this event.',
                    components=[await utils.select_client(
                        user,
                        self.slash_cmd_handler,
                        lambda select_ctx, clients: self.register_client(select_ctx, event, clients[0])
                    )],
                    hidden=True
                )
        else:
            raise UserInputError(f'Event {event.name} is not available for registration')

    async def unregister_user(self, ctx, event: Event, client: Client, remove_guild: bool):

        # When unregistering, one of the 2 cases applies:
        # - Unregister a server bound global client
        # - Unregister an event bound client
        # - Unregister a server bound client from event

        if event:
            client.events.remove(event)
            if not client.is_active and not await client.is_global(ctx.guild_id):
                await dbutils.delete_client(client, self.messenger)
        elif remove_guild:
            await db(
                update(GuildAssociation).where(
                    GuildAssociation.client_id == client.id,
                    GuildAssociation.discord_user_id == client.discord_user_id,
                    GuildAssociation.guild_id == ctx.guild_id
                ).values(client_id=None)
            )
        else:
            await dbutils.delete_client(client, self.messenger)
        await async_session.commit()

        discord_user = await db_select(
            DiscordUser,
            eager=[DiscordUser.clients, DiscordUser.user],
            id=ctx.author_id
        )
        if len(discord_user.clients) == 0 and not discord_user.user:
            await async_session.delete(discord_user)
            await async_session.commit()
        logging.info(f'Successfully unregistered user {ctx.author.display_name}')

    @cog_ext.cog_slash(
        name="unregister",
        description="Unregisters you from tracking",
        options=[]
    )
    @utils.log_and_catch_errors()
    async def unregister(self, ctx):

        async def start_unregistration(ctx, selections: List[Client]):

            event = await dbutils.get_event(ctx.guild_id, ctx.channel_id, state='registration', throw_exceptions=False,
                                            eager_loads=[Event.registrations])

            client = selections[0]

            if not event or client not in event.registrations:
                event = await dbutils.get_event(
                    ctx.guild_id,
                    ctx.channel_id,
                    state='active',
                    throw_exceptions=False,
                    eager_loads=[Event.registrations])

            remove_guild = False
            if not event:
                if ctx.guild_id:
                    remove_guild = await client.is_global(ctx.guild_id)
                    if remove_guild:
                        message = f'Do you really want to remove this account from _{ctx.guild.name}_?'
                        success_message = f'Successfully unregistered you from _{ctx.guild.name}_.' \
                                          f'\nIf you want to completely delete this account, repeat this process in the DM'
                    else:
                        raise InternalError(f"Client {client=} should be global, but {remove_guild}")
                else:
                    message = f'Do you really want to delete this account? **All your data will be gone**'
                    success_message = f'Successfully deleted all data related to this account.'
            else:
                message = f'Do you really want to unregister from _{event.name}_?'
                success_message = f'Successfully unregistered you from _{event.name}_'

            if not selections:
                return

            buttons = utils.create_yes_no_button_row(
                slash=self.slash_cmd_handler,
                author_id=ctx.author.id,
                yes_callback=lambda ctx: self.unregister_user(ctx, event, client, remove_guild),
                yes_message=success_message,
                no_message="Unregistration cancelled",
                hidden=True
            )
            await ctx.send(
                content=message,
                embed=await client.get_discord_embed(),
                components=[buttons],
                hidden=True)

        if not ctx.guild_id:
            user = await dbutils.get_discord_user(ctx.author_id, eager_loads=[(DiscordUser.clients, Client.events),
                                                                              DiscordUser.global_associations])
            await ctx.defer()
            if len(user.clients) > 1:
                ctx, clients = await utils.select_client(ctx, self.slash_cmd_handler, user)

            else:
                await start_unregistration(ctx, user.clients)
        else:
            client = await dbutils.get_client(
                ctx.author.id, ctx.guild_id,
                client_eager=[Client.events],
                discord_user_eager=[DiscordUser.global_associations]
            )
            await start_unregistration(ctx, [client])
