import json
import logging
import os
import random
import discord
import discord.errors
import typing
import time
import shutil
from datetime import timedelta
from threading import Thread

import api.dbutils as dbutils
import api.app as api
from api.database import db
from discord_slash.model import BaseCommandObject
from discord_slash import SlashCommand, SlashContext, SlashCommandOptionType
from discord_slash.utils.manage_commands import create_choice, create_option
from discord.ext import commands
from typing import List, Dict, Type, Tuple
from datetime import datetime

from api.dbmodels.balance import balance_from_json
from api.dbmodels.trade import Trade
from eventmanager import EventManager, FutureCallback

import matplotlib.pyplot as plt
import argparse

#from models.discorduser import DiscordUser
from clientworker import ClientWorker
from api.dbmodels.discorduser import DiscordUser, add_user_from_json
from api.dbmodels.user import User
from api.dbmodels.event import Event
from api.dbmodels.client import Client

#from models.client import Client
from usermanager import UserManager
from key import KEY
from config import (DATA_PATH,
                    PREFIX,
                    FETCHING_INTERVAL_HOURS,
                    REKT_MESSAGES,
                    LOG_OUTPUT_DIR,
                    REKT_GUILDS,
                    CURRENCY_PRECISION,
                    REKT_THRESHOLD,
                    ARCHIVE_PATH)

import utils
from utils import (server_only,
                   de_emojify,
                   add_guild_option,
                   calc_percentage,
                   calc_xs_ys,
                   create_yes_no_button_row)

from Exchanges.binance.binance import BinanceFutures, BinanceSpot
from Exchanges.bitmex import BitmexClient
from Exchanges.ftx.ftx import FtxClient
from Exchanges.kucoin import KuCoinClient
from Exchanges.bybit import BybitClient

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
    #register_command: BaseCommandObject = slash.commands['register']
    #unregister_command: BaseCommandObject = slash.commands['unregister']
    #clear_command: BaseCommandObject = slash.commands['clear']
    #add_guild_option(bot.guilds, register_command,
    #                 'Guild to register this access for. If not given, it will be global.')
    #add_guild_option(bot.guilds, unregister_command,
    #                 'Which guild access to unregister. If not given, it will be global.')
    #add_guild_option(bot.guilds, clear_command,
    #                 'Which guild to clear your data for. If not given, it will be global.')

    user_manager.start_fetching()
    event_manager.initialize_events()


    logger.info('Bot Ready')
    print('Bot Ready.')
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
async def ping(ctx: SlashContext):
    """Get the bot's current websocket and api latency."""
    start_time = time.time()
    message = await ctx.send("Testing Ping...")
    end_time = time.time()

    await message.edit(
        content=f"Pong! {round(bot.latency * 1000, ndigits=3)}ms\napi: {round((end_time - start_time), ndigits=3)}ms")


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
@utils.set_author_default(name='user')
async def balance(ctx: SlashContext, user: discord.Member = None, currency: str = None):
    if currency is None:
        currency = '$'
    currency = currency.upper()

    logger.info(f'New interaction with {ctx.author.display_name}: Get balance for {de_emojify(user.display_name)} ({currency=})')

    if ctx.guild is not None:
        try:
            registered_user = dbutils.get_client(user.id, ctx.guild.id)
        except ValueError as e:
            await ctx.send(e.args[0].replace('{name}', user.display_name), hidden=True)
            return

        await ctx.defer()

        usr_balance = user_manager.get_client_balance(registered_user, currency)
        if usr_balance.error is None:
            await ctx.send(f'{user.display_name}\'s balance: {usr_balance.to_string()}')
        else:
            await ctx.send(f'Error while getting {user.display_name}\'s balance: {usr_balance.error}')
    else:
        try:
            user = dbutils.get_user(ctx.author_id)
        except ValueError:
            await ctx.send(f'You are not registered', hidden=True)
            return

        await ctx.defer()

        for user_client in user.clients:
            usr_balance = user_manager.get_client_balance(user_client, currency)
            balance_message = f'Your balance ({user_client.get_event_string()}): '
            if usr_balance.error is None:
                await ctx.send(f'{balance_message}{usr_balance.to_string()}')
            else:
                await ctx.send(f'Error while getting your balance ({user_client.get_event_string()}): {usr_balance.error}')


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
@utils.set_author_default(name='user')
@utils.time_args(names=[('since', None), ('to', None)])
async def history(ctx: SlashContext,
                  user: discord.Member = None,
                  compare: str = None,
                  since: datetime = None,
                  to: datetime = None,
                  currency: str = None):
    logger.info(f'New interaction with {de_emojify(user.display_name)}: Show history')

    await ctx.defer()

    if ctx.guild:
        try:
            registered_client = dbutils.get_client(user.id, ctx.guild.id)
        except ValueError as e:
            logger.info(e.args[0].replace('{name}', user.display_name))
            await ctx.send(e.args[0].replace('{name}', user.display_name), hidden=True)
            return
        registrations = [(registered_client, user)]
    else:
        try:
            registered_user = dbutils.get_user(user.id)
            registrations = [(client, client.get_event_string()) for client in registered_user.clients]
        except ValueError as e:
            logger.info(e.args[0].replace('{name}', user.display_name))
            await ctx.send(e.args[0].replace('{name}', user.display_name), hidden=True)
            return

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
                        try:
                            registered_client = dbutils.get_client(member.id, ctx.guild.id)
                        except ValueError as e:
                            logger.info(e.args[0].replace('{name}', member.display_name))
                            await ctx.send(e.args[0].replace('{name}', member.display_name), hidden=True)
                            return
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

    first = True
    title = ''
    for registered_client, name in registrations:

        user_manager.get_client_balance(registered_client, currency=currency)
        user_data = user_manager.get_client_history(registered_client,
                                                    guild_id=ctx.guild_id,
                                                    start=since,
                                                    end=to,
                                                    currency=currency)

        if len(user_data) == 0:
            logger.error(f'No data for this user!')
            await ctx.send(content=f'Got no data for this user')
            return

        xs, ys = calc_xs_ys(user_data, percentage)

        total_gain = calc_percentage(user_data[0].amount, user_data[len(ys) - 1].amount)

        if first:
            title = f'History for {name} (Total: {total_gain}%)'
            first = False
        else:
            title += f' vs. {name} (Total: {total_gain}%)'

        plt.plot(xs, ys, label=f"{name}'s {currency_raw} Balance")

    plt.gcf().autofmt_xdate()
    plt.gcf().set_dpi(100)
    plt.gcf().set_size_inches(8 + len(registrations), 5.5 + len(registrations) * (5.5 / 8))
    plt.title(title)
    plt.ylabel(currency_raw)
    plt.xlabel('Time')
    plt.grid()
    plt.legend(loc="best")

    plt.savefig(DATA_PATH + "tmp.png")
    plt.close()
    file = discord.File(DATA_PATH + "tmp.png", "history.png")

    await ctx.send(content='', file=file)


