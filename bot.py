import logging
import argparse
import datetime as datetime
import logging
import os
import random
import shutil
import time
import typing
from datetime import datetime
from typing import List, Dict, Type, Tuple

import dotenv
dotenv.load_dotenv()

import discord
import discord.errors
from discord import Embed
from discord.ext import commands
from discord_slash import SlashCommand, SlashContext, SlashCommandOptionType
from discord_slash.utils.manage_commands import create_choice, create_option
from sqlalchemy import inspect

import api.dbutils as dbutils
import api.app as api
import utils
from Exchanges.binance.binance import BinanceFutures, BinanceSpot
from Exchanges.bitmex import BitmexClient
from Exchanges.bybit import BybitClient
from Exchanges.ftx.ftx import FtxClient
from Exchanges.kucoin import KuCoinClient
from api.database import db
from api.dbmodels.client import Client
from api.dbmodels.discorduser import DiscordUser
from api.dbmodels.event import Event
from api.dbmodels.archive import Archive
from clientworker import ClientWorker
from config import (DATA_PATH,
                    PREFIX,
                    FETCHING_INTERVAL_HOURS,
                    REKT_MESSAGES,
                    LOG_OUTPUT_DIR,
                    REKT_GUILDS,
                    CURRENCY_PRECISION,
                    REKT_THRESHOLD,
                    ARCHIVE_PATH)
from errors import UserInputError, InternalError
from eventmanager import EventManager
from usermanager import UserManager
from utils import (de_emojify,
                   create_yes_no_button_row)
from threading import Thread

intents = discord.Intents().default()
intents.members = True
intents.guilds = True

bot = commands.Bot(command_prefix=PREFIX, intents=intents)
slash = SlashCommand(bot)

EXCHANGES: Dict[str, Type[ClientWorker]] = {
    'binance-futures': BinanceFutures,
    'binance-spot': BinanceSpot,
    'bitmex': BitmexClient,
    'ftx': FtxClient,
    'kucoin': KuCoinClient,
    'bybit': BybitClient
}


@bot.event
async def on_ready():
    user_manager.start_fetching()
    event_manager.initialize_events()

    logger.info('Bot Ready')
    print('Bot Ready')
    rate_limit = True
    while rate_limit:
        try:
            await slash.sync_all_commands(delete_from_unused_guilds=True)
            rate_limit = False
        except discord.errors.HTTPException as e:
            if e.status == 429:
                print('We are being rate limited. Will retry in 10 seconds...')
                time.sleep(10)
            else:
                raise e
    print('Done syncing')


@bot.event
async def on_guild_join(guild: discord.Guild):
    commands = [slash.commands['register'], slash.commands['unregister'], slash.commands['clear']]

    for command in commands:
        for option in command.options:
            if option['name'] == 'guild':
                option['choices'].append(
                    create_choice(
                        name=guild.name,
                        value=guild.id
                    )
                )
    await slash.sync_all_commands(delete_from_unused_guilds=True)


@slash.slash(
    name="ping",
    description="Ping"
)
@utils.log_and_catch_errors()
async def ping(ctx: SlashContext):
    """Get the bot's current websocket and api latency."""
    start_time = time.time()
    message = discord.Embed(title="Testing Ping...")
    msg = await ctx.send(embed=message)
    end_time = time.time()
    message2 = discord.Embed(
        title=f":ping_pong:\nExternal: {round(bot.latency * 1000, ndigits=3)}ms\nInternal: {round((end_time - start_time), ndigits=3)}s")
    await msg.edit(embed=message2)


