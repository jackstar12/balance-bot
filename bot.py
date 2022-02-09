import logging
import os
import random
import discord
import discord.errors
import typing
import time
import shutil
from threading import Thread

import api.app as api
from api.database import db
from discord_slash.model import BaseCommandObject
from discord_slash import SlashCommand, SlashContext, SlashCommandOptionType
from discord_slash.utils.manage_commands import create_choice, create_option
from discord.ext import commands
from typing import List, Dict, Type, Tuple
from datetime import datetime

import matplotlib.pyplot as plt
import argparse

#from models.discorduser import DiscordUser
from clientworker import ClientWorker
from api.dbmodels.discorduser import DiscordUser
from api.dbmodels.user import User
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

client = commands.Bot(command_prefix=PREFIX, intents=intents)
slash = SlashCommand(client)

EXCHANGES: Dict[str, Type[ClientWorker]] = {
    'binance-futures': BinanceFutures,
    'binance-spot': BinanceSpot,
    'bitmex': BitmexClient,
    'ftx': FtxClient,
    'kucoin': KuCoinClient,
    'bybit': BybitClient
}


@client.event
async def on_ready():
    register_command: BaseCommandObject = slash.commands['register']
    unregister_command: BaseCommandObject = slash.commands['unregister']
    clear_command: BaseCommandObject = slash.commands['clear']
    add_guild_option(client.guilds, register_command,
                     'Guild to register this access for. If not given, it will be global.')
    add_guild_option(client.guilds, unregister_command,
                     'Which guild access to unregister. If not given, it will be global.')
    add_guild_option(client.guilds, clear_command,
                     'Which guild to clear your data for. If not given, it will be global.')

    user_manager.start_fetching()

    logger.info('Bot Ready')
    print('Bot Ready.')
    rate_limit = True
    while rate_limit:
        try:
            await slash.sync_all_commands(delete_from_unused_guilds=True)
            rate_limit = False
        except discord.errors.HTTPException as e:
            if e.code == 429:
                print('We are being rate limited. Retry in 5 seconds...')
                time.sleep(5)


@client.event
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
        content=f"Pong! {round(client.latency * 1000, ndigits=3)}ms\napi: {round((end_time - start_time), ndigits=3)}ms")


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

    logger.info(
        f'New interaction with {ctx.author.display_name}: Get balance for {de_emojify(user.display_name)} ({currency=})')

    if ctx.guild is not None:
        try:
            registered_user = user_manager.get_user(user.id, ctx.guild.id)
        except ValueError as e:
            await ctx.send(e.args[0].replace('{name}', user.display_name), hidden=True)
            return

        await ctx.defer()

        usr_balance = user_manager.get_user_balance(registered_user, currency)
        if usr_balance.error is None:
            await ctx.send(f'{user.display_name}\'s balance: {usr_balance.to_string()}')
        else:
            await ctx.send(f'Error while getting {user.display_name}\'s balance: {usr_balance.error}')
    else:
        users_by_id = user_manager.get_users_by_id()
        if user.id in users_by_id:
            registered_guilds = users_by_id[user.id]

            await ctx.defer()

            for guild_id in registered_guilds:
                usr_balance = user_manager.get_user_balance(registered_guilds[guild_id], currency)
                guild_name = client.get_guild(guild_id)
                balance_message = f'Your balance on {guild_name}: ' if guild_name else 'Your balance: '
                if usr_balance.error is None:
                    await ctx.send(f'{balance_message}{usr_balance.to_string()}')
                else:
                    await ctx.send(f'Error while getting your balance on {guild_name}: {usr_balance.error}')
        else:
            await ctx.send(f'You are not registered', hidden=True)


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
@server_only
async def history(ctx: SlashContext,
                  user: discord.Member = None,
                  compare: str = None,
                  since: datetime = None,
                  to: datetime = None,
                  currency: str = None):
    logger.info(f'New interaction with {de_emojify(user.display_name)}: Show history')

    await ctx.defer()

    try:
        registered_user = user_manager.get_user(user.id, ctx.guild.id)
    except ValueError as e:
        logger.info(e.args[0].replace('{name}', user.display_name))
        await ctx.send(e.args[0].replace('{name}', user.display_name), hidden=True)
        return

    registrations = [(registered_user, user)]

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
                            registered_user = user_manager.get_user(member.id, ctx.guild.id)
                        except ValueError as e:
                            logger.info(e.args[0].replace('{name}', member.display_name))
                            await ctx.send(e.args[0].replace('{name}', member.display_name), hidden=True)
                            return
                        registrations.append((registered_user, member))

    currency_raw = currency
    if currency is None:
        if len(registrations) > 1:
            currency = '%'
        else:
            currency = '$'
    currency = currency.upper()
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
    for registered_user, member in registrations:

        user_manager.get_user_balance(registered_user, currency=currency)
        user_data = user_manager.get_single_user_data(registered_user.user_id,
                                                      start=since,
                                                      end=to, currency=currency)

        if len(user_data) == 0:
            logger.error(f'No data for this user!')
            await ctx.send(content=f'Got no data for this user')
            return

        xs, ys = calc_xs_ys(user_data, percentage)

        total_gain = calc_percentage(user_data[0].amount, user_data[len(ys) - 1].amount)

        if first:
            title = f'History for {member.display_name} (Total: {total_gain}%)'
            first = False
        else:
            title += f' vs. {member.display_name} (Total: {total_gain}%)'

        plt.plot(xs, ys, label=f"{member.display_name}'s {currency_raw} Balance")

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