def calc_gains(clients: List[Client],
               guild_id: int,
               search: datetime,
               currency: str = None) -> List[Tuple[DiscordUser, Tuple[float, float]]]:
    """
    :param guild_id:
    :param clients: users to calculate gain for
    :param search: date since when gain should be calculated
    :param currency:
    :param since_start: should the gain since the start be calculated?
    :return:
    Gain for each user is stored in a list of tuples following this structure: (User, (user gain rel, user gain abs)) success
                                                                               (User, None) missing
    """

    if currency is None:
        currency = '$'

    results = []
    for client in clients:
        data = user_manager.get_client_history(client, guild_id, start=search)
        if len(data) > 0:
            balance_then = user_manager.db_match_balance_currency(data[0], currency)
            balance_now = user_manager.db_match_balance_currency(data[len(data) - 1], currency)
            diff = round(balance_now.amount - balance_then.amount,
                         ndigits=CURRENCY_PRECISION.get(currency, 3))
            if balance_then.amount > 0:
                results.append((client,
                                (round(100 * (diff / balance_then.amount),
                                       ndigits=CURRENCY_PRECISION.get('%', 2)), diff)))
            else:
                results.append((client, (0.0, diff)))
        else:
            results.append((client, None))

    return results


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
@utils.time_args(names=[('time', None)])
@utils.set_author_default(name='user')
async def gain(ctx: SlashContext, user: discord.Member, time: datetime = None, currency: str = None):
    if currency is None:
        currency = '$'
    currency = currency.upper()

    logger.info(f'New Interaction with {ctx.author}: Calculate gain for {de_emojify(user.display_name)} {time=}')

    try:
        if ctx.guild:
            registered_client = dbutils.get_client(user.id, ctx.guild_id)
            clients = [registered_client]
        else:
            user = dbutils.get_user(ctx.author_id)
            clients = user.clients
    except ValueError as e:
        await ctx.send(content=e.args[0].replace('{name}', user.display_name))
        return

    since_start = time is None
    time_str = utils.readable_time(time)

    user_manager.fetch_data(clients=clients)
    user_gains = calc_gains(clients, ctx.guild_id, time, currency)

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