@slash.slash(
    name="balance",
    description="Gives balance of user",
    options=[
        create_option(
            name="user",
            description="User to get balance for",
            required=False,
            option_type=6
        ),
        create_option(
            name="currency",
            description="Currency to show. Not supported for all exchanges",
            required=False,
            option_type=3
        )
    ]
)
@utils.log_and_catch_errors()
@utils.set_author_default(name='user')
async def balance(ctx: SlashContext, user: discord.Member = None, currency: str = None):
    if currency is None:
        currency = '$'
    currency = currency.upper()

    if ctx.guild is not None:
        registered_user = dbutils.get_client(user.id, ctx.guild.id)

        await ctx.defer()
        usr_balance = user_manager.get_client_balance(registered_user, currency)
        if usr_balance.error is None:
            await ctx.send(f'{user.display_name}\'s balance: {usr_balance.to_string()}')
        else:
            await ctx.send(f'Error while getting {user.display_name}\'s balance: {usr_balance.error}')
    else:
        user = dbutils.get_user(ctx.author_id)
        await ctx.defer()

        for user_client in user.clients:
            usr_balance = user_manager.get_client_balance(user_client, currency)
            balance_message = f'Your balance ({user_client.get_event_string()}): '
            if usr_balance.error is None:
                await ctx.send(f'{balance_message}{usr_balance.to_string()}')
            else:
                await ctx.send(
                    f'Error while getting your balance ({user_client.get_event_string()}): {usr_balance.error}')


@slash.slash(
    name="history",
    description="Draws balance history of a user",
    options=[
        create_option(
            name="user",
            description="User to graph",
            required=False,
            option_type=SlashCommandOptionType.USER
        ),
        create_option(
            name="compare",
            description="Users to compare with",
            required=False,
            option_type=SlashCommandOptionType.STRING
        ),
        create_option(
            name="since",
            description="Start time for graph",
            required=False,
            option_type=SlashCommandOptionType.STRING
        ),
        create_option(
            name="to",
            description="End time for graph",
            required=False,
            option_type=SlashCommandOptionType.STRING
        ),
        create_option(
            name="currency",
            description="Currency to display history for (only available for some exchanges)",
            required=False,
            option_type=SlashCommandOptionType.STRING
        )
    ]
)
@utils.log_and_catch_errors()
@utils.set_author_default(name='user')
@utils.time_args(names=[('since', None), ('to', None)])
async def history(ctx: SlashContext,
                  user: discord.Member = None,
                  compare: str = None,
                  since: datetime = None,
                  to: datetime = None,
                  currency: str = None):
    if ctx.guild:
        registered_client = dbutils.get_client(user.id, ctx.guild.id)
        registrations = [(registered_client, user.display_name)]
    else:
        registered_user = dbutils.get_user(user.id)
        registrations = [
            (client, client.get_event_string()) for client in registered_user.clients
        ]

    if compare:
        members_raw = compare.split(' ')
        if len(members_raw) > 0:
            for member_raw in members_raw:
                if len(member_raw) > 3:
                    # ID Format: <@!373964325091672075>
                    #         or <@373964325091672075>
                    for pos in range(len(member_raw)):
                        if member_raw[pos].isnumeric():
                            member_raw = member_raw[pos:-1]
                            break
                    try:
                        member = ctx.guild.get_member(int(member_raw))
                    except ValueError:
                        # Could not cast to integer
                        continue
                    if member:
                        registered_client = dbutils.get_client(member.id, ctx.guild.id)
                        registrations.append((registered_client, member.display_name))

    if currency is None:
        if len(registrations) > 1:
            currency = '%'
        else:
            currency = '$'
    currency = currency.upper()
    currency_raw = currency
    if '%' in currency:
        percentage = True
        currency = currency.rstrip('%')
        currency = currency.rstrip()
        if not currency:
            currency = '$'
    else:
        percentage = False

    await ctx.defer()

    utils.create_history(
        to_graph=registrations,
        guild_id=ctx.guild_id,
        start=since,
        end=to,
        currency_display=currency_raw,
        currency=currency,
        percentage=percentage,
        path=DATA_PATH + "tmp.png"
    )

    file = discord.File(DATA_PATH + "tmp.png", "history.png")

    await ctx.send(content='', file=file)


