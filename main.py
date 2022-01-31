import asyncio
import logging
import os
import random
import sys
import discord
import json
import typing
import time
import shutil
import re
import smtplib

from discord_slash.model import BaseCommandObject
from discord_slash import SlashCommand, SlashContext, SlashCommandOptionType
from discord_slash.utils.manage_commands import create_choice, create_option
from discord.ext import commands
from typing import List, Dict, Type, Tuple, Union, Optional
from datetime import datetime, timedelta
from random import Random

import matplotlib.pyplot as plt
import argparse

from balance import Balance, balance_from_json
from user import User, user_from_json
from client import Client
from datacollector import DataCollector
from dialogue import Dialogue, YesNoDialogue
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

from utils import (dm_only,
                   server_only,
                   de_emojify,
                   get_user_by_id,
                   add_guild_option,
                   calc_percentage,
                   calc_timedelta_from_time_args,
                   calc_xs_ys,
                   create_yes_no_button_row)

from Exchanges.binance import BinanceClient
from Exchanges.bitmex import BitmexClient
from Exchanges.ftx import FtxClient
from Exchanges.kucoin import KuCoinClient
from Exchanges.bybit import BybitClient

intents = discord.Intents().default()
intents.members = True
intents.guilds = True

client = commands.Bot(command_prefix=PREFIX, intents=intents)
slash = SlashCommand(client)
USERS: List[User] = []

# { user_id: { guild_id: User} }
USERS_BY_ID: Dict[int, Dict[int, User]] = {}