@slash.slash(
    name="register",
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
async def register_user(ctx: SlashContext,
                        exchange_name: str,
                        api_key: str,
                        api_secret: str,
                        subaccount: typing.Optional[str] = None,
                        guild: str = None,
                        args: str = None):
    if guild:
        guild = int(guild)

    logger.info(f'New Interaction with {ctx.author.display_name}: Trying to register user')

    await ctx.defer(hidden=True)

    active_event = dbutils.get_event(ctx.guild_id, throw_exceptions=False)

    kwargs = {}
    if args:
        args = args.split(' ')
        if len(args) > 0:
            for arg in args:
                try:
                    name, value = arg.split('=')
                    kwargs[name] = value
                except ValueError:
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
                client: Client = Client(
                    api_key=api_key,
                    api_secret=api_secret,
                    subaccount=subaccount,
                    extra_kwargs=kwargs,
                    exchange=exchange_name
                )
                worker = exchange_cls(client)
                existing_user = dbutils.get_client(user_id=ctx.author.id, guild_id=ctx.guild_id, throw_exceptions=False)
                if existing_user:
                    existing_user.api = client
                    await ctx.send(embed=existing_user.get_discord_embed(client.get_guild(guild)), hidden=True)
                    logger.info(f'Updated user')
                    #user_manager.save_registered_users()
                else:
                    new_user = DiscordUser(
                        user_id = ctx.author.id,
                        name=ctx.author.name,
                        clients=[client],
                        global_client=client
                    )
                    init_balance = worker.get_balance(datetime.now())
                    if init_balance.error is None:
                        if round(init_balance.amount, ndigits=2) == 0.0:
                            message = f'You do not have any balance in your account. Please fund your account before registering.'
                            button_row = None
                        else:
                            message = f'Your balance: **{init_balance.to_string()}**. This will be used as your initial balance. Is this correct?\nYes will register you, no will cancel the process.'

                            def register_user():
                                new_user.clients[0].history.append(init_balance)
                                user_manager._add_worker(worker)
                                db.session.add(new_user)
                                db.session.add(client)
                                db.session.commit()
                                logger.info(f'Registered new user')

                            button_row = create_yes_no_button_row(
                                slash,
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
                        embed=new_user.get_discord_embed(),
                        hidden=True,
                        components=[button_row] if button_row else None
                    )

            else:
                logger.error(
                    f'Not enough kwargs for exchange {exchange_cls.exchange} were given.\nGot: {kwargs}\nRequired: {exchange_cls.required_extra_args}')
                args_readable = ''
                for arg in exchange_cls.required_extra_args:
                    args_readable += f'{arg}\n'
                await ctx.send(
                    f'Need more keyword arguments for exchange {exchange_cls.exchange}.\nRequirements:\n {args_readable}')
        else:
            logger.error(f'Class {exchange_cls} is no subclass of Client!')
    except KeyError:
        logger.error(f'Exchange {exchange_name} unknown')
        await ctx.send(f'Exchange {exchange_name} unknown')


@slash.slash(
    name="register_existing",
    description="Registers your global access to an ongoing event.",
    options=[]
)
@server_only
async def register_existing(ctx: SlashContext):

    try:
        event = dbutils.get_event(guild_id=ctx.guild_id, registration=True)
        user = dbutils.get_user(ctx.author_id)
    except ValueError as e:
        await ctx.send(content=e.args[0].replace('{name}', ctx.author.display_name), hidden=True)
        return

    if event.is_free_for_registration:
        if user.global_client:
            if user.global_client not in event.registrations:
                event.registrations.append(user.global_client)
                await ctx.send('Success', hidden=True)
            else:
                await ctx.send('You are already registered for this event!', hidden=True)
        else:
            await ctx.send('You do not have a global access to use', hidden=True)
    else:
        await ctx.send(f'Event {event.name} is not available for registration', hidden=True)


@slash.slash(
    name="event_show",
    description="Shows you all ongoing events",
    options=[]
)
@server_only
async def event_show(ctx: SlashContext):
    logging.info(f'Show events: {ctx.author=} {ctx.guild=}')

    try:
        event = dbutils.get_event(ctx.guild_id, channel_id=ctx.channel_id)
    except ValueError as e:
        await ctx.send(e.args[0], hidden=True)
        logging.info('No event registered.')
        return

    await ctx.send(embed=event.get_discord_embed(registrations=True))


@slash.slash(
    name='event',
    description='Register an event for this guild.',
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
@server_only
@utils.time_args(names=[('start', None), ('end', None), ('registration_start', None), ('registration_end', None)], allow_future=True)
async def register_event(ctx: SlashContext, name: str, description: str, start: datetime, end: datetime, registration_start: datetime, registration_end: datetime):

    now = datetime.now()
    start = now + timedelta(seconds=20)
    registration_start = now + timedelta(seconds=10)
    registration_end = now + timedelta(seconds=30)
    end = now + timedelta(seconds=40)

    if start >= end:
        await ctx.send("Start time can't be after end time.", hidden=True)
        return
    if registration_start >= registration_end:
        await ctx.send("Registration start can't be after registration end", hidden=True)
        return
    if registration_end < start:
        await ctx.send("Registration end should be after or at event start", hidden=True)
        return
    if registration_end > end:
        await ctx.send("Registration end can't be after event end.", hidden=True)
        return
    if registration_start > start:
        await ctx.send("Registration start should be before event start.", hidden=True)
        return

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

    def register():
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

    await ctx.send(embed=event.get_discord_embed(), components=[row], hidden=True)



@slash.slash(
    name="unregister",
    description="Unregisters you from tracking",
    options=[]
)
async def unregister(ctx, guild: str = None):
    if guild:
        guild = int(guild)

    logger.info(f'New Interaction with {ctx.author.display_name}: Trying to unregister user {ctx.author.display_name}')

    try:
        client = dbutils.get_client(ctx.author.id, guild)
    except ValueError as e:
        await ctx.send(e.args[0].replace('{name}', ctx.author.display_name), hidden=True)
        return

    def unregister_user():
        user_manager.remove_client(client)
        logger.info(f'Successfully unregistered user {ctx.author.display_name}')

    buttons = create_yes_no_button_row(
        slash,
        author_id=ctx.author.id,
        yes_callback=unregister_user,
        yes_message="You were succesfully urnegistered!",
        no_message="Unregistration cancelled",
        hidden=True
    )

    guild_name = ""
    if guild:
        guild_name = f' from {bot.get_guild(guild).name}'
    await ctx.send(content=f'Do you really want to unregister{guild_name}? This will **delete all your data**.',
                   components=[buttons],
                   hidden=True)


@slash.slash(
    name="info",
    description="Shows your stored information",
    options=[]
)
async def info(ctx, guild=None):

    try:
        user = dbutils.get_user(ctx.author_id)
    except ValueError as e:
        await ctx.send(e.args[0].replace('{name}', ctx.author.display_name), hidden=True)
        return

    trades = Trade.query.all()

    await ctx.send(content='', embed=user.get_discord_embed(), hidden=True)


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
@utils.time_args(names=[('since', None), ('to', None)])
async def clear(ctx: SlashContext, since: datetime = None, to: datetime = None, guild: str = None):
    logging.info(f'New interaction with {de_emojify(ctx.author.display_name)}: clear history {since=} {to=}')

    if guild:
        guild = int(guild)

    try:
        client = dbutils.get_client(ctx.author.id. ctx.guild_id)
    except ValueError as e:
        await ctx.send(e.args[0].replace('{name}', ctx.author.display_name), hidden=True)
        return

    from_to = ''
    if since:
        from_to += f' since **{since}**'
    if to:
        from_to += f' till **{to}**'

    def clear_user():
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


async def create_leaderboard(ctx: SlashContext, guild: discord.Guild, mode: str, time: datetime = None):
    user_scores: List[Tuple[DiscordUser, float]] = []
    value_strings: Dict[DiscordUser, str] = {}
    users_rekt: List[DiscordUser] = []
    clients_missing: List[DiscordUser] = []

    footer = ''
    description = ''

    event = dbutils.get_event(guild.id, throw_exceptions=False)

    if event:
        clients = event.registrations
    else:
        clients = []
        # All global clients
        users = DiscordUser.query.filter(DiscordUser.global_client_id).all()
        for user in users:
            member = guild.get_member(user.user_id)
            if member:
                clients.append(user.global_client)

    user_manager.fetch_data(clients=clients)

    if mode == 'balance':
        for client in clients:
            if client.rekt_on:
                users_rekt.append(client)
            elif len(client.history) > 0:
                balance = client.history[len(client.history) - 1]
                if balance.amount > REKT_THRESHOLD:
                    user_scores.append((client, balance.amount))
                    value_strings[client] = balance.to_string(display_extras=False)
                else:
                    users_rekt.append(client)
            else:
                clients_missing.append(client)
    elif mode == 'gain':

        description += f'Gain {utils.readable_time(time)}\n\n'

        client_gains = calc_gains(clients, ctx.guild_id, time)

        for client, client_gain in client_gains:
            if client_gain is not None:
                if client.rekt_on:
                    users_rekt.append(client)
                else:
                    user_gain_rel, user_gain_abs = client_gain
                    user_scores.append((client, user_gain_rel))
                    value_strings[client] = f'{user_gain_rel}% ({user_gain_abs}$)'
            else:
                clients_missing.append(client)
    else:
        logging.error(f'Unknown mode {mode} was passed in')
        await ctx.send(f'Unknown mode {mode}')
        return

    user_scores.sort(key=lambda x: x[1], reverse=True)
    rank = 1
    rank_true = 1

    if len(user_scores) > 0:
        prev_score = None
        for client, score in user_scores:
            member = guild.get_member(client.discorduser.user_id)
            if member:
                if prev_score is not None and score < prev_score:
                    rank = rank_true
                if client in value_strings:
                    value = value_strings[client]
                    description += f'{rank}. **{member.display_name}** {value}\n'
                    rank_true += 1
                else:
                    logger.error(f'Missing value string for {client=} even though hes in user_scores')
                prev_score = score

    if len(users_rekt) > 0:
        description += f'\n**Rekt**\n'
        for user_rekt in users_rekt:
            member = guild.get_member(user_rekt.discorduser.user_id)
            if member:
                description += f'{member.display_name}'
                if user_rekt.rekt_on:
                    description += f' since {user_rekt.rekt_on.replace(microsecond=0)}'
                description += '\n'

    if len(clients_missing) > 0:
        description += f'\n**Missing**\n'
        for client_missing in clients_missing:
            member = guild.get_member(client_missing.discorduser.user_id)
            if member:
                description += f'{member.display_name}\n'

    description += f'\n{footer}'

    embed = discord.Embed(
        title='Leaderboard :medal:',
        description=description
    )
    logger.info(f"Done creating leaderboard.\nDescription:\n{de_emojify(description)}")
    await ctx.send(content='', embed=embed)


@slash.subcommand(
    base="leaderboard",
    name="balance",
    description="Shows you the highest ranked users by $ balance",
    options=[]
)
@server_only
async def leaderboard_balance(ctx: SlashContext):
    logger.info(f'New Interaction: Creating balance leaderboard, requested by user {de_emojify(ctx.author.display_name)}')
    await ctx.defer()
    await create_leaderboard(ctx, guild=ctx.guild, mode='balance', time=None)


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
@utils.time_args(names=[('time', None)])
@server_only
async def leaderboard_gain(ctx: SlashContext, time: datetime = None):
    logger.info(f'New Interaction: Creating balance leaderboard, requested by user {de_emojify(ctx.author.display_name)}')

    await ctx.defer()
    await create_leaderboard(ctx, guild=ctx.guild, mode='gain', time=time)


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

    #user_manager.save_registered_users()


parser = argparse.ArgumentParser(description="Run the bot.")
parser.add_argument("-r", "--reset", action="store_true", help="Archives the current data and resets it.")
parser.add_argument("-m", "--migrate", action="store_true", help="Specifying this puts the current data into a database.")

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

if args.migrate:

    def load_registered_users():
        try:
            with open(DATA_PATH + 'users.json', 'r') as f:
                users_json = json.load(fp=f)
                for user_json in users_json:
                    try:
                        add_user_from_json(user_json)
                    except KeyError as e:
                        logging.error(f'{e} occurred while parsing user data {user_json} from users.json')
        except FileNotFoundError:
            logging.info(f'No user information found')
        except json.decoder.JSONDecodeError:
            pass


    def load_user_data():
        try:
            with open(DATA_PATH + "user_data.json", "r") as f:
                raw_json = json.load(fp=f)
                if raw_json:
                    for ts, data in raw_json:
                        time = datetime.fromtimestamp(ts)
                        for user_id in data:
                            user = DiscordUser.query.filter_by(user_id=user_id).first()
                            if user:
                                for key in data[user_id].keys():
                                    balance = balance_from_json(data[user_id][key], time)
                                    user.global_client.history.append(balance)
                                    db.session.add(balance)
                                    break
        except FileNotFoundError:
            logging.info('No user data found')
        except json.JSONDecodeError as e:
            logging.error(f'{e}: Error while parsing user data.')

        db.session.commit()


    load_registered_users()
    load_user_data()

    print('Done migrating. Do not run this again.')

    users = DiscordUser.query.all()
    exit()


user_manager = UserManager(exchanges=EXCHANGES,
                           fetching_interval_hours=FETCHING_INTERVAL_HOURS,
                           data_path=DATA_PATH,
                           rekt_threshold=REKT_THRESHOLD,
                           on_rekt_callback=lambda user: bot.loop.create_task(on_rekt_async(user)))

event_manager = EventManager(discord_client=bot)

bot.run(KEY)