@slash.slash(
    name="gain",
    description="Calculate gain",
    options=[
        create_option(
            name="user",
            description="User to calculate gain for",
            required=False,
            option_type=6
        ),
        create_option(
            name="time",
            description="Time frame for gain. Default is start",
            required=False,
            option_type=3
        ),
        create_option(
            name="currency",
            description="Currency to calculate gain for",
            required=False,
            option_type=3
        )
    ]
)
@utils.log_and_catch_errors()
@utils.time_args(names=[('time', None)])
@utils.set_author_default(name='user')
async def gain(ctx: SlashContext, user: discord.Member, time: datetime = None, currency: str = None):
    if currency is None:
        currency = '$'
    currency = currency.upper()

    if ctx.guild:
        registered_client = dbutils.get_client(user.id, ctx.guild_id)
        clients = [registered_client]
    else:
        user = dbutils.get_user(ctx.author_id)
        clients = user.clients

    since_start = time is None
    time_str = utils.readable_time(time)

    await ctx.defer()

    user_manager.fetch_data(clients=clients)
    user_gains = utils.calc_gains(clients, ctx.guild_id, time, currency)

    for cur_client, user_gain in user_gains:
        guild = bot.get_guild(ctx.guild_id)
        if ctx.guild:
            gain_message = f'{user.display_name}\'s gain {"" if since_start else time_str}: '
        else:
            
            gain_message = f"Your gain ({cur_client.get_event_string()}): " if not guild else f"Your gain on {guild}: "
        if user_gain is None:
            logger.info(
                f'Not enough data for calculating {de_emojify(user.display_name)}\'s {time_str} gain on guild {guild}')
            if ctx.guild:
                await ctx.send(f'Not enough data for calculating {user.display_name}\'s {time_str} gain')
            else:
                await ctx.send(f'Not enough data for calculating your gain ({cur_client.get_event_string()})')
        else:
            user_gain_rel, user_gain_abs = user_gain
            await ctx.send(
                f'{gain_message}{round(user_gain_rel, ndigits=3)}% ({round(user_gain_abs, ndigits=CURRENCY_PRECISION.get(currency, 3))}{currency})')


def get_available_exchanges() -> str:
    exchange_list = ''
    for exchange in EXCHANGES.keys():
        exchange_list += f'{exchange}\n'
    return exchange_list