EXCHANGES: Dict[str, Type[Client]] = {
    'binance': BinanceClient,
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
    add_guild_option(client.guilds, register_command, 'Guild to register this access for. If not given, it will be global.')
    add_guild_option(client.guilds, unregister_command, 'Which guild access to unregister. If not given, it will be global.')
    add_guild_option(client.guilds, clear_command, 'Which guild to clear your data for. If not given, it will be global.')

    collector.start_fetching()

    logger.info('Bot Ready')
    print('Bot Ready.')
    await slash.sync_all_commands(delete_from_unused_guilds=True)


@client.event
async def on_guild_join(guild: discord.Guild):
    commands = [slash.commands['register'], slash.commands['unregister'], slash.commands['clear']]

    for command in commands:
        for option in command.options:
            if option['name'] == 'guild':
                option.choices.append(
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
    """Get the bot's current websocket and API latency."""
    start_time = time.time()
    message = await ctx.send("Testing Ping...")
    end_time = time.time()

    await message.edit(
        content=f"Pong! {round(client.latency, ndigits=3)}ms\nAPI: {round((end_time - start_time), ndigits=3)}ms")


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
async def balance(ctx, user: discord.Member = None, currency: str = None):
    if user is None:
        user = ctx.author
    if currency is None:
        currency = '$'
    currency = currency.upper()

    logger.info(f'New interaction with {ctx.author.display_name}: Get balance for {de_emojify(user.display_name)} ({currency=})')
    
    if ctx.guild is not None:
        try:
            registered_user = get_user_by_id(USERS_BY_ID, user.id, ctx.guild.id)
        except ValueError as e:
            await ctx.send(e.args[0].replace('{name}', user.display_name), hidden=True)
            return

        usr_balance = collector.get_user_balance(registered_user, currency)
        if usr_balance.error is None:
            await ctx.send(f'{user.display_name}\'s balance: {usr_balance.to_string()}')
        else:
            await ctx.send(f'Error while getting {user.display_name}\'s balance: {usr_balance.error}')
    else:
        if user.id in USERS_BY_ID:
            registered_guilds = USERS_BY_ID[user.id]
            for guild_id in registered_guilds:
                usr_balance = collector.get_user_balance(registered_guilds[guild_id], currency)
                guild_name = client.get_guild(guild_id)
                balance_message = f'Your balance on {guild_name}: ' if guild_name else 'Your balance: '
                if usr_balance.error is None:
                    await ctx.send(f'{balance_message}{usr_balance.to_string()}')
                else:
                    await ctx.send(f'Error while getting your balance on {guild_name}: {usr_balance.error}')


async def create_history(message: discord.Message,
                         user: discord.Member,
                         guild_id: int,
                         currency: str,
                         compare: discord.Member = None,
                         since: str = None,
                         to: str = None):
    logger.info(f'New interaction with {de_emojify(user.display_name)}: Show history')

    currency_raw = currency
    if '%' in currency:
        percentage = True
        currency = currency.rstrip('%')
        currency = currency.rstrip()
        if not currency:
            currency = '$'
    else:
        percentage = False

    try:
        registered_user = get_user_by_id(USERS_BY_ID, user.id, guild_id)
    except ValueError as e:
        await message.edit(content=e.args[0].replace('{name}', user.display_name))
        return

    start = None
    try:
        delta = calc_timedelta_from_time_args(since)
        if delta:
            start = datetime.now() - delta
    except ValueError as e:
        logger.error(e.args[0])
        await message.edit(content=e.args[0])
        return

    end = None
    try:
        delta = calc_timedelta_from_time_args(to)
        if delta:
            end = datetime.now() - delta
    except ValueError as e:
        logger.error(e.args[0])
        await message.edit(content=e.args[0])
        return

    collector.get_user_balance(registered_user, currency=currency)
    user_data = collector.get_single_user_data(registered_user.id, guild_id=registered_user.guild_id, start=start,
                                               end=end, currency=currency)

    if len(user_data) == 0:
        logger.error(f'No data for this user!')
        await message.edit(content=f'Got no data for this user')
        return

    xs, ys = calc_xs_ys(user_data, percentage)

    compare_data = []
    if compare:
        try:
            compare_user = get_user_by_id(USERS_BY_ID, compare.id, guild_id)
        except ValueError as e:
            await message.edit(content=e.args[0].replace('{name}', compare.display_name))
            return
        compare_data = collector.get_single_user_data(compare_user.id, compare_user.guild_id, start=start, end=end,
                                                      currency=currency)

    compare_xs, compare_ys = calc_xs_ys(compare_data, percentage)

    total_gain = calc_percentage(user_data[0][1].amount, user_data[len(ys) - 1][1].amount)
    title = f'History for {user.display_name} (Total gain: {total_gain}%)'
    plt.plot(xs, ys, label=f"{user.display_name}'s {currency_raw} Balance")

    if compare:
        total_gain = calc_percentage(compare_data[0][1].amount, compare_data[len(compare_ys) - 1][1].amount)
        plt.plot(compare_xs, compare_ys, label=f"{compare.display_name}'s {currency_raw} Balance")
        title += f' vs. {compare.display_name} (Total gain: {total_gain}%)'

    plt.gcf().autofmt_xdate()
    plt.gcf().set_dpi(100)
    plt.gcf().set_size_inches(8, 5.5)
    plt.title(title)
    plt.ylabel(currency_raw)
    plt.xlabel('Time')
    plt.grid()
    plt.legend(loc="best")

    plt.savefig(DATA_PATH + "tmp.png")
    plt.close()
    file = discord.File(DATA_PATH + "tmp.png", "history.png")

    await message.edit(content='', file=file)


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
            description="User to compare with",
            required=False,
            option_type=SlashCommandOptionType.USER
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
@server_only
async def history(ctx,
                  user: discord.Member = None,
                  compare: discord.Member = None,
                  since: str = None, to: str = None,
                  currency: str = None):
    if user is None:
        user = ctx.author
    if currency is None:
        currency = '$'
    currency = currency.upper()

    message = await ctx.send(f'...')

    asyncio.create_task(
        create_history(message, user, guild_id=ctx.guild.id, currency=currency, compare=compare, since=since, to=to)
    )


def calc_gains(users: List[User],
               search: datetime,
               currency: str = None,
               since_start=False) -> List[Tuple[User, Tuple[float, float]]]:
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

    user_data = collector.get_user_data()
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
                        balance_then = collector.match_balance_currency(balance_then, currency)

                    if not balance_then:
                        balance_then = collector.get_balance_from_data(data, user.id, user.guild_id, exact=True)
                        balance_then = collector.match_balance_currency(balance_then, currency)

                    if balance_then:
                        balance_now = collector.get_latest_user_balance(user.id,
                                                                        guild_id=user.guild_id,
                                                                        currency=currency)
                        if balance_now:
                            users_left.remove(user)
                            diff = balance_now.amount - balance_then.amount
                            if balance_then.amount > 0:
                                results.append((user, (100 * (diff / balance_then.amount), diff)))
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
async def gain(ctx, user: discord.Member = None, time: str = None, currency: str = None):
    if user is None:
        user = ctx.author

    time_str = time
    if time_str is None:
        time_str = 'total'

    if currency is None:
        currency = '$'
    currency = currency.upper()

    logger.info(f'New Interaction with {ctx.author}: Calculate gain for {de_emojify(user.display_name)} {time_str=}')

    users = []
    if ctx.guild:
        try:
            registered_user = get_user_by_id(USERS_BY_ID, user.id, None if not ctx.guild else ctx.guild.id)
            users = [registered_user]
        except ValueError as e:
            await ctx.send(content=e.args[0].replace('{name}', user.display_name))
            return
    elif user.id in USERS_BY_ID:
        users = list(USERS_BY_ID[user.id].values())
    else:
        await ctx.send(f'You are not registered.')
    since_start = time_str == 'start' or time_str == 'all' or time_str == 'total'

    if since_start:
        delta = timedelta(0)
    else:
        try:
            delta = calc_timedelta_from_time_args(time)
        except ValueError as e:
            logger.error(e.args[0])
            await ctx.send(content=e.args[0].replace('{name}', user.display_name))
            return

    time = datetime.now()
    search = time - delta
    collector.fetch_data(users=users)
    user_gains = calc_gains(users, search, currency, since_start=since_start)

    for cur_user, user_gain in user_gains:
        guild = client.get_guild(ctx.guild_id)
        if ctx.guild:
            gain_message = f'{user.display_name}\'s {time_str} gain: '
        else:
            gain_message = "Your gain: " if not guild else f"Your gain on {guild}: "
        if user_gain is None:
            logger.info(f'Not enough data for calculating {de_emojify(user.display_name)}\'s {time_str} gain on guild {guild}')
            if ctx.guild:
                await ctx.send(f'Not enough data for calculating {user.display_name}\'s {time_str} gain')
            else:
                await ctx.send(f'Not enough data for calculating your {time_str} gain on {guild}')
        else:
            user_gain_rel, user_gain_abs = user_gain
            await ctx.send(f'{gain_message}{round(user_gain_rel, ndigits=3)}% ({round(user_gain_abs, ndigits=CURRENCY_PRECISION.get(currency, 3))}{currency})')


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
            description="Your API Key",
            required=True,
            option_type=3
        ),
        create_option(
            name="api_secret",
            description="Your API Secret",
            required=True,
            option_type=3
        ),
        create_option(
            name="subaccount",
            description="Subaccount for API Access",
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
                    await ctx.send(f'Invalid keyword argument: {arg} syntax for keyword arguments: key1=value1 key2=value2 ...',
                                   hidden=True)
                    logging.error(f'Invalid Keyword Arg {arg} passed in')

    try:
        exchange_name = exchange_name.lower()
        exchange_cls = EXCHANGES[exchange_name]
        if issubclass(exchange_cls, Client):
            # Check if required keyword args are given
            if len(kwargs.keys()) >= len(exchange_cls.required_extra_args) and \
                    all(required_kwarg in kwargs for required_kwarg in exchange_cls.required_extra_args):
                exchange: Client = exchange_cls(
                    api_key=api_key,
                    api_secret=api_secret,
                    subaccount=subaccount,
                    extra_kwargs=kwargs
                )
                existing_user = get_user_by_id(USERS_BY_ID, ctx.author.id, guild, exact=True, throw_exceptions=False)
                if existing_user:
                    existing_user.api = exchange
                    await ctx.send(embed=existing_user.get_discord_embed(client.get_guild(guild)), hidden=True)
                    logger.info(f'Updated user')
                    save_registered_users()
                else:
                    new_user = User(
                        ctx.author.id,
                        exchange,
                        guild_id=guild
                    )

                    init_balance = new_user.api.get_balance()
                    if init_balance.error is None:
                        message = f'Your balance: **{init_balance.to_string()}**. This will be used as your initial balance. Is this correct?\nYes will register you, no will cancel the process.'

                        def register_user():
                            new_user.initial_balance = (datetime.now(), init_balance)

                            USERS.append(new_user)
                            if new_user.id not in USERS_BY_ID:
                                USERS_BY_ID[new_user.id] = {}

                            USERS_BY_ID[new_user.id][guild] = new_user
                            collector.add_user(new_user)
                            save_registered_users()
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
        registered_user = get_user_by_id(USERS_BY_ID, ctx.author.id, guild, exact=False)
    except ValueError as e:
        await ctx.send(e.args[0].replace('{name}', ctx.author.display_name), hidden=True)
        return

    def unregister_user():
        collector.clear_user_data(registered_user)
        USERS_BY_ID[registered_user.id].pop(registered_user.guild_id)

        if len(USERS_BY_ID[registered_user.id]) == 0:
            USERS_BY_ID.pop(registered_user.id)

        USERS.remove(registered_user)
        collector.remove_user(registered_user)
        save_registered_users()
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
    if ctx.author.id in USERS_BY_ID:
        registrations = USERS_BY_ID[ctx.author.id]
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
async def clear(ctx, since: str = None, to: str = None, guild: str = None):
    logging.info(f'New interaction with {de_emojify(ctx.author.display_name)}: clear history {since=} {to=}')

    if guild:
        guild = int(guild)

    try:
        registered_user = get_user_by_id(USERS_BY_ID, ctx.author.id, guild)
    except ValueError as e:
        await ctx.send(e.args[0].replace('{name}', ctx.author.display_name), hidden=True)
        return

    start = None
    try:
        delta = calc_timedelta_from_time_args(since)
        if delta:
            start = datetime.now() - delta
    except ValueError as e:
        logger.error(e.args[0])
        await ctx.send(e.args[0], hidden=True)
        return

    end = None
    try:
        delta = calc_timedelta_from_time_args(to)
        if delta:
            end = datetime.now() - delta
    except ValueError as e:
        logger.error(e.args[0])
        await ctx.send(e.args[0], hidden=True)
        return

    from_to = ''
    if start:
        from_to += f' since **{start}**'
    if end:
        from_to += f' till **{end}**'

    def clear_user():
        collector.clear_user_data(registered_user,
                                  start=start,
                                  end=end,
                                  remove_all_guilds=True,
                                  update_initial_balance=True)
        save_registered_users()

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


async def create_leaderboard(ctx: SlashContext, guild: discord.Guild, mode: str, time: str):
    user_scores: List[Tuple[User, float]] = []
    value_strings: Dict[User, str] = {}
    users_rekt: List[User] = []
    users_missing: List[User] = []

    footer = ''
    description = ''

    date, data = collector.fetch_data()
    if mode == 'balance':
        for user_id in USERS_BY_ID:
            user = get_user_by_id(USERS_BY_ID, user_id, guild.id, throw_exceptions=False)
            if user and guild.get_member(user_id):
                if user.rekt_on:
                    users_rekt.append(user)
                else:
                    balance = collector.get_balance_from_data(data, user.id, user.guild_id)
                    if not balance:
                        balance = collector.get_latest_user_balance(user.id)
                    if balance is None:
                        users_missing.append(user)
                    elif balance.amount > REKT_THRESHOLD:
                        user_scores.append((user, balance.amount))
                        value_strings[user] = balance.to_string()
                    else:
                        users_rekt.append(user)

        date = date.replace(microsecond=0)
        footer += f'Data used from: {date}'
    elif mode == 'gain':

        since_start = time == 'all' or time == 'start' or time == 'total'

        if not since_start:
            try:
                delta = calc_timedelta_from_time_args(time)
            except ValueError as e:
                logging.error(e.args[0])
                await ctx.send(content=e.args[0])
                return
        else:
            delta = timedelta(0)

        time = datetime.now()
        search = (time - delta).replace(microsecond=0)

        if since_start:
            description += f'Gain since start\n\n'
        else:
            description += f'Gain since {search}\n\n'

        users = []
        for user_id in USERS_BY_ID:
            user = get_user_by_id(USERS_BY_ID, user_id, guild.id, throw_exceptions=False)
            if user and guild.get_member(user.id):
                users.append(user)
        user_gains = calc_gains(users, search, since_start=since_start)

        for user, user_gain in user_gains:
            if user_gain is not None:
                if user.rekt_on:
                    users_rekt.append(user)
                else:
                    user_gain_rel, user_gain_abs = user_gain
                    user_scores.append((user, user_gain_rel))
                    value_strings[user] = f'{round(user_gain_rel, ndigits=2)}% ({round(user_gain_abs, ndigits=2)}$)'
            else:
                users_missing.append(user)
    else:
        logging.error(f'Unknown mode {mode} was passed in')
        await ctx.send(f'Unknown mode {mode}')
        return

    user_scores.sort(key=lambda x: x[1], reverse=True)
    rank = 1

    if len(user_scores) > 0:
        prev_score = None
        for user, score in user_scores:
            member = guild.get_member(user.id)
            if member:
                if prev_score is not None and score < prev_score:
                    rank += 1
                if user in value_strings:
                    value = value_strings[user]
                    description += f'{rank}. **{member.display_name}** {value}\n'
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
    logger.info(f'New Interaction: Creating balance leaderboard, requested by user {de_emojify(ctx.author.display_name)}')
    await ctx.defer()
    await create_leaderboard(ctx, guild=ctx.guild, mode='balance', time='24h')


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
@server_only
async def leaderboard_gain(ctx: SlashContext, time: str = None):
    logger.info(f'New Interaction: Creating balance leaderboard, requested by user {de_emojify(ctx.author.display_name)}')

    if not time:
        time = 'start'

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


def load_registered_users():
    try:
        with open(DATA_PATH + 'users.json', 'r') as f:
            users_json = json.load(fp=f)
            for user_json in users_json:
                try:
                    user = user_from_json(user_json, EXCHANGES)
                    if user.id not in USERS_BY_ID:
                        USERS_BY_ID[user.id] = {}
                    USERS_BY_ID[user.id][user.guild_id] = user
                    USERS.append(user)
                except KeyError as e:
                    logger.error(f'{e} occurred while parsing user data {user_json} from users.json')
    except FileNotFoundError:
        logger.info(f'No user information found')


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
        value="You can register using the **/register** command in the private message of the bot.\n"
              "You have to pass in which exchange you are using and an api access (key, secret). This access can and should be **read only**.\n"
              "Also make sure to pass in the name of your subaccount (optional parameter), if you use one.\n\n"
              "The bot will try to read your balance and ask if it is correct. To confirm, send a message \"y\" for yes or \"n\" if the result is not correct.",
        inline=False
    )
    # embed.add_field(
    #     name=""
    # )
    await ctx.send(embed=embed)


def save_registered_users():
    with open(DATA_PATH + 'users.json', 'w') as f:
        users_json = [user.to_json() for user in USERS]
        json.dump(obj=users_json, fp=f, indent=3)


async def on_rekt_async(user: User):
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

    save_registered_users()

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

if os.path.exists(DATA_PATH):
    load_registered_users()
else:
    os.mkdir(DATA_PATH)

collector = DataCollector(USERS,
                          fetching_interval_hours=FETCHING_INTERVAL_HOURS,
                          data_path=DATA_PATH,
                          rekt_threshold=REKT_THRESHOLD,
                          on_rekt_callback=lambda user: client.loop.create_task(on_rekt_async(user)))

client.run(KEY)