def calc_gains(users: List[DiscordUser],
               search: datetime,
               currency: str = None,
               since_start=False) -> List[Tuple[DiscordUser, Tuple[float, float]]]:
    """
    :param users: users to calculate gain for
    :param search: date since when gain should be calculated
    :param currency:
    :param since_start: should the gain since the start be calculated?
    :return:
    Gain for each user is stored in a list of tuples following this structure: (User, (user gain rel, user gain abs)) success
                                                                               (User, None) missing
    """

    if currency is None:
        currency = '$'

    if search is None:
        search = datetime.now()

    user_data = user_manager.get_user_data()
    users_left = users.copy()
    results = []

    if since_start:
        iterator = user_data
    else:
        iterator = reversed(user_data)

    for cur_time, data in iterator:
        cur_diff = cur_time - search
        if cur_diff.total_seconds() <= 0 or since_start:
            for user in users_left:
                try:
                    balance_then = None
                    if since_start and user.initial_balance:
                        then, balance_then = user.initial_balance
                        balance_then = user_manager.match_balance_currency(balance_then, currency)

                    if not balance_then:
                        balance_then = user_manager.get_balance_from_data(data, user.id, user.guild_id, exact=True)
                        balance_then = user_manager.match_balance_currency(balance_then, currency)

                    if balance_then:
                        balance_now = user_manager.get_latest_user_balance(user.id,
                                                                           guild_id=user.guild_id,
                                                                           currency=currency)
                        if balance_now:
                            users_left.remove(user)
                            diff = round(balance_now.amount - balance_then.amount,
                                         ndigits=CURRENCY_PRECISION.get(currency, 3))
                            if balance_then.amount > 0:
                                results.append((user,
                                                (round(100 * (diff / balance_then.amount),
                                                       ndigits=CURRENCY_PRECISION.get('%', 2)), diff)))
                            else:
                                results.append((user, (0.0, diff)))
                except KeyError:
                    # User isn't included in data set
                    continue
            if len(users_left) == 0:
                break

    for user in users_left:
        results.append((user, None))

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
async def gain(ctx, user: discord.Member, time: datetime = None, currency: str = None):
    if currency is None:
        currency = '$'
    currency = currency.upper()

    logger.info(f'New Interaction with {ctx.author}: Calculate gain for {de_emojify(user.display_name)} {time=}')

    users = []
    users_by_id = user_manager.get_users_by_id()
    if ctx.guild:
        try:
            registered_user = user_manager.get_user(user.id, None if not ctx.guild else ctx.guild.id)
            users = [registered_user]
        except ValueError as e:
            await ctx.send(content=e.args[0].replace('{name}', user.display_name))
            return
    elif user.id in users_by_id:
        users = list(users_by_id[user.id].values())
    else:
        await ctx.send(f'You are not registered.')

    since_start = time is None
    time_str = utils.readable_time(time)

    user_manager.fetch_data(users=users)
    user_gains = calc_gains(users, time, currency, since_start=since_start)

    for cur_user, user_gain in user_gains:
        guild = client.get_guild(ctx.guild_id)
        if ctx.guild:
            gain_message = f'{user.display_name}\'s gain {"" if since_start else time_str}: '
        else:
            gain_message = "Your gain: " if not guild else f"Your gain on {guild}: "
        if user_gain is None:
            logger.info(
                f'Not enough data for calculating {de_emojify(user.display_name)}\'s {time_str} gain on guild {guild}')
            if ctx.guild:
                await ctx.send(f'Not enough data for calculating {user.display_name}\'s {time_str} gain')
            else:
                await ctx.send(f'Not enough data for calculating your gain on {guild}')
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
    description=f"Register you for tracking.",
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
    ],
)
async def register(ctx: SlashContext,
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
                client_data: Client = Client(
                    api_key=api_key,
                    api_secret=api_secret,
                    subaccount=subaccount,
                    extra_kwargs=kwargs,
                    exchange=exchange_name
                )
                worker = exchange_cls(client_data)
                existing_user = user_manager.get_user(user_id=ctx.author.id)
                if existing_user:
                    existing_user.api = client_data
                    await ctx.send(embed=existing_user.get_discord_embed(client_data.get_guild(guild)), hidden=True)
                    logger.info(f'Updated user')
                    user_manager.save_registered_users()
                else:
                    new_user = DiscordUser(
                        user_id = ctx.author.id,
                        name=ctx.author.name,
                        client=client_data
                    )
                    init_balance = worker.get_balance(datetime)
                    if init_balance.error is None:
                        if round(init_balance.amount, ndigits=2) == 0.0:
                            message = f'You do not have any balance in your account. Please fund your account before registering.'
                            button_row = None
                        else:
                            message = f'Your balance: **{init_balance.to_string()}**. This will be used as your initial balance. Is this correct?\nYes will register you, no will cancel the process.'

                            def register_user():
                                new_user.client.history.append(init_balance)
                                user_manager.db_add_worker(worker)
                                db.session.add(new_user)
                                db.session.add(client_data)
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
                        embed=new_user.get_discord_embed(client.get_guild(guild)),
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
    name="unregister",
    description="Unregisters you from tracking",
    options=[]
)
async def unregister(ctx, guild: str = None):
    if guild:
        guild = int(guild)

    logger.info(f'New Interaction with {ctx.author.display_name}: Trying to unregister user {ctx.author.display_name}')

    try:
        registered_user = user_manager.get_user(ctx.author.id, guild, exact=False)
    except ValueError as e:
        await ctx.send(e.args[0].replace('{name}', ctx.author.display_name), hidden=True)
        return

    def unregister_user():
        user_manager.clear_user_data(registered_user)
        user_manager.remove_user(registered_user)
        user_manager.save_registered_users()
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
        guild_name = f' from {client.get_guild(guild).name}'
    await ctx.send(content=f'Do you really want to unregister{guild_name}? This will **delete all your data**.',
                   components=[buttons],
                   hidden=True)