@slash.subcommand(
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
async def register_new(ctx: SlashContext,
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
                        f'Invalid keyword argument: {arg} syntax for keyword arguments: key1=value1 key2=value2 ...',
                        hidden=True)
                    logging.error(f'Invalid Keyword Arg {arg} passed in')

    try:
        exchange_name = exchange_name.lower()
        exchange_cls = EXCHANGES[exchange_name]
        if issubclass(exchange_cls, ClientWorker):
            # Check if required keyword args are given
            if len(kwargs.keys()) >= len(exchange_cls.required_extra_args) and \
                    all(required_kwarg in kwargs for required_kwarg in exchange_cls.required_extra_args):
                event = dbutils.get_event(ctx.guild_id, ctx.channel_id, registration=True, throw_exceptions=False)
                existing_client = None

                discord_user = DiscordUser.query.filter_by(user_id=ctx.author_id).first()
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

                new_client: Client = Client(
                    api_key=api_key,
                    api_secret=api_secret,
                    subaccount=subaccount,
                    extra_kwargs=kwargs,
                    exchange=exchange_name,
                    discorduser=discord_user
                )
                if event:
                    new_client.events.append(event)
                worker = exchange_cls(new_client)


                async def start_registration(ctx):
                    init_balance = worker.get_balance(datetime.now())
                    if init_balance.error is None:
                        if round(init_balance.amount, ndigits=2) == 0.0:
                            message = f'You do not have any balance in your account. Please fund your account before registering.'
                            button_row = None
                        else:
                            message = f'Your balance: **{init_balance.to_string()}**. This will be used as your initial balance. Is this correct?\nYes will register you, no will cancel the process.'

                            def register_user(ctx):
                                if existing_client:
                                    user_manager.delete_client(existing_client, commit=False)

                                if not discord_user.global_client:
                                    discord_user.global_client = new_client
                                    discord_user.global_client_id = new_client.id

                                discord_user.clients.append(new_client)

                                new_client.history.append(init_balance)
                                user_manager.add_client(new_client)

                                if inspect(discord_user).transient:
                                    db.session.add(discord_user)

                                db.session.add(new_client)
                                db.session.commit()
                                logger.info(f'Registered new user')

                            button_row = create_yes_no_button_row(
                                slash=slash,
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

                if not existing_client:
                    await start_registration(ctx)
                else:
                    buttons = create_yes_no_button_row(
                        slash=slash,
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
                logger.error(
                    f'Not enough kwargs for exchange {exchange_cls.exchange} were given.\nGot: {kwargs}\nRequired: {exchange_cls.required_extra_args}')
                args_readable = ''
                for arg in exchange_cls.required_extra_args:
                    args_readable += f'{arg}\n'
                raise UserInputError(
                    f'Need more keyword arguments for exchange {exchange_cls.exchange}.\nRequirements:\n {args_readable}')
        else:
            raise InternalError(f'Class {exchange_cls} is no subclass of ClientWorker!')
    except KeyError:
        raise UserInputError(f'Exchange {exchange_name} unknown')


@slash.subcommand(
    base="register",
    name="existing",
    description="Registers your global access to an ongoing event.",
    options=[]
)
@utils.log_and_catch_errors()
@utils.server_only
async def register_existing(ctx: SlashContext):
    event = dbutils.get_event(guild_id=ctx.guild_id, registration=True)
    user = dbutils.get_user(ctx.author_id)

    if event.is_free_for_registration:
        if user.global_client:
            if user.global_client not in event.registrations:
                event.registrations.append(user.global_client)
                db.session.commit()
                await ctx.send(f'You are now registered for _{event.name}_!', hidden=True)
            else:
                raise UserInputError('You are already registered for this event!')
        else:
            raise UserInputError('You do not have a global access to use')
    else:
        raise UserInputError(f'Event {event.name} is not available for registration')


@slash.subcommand(
    base='event',
    subcommand_group='show'
)
@utils.log_and_catch_errors()
@utils.server_only
async def event_show(ctx: SlashContext):
    events = Event.query.filter_by(guild_id=ctx.guild_id).all()
    if len(events) == 0:
        await ctx.send(content='There are no events', hidden=True)
    else:
        await ctx.defer()
        for event in events:
            if event.is_active:
                await ctx.send(content='Current Event:', embed=event.get_discord_embed(bot, registrations=True))
            else:
                await ctx.send(content='Upcoming Event:', embed=event.get_discord_embed(bot, registrations=True))


@slash.subcommand(
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
@utils.time_args(names=[('start', None), ('end', None), ('registration_start', None), ('registration_end', None)],
                 allow_future=True)
@utils.admin_only
@utils.server_only
async def register_event(ctx: SlashContext, name: str, description: str, start: datetime, end: datetime,
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

    active_registration = dbutils.get_event(ctx.guild_id, ctx.channel_id, registration=True, throw_exceptions=False)

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
        db.session.add(event)
        db.session.commit()
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


@slash.slash(
    name="unregister",
    description="Unregisters you from tracking",
    options=[]
)
@utils.log_and_catch_errors()
async def unregister(ctx):
    client = dbutils.get_client(ctx.author.id, ctx.guild_id)
    event = dbutils.get_event(ctx.guild_id, ctx.channel_id, throw_exceptions=False)

    def unregister_user(ctx):
        if event:
            client.events.remove(event)
            if len(client.events) == 0:
                user_manager.delete_client(client)
        else:
            user_manager.delete_client(client)
        discord_user = DiscordUser.query.filter_by(user_id=ctx.author_id).first()
        if len(discord_user.clients) == 0 and not discord_user.user:
            DiscordUser.query.filter_by(user_id=ctx.author_id).delete()
            db.session.commit()
        logger.info(f'Successfully unregistered user {ctx.author.display_name}')

    buttons = create_yes_no_button_row(
        slash=slash,
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


@slash.slash(
    name="info",
    description="Shows your stored information",
    options=[]
)
@utils.log_and_catch_errors()
async def info(ctx):
    user = dbutils.get_user(ctx.author_id)
    await ctx.send(content='', embeds=user.get_discord_embed(), hidden=True)


@slash.slash(
    name="clear",
    description="Clears your balance history",
    options=[
        create_option(
            name="since",
            description="Since when the history should be deleted",
            required=False,
            option_type=3
        ),
        create_option(
            name="to",
            description="Until when the history should be deleted",
            required=False,
            option_type=3,
        )
    ]
)
@utils.log_and_catch_errors()
@utils.time_args(names=[('since', None), ('to', None)])
async def clear(ctx: SlashContext, since: datetime = None, to: datetime = None, guild: str = None):
    if guild:
        guild = int(guild)

    client = dbutils.get_client(ctx.author_id, ctx.guild_id)

    from_to = ''
    if since:
        from_to += f' since **{since}**'
    if to:
        from_to += f' till **{to}**'

    def clear_user(ctx):
        user_manager.clear_client_data(client,
                                       start=since,
                                       end=to,
                                       update_initial_balance=True)

    buttons = create_yes_no_button_row(
        slash,
        author_id=ctx.author.id,
        yes_callback=clear_user,
        yes_message=f'Deleted your history{from_to}',
        no_message="Clear cancelled",
        hidden=True
    )

    await ctx.send(content=f'Do you really want to **delete** your history{from_to}?',
                   components=[buttons],
                   hidden=True)


@slash.subcommand(
    base="leaderboard",
    name="balance",
    description="Shows you the highest ranked users by $ balance",
    options=[]
)
@utils.log_and_catch_errors()
@utils.server_only
async def leaderboard_balance(ctx: SlashContext):
    await ctx.defer()
    await ctx.send(content='',
                   embed=utils.create_leaderboard(dc_client=bot, guild_id=ctx.guild_id, mode='balance', time=None))


@slash.subcommand(
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
async def leaderboard_gain(ctx: SlashContext, time: datetime = None):
    await ctx.defer()
    await ctx.send(content='',
                   embed=utils.create_leaderboard(dc_client=bot, guild_id=ctx.guild_id, mode='gain', time=time))


@slash.slash(
    name="daily",
    description="Shows your daily gains.",
    options=[
        create_option(
            name="user",
            description="User to display daily gains for (Author default)"
        ),
        create_option(
            name="amount",
            description="Amount of days",
            option_type=SlashCommandOptionType.INTEGER,
            required=False
        ),
        create_option(
            name="currency",
            description="Currency to use"
        )
    ]
)
@utils.log_and_catch_errors()
@utils.set_author_default(name="user")
async def daily(ctx: SlashContext, user: discord.Member, amount: int = None, currency: str = None ):
    client = dbutils.get_client(user.id, ctx.guild_id)
    await ctx.defer()
    daily_gains = utils.calc_daily(client, amount, ctx.guild_id, string=True)
    await ctx.send(
        embed=discord.Embed(title=f'Daily gains for {ctx.author.display_name}', description=f'```\n{daily_gains}```'))


@slash.slash(
    name="exchanges",
    description="Shows available exchanges"
)
async def exchanges(ctx):
    logger.info(f'New Interaction: Listing available exchanges for user {de_emojify(ctx.author.display_name)}')
    description = get_available_exchanges()
    embed = discord.Embed(title="Available Exchanges", description=description)
    await ctx.send(embed=embed)


def setup_logger(debug: bool = False):
    logger = logging.getLogger()
    logger.setLevel(logging.DEBUG if debug else logging.INFO)  # Change this to DEBUG if you want a lot more info
    formatter = logging.Formatter("%(asctime)s - %(name)s - %(levelname)s - %(message)s")
    if not os.path.exists(LOG_OUTPUT_DIR):
        os.mkdir(LOG_OUTPUT_DIR)
    log_stream = open(LOG_OUTPUT_DIR + f'log_{datetime.now().strftime("%Y-%m-%d_%H_%M_%S")}.txt', "w")
    handler = logging.StreamHandler(log_stream)
    handler.setFormatter(formatter)

    logger.addHandler(handler)
    return logger


@slash.slash(
    name="donate",
    description="Support dev?"
)
async def donate(ctx: SlashContext):
    embed = discord.Embed(
        description="**Do you like this bot?**\n"
                    "If so, maybe consider helping out a poor student :cry:\n\n"
                    "**BTC**: 1NQuRagfTziZ1k4ijc38cuCmCncWQFthSQ\n"
                    "**ZBD**: jackstar12@zbd.gg\n"
                    "**USDT (TRX)**: TPf47q7143stBkWicj4SidJ1DDeYSvtWBf\n"
                    "**USDT (BSC)**: 0x694cf86962f84d281d322887569b16935b48d9dd\n\n"
                    "@jacksn#9149."
    )
    await ctx.send(embed=embed)


@slash.slash(
    name="help",
    description="Help!"
)
async def help(ctx: SlashContext):
    embed = discord.Embed(
        title="**Usage**"
    )
    embed.add_field(
        name="How do I register?",
        value="https://github.com/jackstar12/balance-bot/blob/master/examples/register.md",
        inline=False
    )
    embed.add_field(
        name="Which information do I have to give the bot?",
        value="The bot only requires an **read only** api access",
        inline=False
    )
    # embed.add_field(
    #     name=""
    # )
    await ctx.send(embed=embed)


async def on_rekt_async(user: DiscordUser):
    logger.info(f'User {user} is rekt')

    message = random.Random().choice(seq=REKT_MESSAGES)

    for guild_data in REKT_GUILDS:
        try:
            guild: discord.guild.Guild = bot.get_guild(guild_data['guild_id'])
            channel = guild.get_channel(guild_data['guild_channel'])
            member = guild.get_member(user.user_id)
            if member:
                message_replaced = message.replace("{name}", member.display_name)
                embed = discord.Embed(description=message_replaced)
                await channel.send(embed=embed)
        except KeyError as e:
            logger.error(f'Invalid guild {guild_data=} {e}')
        except AttributeError as e:
            logger.error(f'Error while sending message to guild {e}')


parser = argparse.ArgumentParser(description="Run the bot.")
parser.add_argument("-r", "--reset", action="store_true", help="Archives the current data and resets it.")

args = parser.parse_args()

logger = setup_logger(debug=False)

if args.reset and os.path.exists(DATA_PATH):
    if not os.path.exists(ARCHIVE_PATH):
        os.mkdir(ARCHIVE_PATH)

    new_path = ARCHIVE_PATH + f"Archive_{datetime.now().strftime('%Y-%m-%d_%H-%M')}/"
    os.mkdir(new_path)
    try:
        shutil.copy(DATA_PATH + "user_data.json", new_path + "user_data.json")
        shutil.copy(DATA_PATH + "users.json", new_path + "users.json")

        os.remove(DATA_PATH + "user_data.json")
        os.remove(DATA_PATH + "users.json")
    except FileNotFoundError as e:
        logger.info(f'Error while archiving data: {e}')

api_thread = Thread(target=api.run)
api_thread.daemon = True
api_thread.start()


@slash.slash(
    name="summary",
    description="Show event summary"
)
@utils.log_and_catch_errors()
@utils.server_only
async def summary(ctx: SlashContext):
    event = dbutils.get_event(ctx.guild_id, ctx.channel_id, state='active')
    await ctx.defer()
    history = event.create_complete_history(dc_client=bot)
    await ctx.send(
        embeds=[
            event.create_leaderboard(bot),
            event.get_summary_embed(dc_client=bot).set_image(url=f'attachment://{history.filename}'),
        ],
        file=history
    )


@slash.slash(
   name="archive",
   description="Shows summary of archived event"
)
@utils.log_and_catch_errors()
@utils.server_only
async def archive(ctx: SlashContext):

    now = datetime.now()
    archived = Event.query.filter(
        Event.guild_id == ctx.guild_id,
        Event.end < now
    )

    async def show_events(ctx, selection: List[Event]):

        for event in selection:
            archive = event.archive
            history = discord.File(DATA_PATH + archive.history_path, "history.png")

            info = archive.event.get_discord_embed(
                bot, registrations=False
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
        slash,
        author_id=ctx.author_id,
        options=[
            {
                "name": event.name,
                "description": f'From {event.start.strftime("%Y-%m-%d")} to {event.end.strftime("%Y-%m-%d")}',
                "value": event,
            }
            for event in archived
        ],
        callback=show_events
    )

    await ctx.send(content='Which events do you want to display', hidden=True, components=[selection_row])

user_manager = UserManager(exchanges=EXCHANGES,
                           fetching_interval_hours=FETCHING_INTERVAL_HOURS,
                           data_path=DATA_PATH,
                           rekt_threshold=REKT_THRESHOLD,
                           on_rekt_callback=lambda user: bot.loop.create_task(on_rekt_async(user)))

event_manager = EventManager(discord_client=bot)

KEY = os.environ.get('BOT_KEY')
assert KEY, 'BOT_KEY missing'

bot.run(KEY)
