import logging

from asgiref import typing
from datetime import datetime

from discord_slash import cog_ext, SlashContext
from discord_slash.utils.manage_commands import create_option, create_choice
from sqlalchemy import inspect

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
from balancebot.exchangeworker import ExchangeWorker
from balancebot.common.utils import create_yes_no_button_row


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
                # Check if required keyword args are given
                if len(kwargs.keys()) >= len(exchange_cls.required_extra_args) and \
                        all(required_kwarg in kwargs for required_kwarg in exchange_cls.required_extra_args):
                    event = dbutils.get_event(ctx.guild_id, ctx.channel_id, state='registration',
                                              throw_exceptions=False)
                    existing_client = None

                    discord_user = session.query(DiscordUser).filter_by(user_id=ctx.author_id).first()
                    if not discord_user:
                        discord_user = DiscordUser(
                            user_id=ctx.author.id,
                            name=ctx.author.name
                        )
                    else:
                        if event:
                            for client in event.registrations:
                                if client.discorduser.user_id == ctx.author_id:
                                    existing_client = client
                                    break
                        else:
                            existing_client = discord_user.global_client

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
                        init_balance = await worker.get_balance(datetime.now())

                        if init_balance.error is None:
                            if init_balance.amount < config.REGISTRATION_MINIMUM:
                                message = f'You do not have enough balance in your account ' \
                                          f'(Minimum: {config.REGISTRATION_MINIMUM}$, Your Balance: {init_balance.amount}$).\n' \
                                          f'Please fund your account before registering.'
                                button_row = None
                            else:
                                message = f'Your balance: **{init_balance.to_string()}**. This will be used as your initial balance. Is this correct?\nYes will register you, no will cancel the process.'

                                async def register_user(ctx):
                                    if existing_client:
                                        await dbutils.delete_client(existing_client, self.messenger, commit=False)

                                    new_client = get_new_client()

                                    if not discord_user.global_client or event is None:
                                        discord_user.global_client = new_client
                                        discord_user.global_client_id = new_client.id

                                    discord_user.clients.append(new_client)

                                    new_client.history.append(init_balance)
                                    dbutils.add_client(new_client, self.messenger)

                                    if inspect(discord_user).transient:
                                        session.add(discord_user)

                                    session.add(new_client)
                                    session.commit()
                                    dbutils.add_client(new_client, self.messenger)
                                    logging.info(f'Registered new user')

                                button_row = create_yes_no_button_row(
                                    slash=self.slash_cmd_handler,
                                    author_id=ctx.author.id,
                                    yes_callback=register_user,
                                    yes_message="You were successfully registered!",
                                    no_message="Registration cancelled",
                                    hidden=True
                                )
                        else:
                            message = f'An error occured while getting your balance: {init_balance.error}.'
                            button_row = None

                        await ctx.send(
                            content=message,
                            embed=new_client.get_discord_embed(is_global=event is None),
                            hidden=True,
                            components=[button_row] if button_row else None
                        )

                        # The new client has to be removed and can't be reused for register_user because in this case it would persist in memory
                        # if the registration is cancelled, causing bugs
                        session.add(new_client)
                        session.expunge(new_client)
                        session.commit()

                    if not existing_client:
                        await start_registration(ctx)
                    else:
                        buttons = create_yes_no_button_row(
                            slash=self.slash_cmd_handler,
                            author_id=ctx.author_id,
                            yes_callback=start_registration,
                            no_message="Registration cancelled",
                            hidden=True
                        )
                        await ctx.send(
                            content=f'You are already registered for _{existing_client.get_event_string()}_.\n'
                                    f'Continuing the registration will delete your old data for _{existing_client.get_event_string()}_.\n'
                                    f'Do you want to proceed?',
                            components=[buttons],
                            hidden=True
                        )
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

    @cog_ext.cog_subcommand(
        base="register",
        name="existing",
        description="Registers your global access to an ongoing event.",
        options=[]
    )
    @utils.log_and_catch_errors()
    @utils.server_only
    async def register_existing(self, ctx: SlashContext):
        event = dbutils.get_event(guild_id=ctx.guild_id, state='registration')
        user = dbutils.get_user(ctx.author_id)

        if user and event.is_free_for_registration:
            for client in user.clients:
                if client in event.registrations:
                    raise UserInputError('You are already registered for this event!')
            if user.global_client:
                if user.global_client not in event.registrations:
                    event.registrations.append(user.global_client)
                    session.commit()
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
        client = dbutils.get_client(ctx.author.id, ctx.guild_id, registration=True)
        event = dbutils.get_event(ctx.guild_id, ctx.channel_id, state='registration', throw_exceptions=False)

        if not event or not client in event.registrations:
            event = dbutils.get_event(ctx.guild_id, ctx.channel_id, state='active', throw_exceptions=False)

        await ctx.defer(hidden=True)

        async def unregister_user(ctx):
            if event:
                client.events.remove(event)
                if not client.is_active and not client.is_global:
                    await dbutils.delete_client(client, self.messenger)
            else:
                await dbutils.delete_client(client, self.messenger)
            session.commit()

            discord_user: DiscordUser = session.query(DiscordUser).filter_by(user_id=ctx.author_id).first()
            if len(discord_user.clients) == 0 and not discord_user.user:
                session.query(DiscordUser).filter_by(user_id=ctx.author_id).delete()
            session.commit()
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
            content=f'Do you really want to unregister from {event.name if event else client.get_event_string()}? This will **delete all your data**.',
            embed=client.get_discord_embed(),
            components=[buttons],
            hidden=True)