@slash.slash(
    name="info",
    description="Shows your stored information",
    options=[]
)
async def info(ctx):
    users_by_id = user_manager.get_users_by_id()
    if ctx.author.id in users_by_id:
        registrations = users_by_id[ctx.author.id]
        for registration in registrations.values():
            guild_name = client.get_guild(registration.guild_id)
            await ctx.send(embed=registration.get_discord_embed(guild_name), hidden=True)
    else:
        await ctx.send(f'You are not registered.', hidden=True)


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
async def clear(ctx, since: datetime = None, to: datetime = None, guild: str = None):
    logging.info(f'New interaction with {de_emojify(ctx.author.display_name)}: clear history {since=} {to=}')

    if guild:
        guild = int(guild)

    try:
        registered_user = user_manager.get_user(ctx.author.id, guild)
    except ValueError as e:
        await ctx.send(e.args[0].replace('{name}', ctx.author.display_name), hidden=True)
        return

    from_to = ''
    if since:
        from_to += f' since **{since}**'
    if to:
        from_to += f' till **{to}**'

    def clear_user():
        user_manager.clear_user_data(registered_user,
                                     start=since,
                                     end=to,
                                     remove_all_guilds=True,
                                     update_initial_balance=True)
        user_manager.save_registered_users()

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
    users_missing: List[DiscordUser] = []

    footer = ''
    description = ''

    date, data = user_manager.fetch_data()
    if mode == 'balance':
        users_by_id = user_manager.get_users_by_id()
        for user_id in users_by_id:
            user = user_manager.get_user(user_id, guild.id, throw_exceptions=False)
            if user and guild.get_member(user_id):
                if user.rekt_on:
                    users_rekt.append(user)
                else:
                    balance = user_manager.get_balance_from_data(data, user.id, user.guild_id)
                    if not balance:
                        balance = user_manager.get_latest_user_balance(user.id)
                    if balance is None:
                        users_missing.append(user)
                    elif balance.amount > REKT_THRESHOLD:
                        user_scores.append((user, balance.amount))
                        value_strings[user] = balance.to_string(display_extras=False)
                    else:
                        users_rekt.append(user)

        date = date.replace(microsecond=0)
        footer += f'Data used from: {date}'
    elif mode == 'gain':

        since_start = time is None
        description += f'Gain since {utils.readable_time(time)}\n\n'

        users = []
        users_by_id = user_manager.get_users_by_id()
        for user_id in users_by_id:
            user = user_manager.get_user(user_id, guild.id, throw_exceptions=False)
            if user and guild.get_member(user.id):
                users.append(user)

        user_gains = calc_gains(users, time, since_start=since_start)

        for user, user_gain in user_gains:
            if user_gain is not None:
                if user.rekt_on:
                    users_rekt.append(user)
                else:
                    user_gain_rel, user_gain_abs = user_gain
                    user_scores.append((user, user_gain_rel))
                    value_strings[user] = f'{user_gain_rel}% ({user_gain_abs}$)'
            else:
                users_missing.append(user)
    else:
        logging.error(f'Unknown mode {mode} was passed in')
        await ctx.send(f'Unknown mode {mode}')
        return

    user_scores.sort(key=lambda x: x[1], reverse=True)
    rank = 1
    rank_true = 1

    if len(user_scores) > 0:
        prev_score = None
        for user, score in user_scores:
            member = guild.get_member(user.id)
            if member:
                if prev_score is not None and score < prev_score:
                    rank = rank_true
                if user in value_strings:
                    value = value_strings[user]
                    description += f'{rank}. **{member.display_name}** {value}\n'
                    rank_true += 1
                else:
                    logger.error(f'Missing value string for {user=} even though hes in user_scores')
                prev_score = score

    if len(users_rekt) > 0:
        description += f'\n**Rekt**\n'
        for user_rekt in users_rekt:
            member = guild.get_member(user_rekt.id)
            if member:
                description += f'{member.display_name}'
                if user_rekt.rekt_on:
                    description += f' since {user_rekt.rekt_on.replace(microsecond=0)}'
                description += '\n'

    if len(users_missing) > 0:
        description += f'\n**Missing**\n'
        for user_missing in users_missing:
            member = guild.get_member(user_missing.id)
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
    logger.info(
        f'New Interaction: Creating balance leaderboard, requested by user {de_emojify(ctx.author.display_name)}')
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
    logger.info(
        f'New Interaction: Creating balance leaderboard, requested by user {de_emojify(ctx.author.display_name)}')

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
            guild: discord.guild.Guild = client.get_guild(guild_data['guild_id'])
            channel = guild.get_channel(guild_data['guild_channel'])
            member = guild.get_member(user.id)
            if member:
                message_replaced = message.replace("{name}", member.display_name)
                embed = discord.Embed(description=message_replaced)
                await channel.send(embed=embed)
        except KeyError as e:
            logger.error(f'Invalid guild {guild_data=} {e}')
        except AttributeError as e:
            logger.error(f'Error while sending message to guild {e}')

    user_manager.save_registered_users()


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

user_manager = UserManager(exchanges=EXCHANGES,
                           fetching_interval_hours=FETCHING_INTERVAL_HOURS,
                           data_path=DATA_PATH,
                           rekt_threshold=REKT_THRESHOLD,
                           on_rekt_callback=lambda user: client.loop.create_task(on_rekt_async(user)))

api_thread = Thread(target=api.run)
api_thread.daemon = True
api_thread.start()

client.run(KEY)
