import asyncio
import logging
import os
import random
import sys
import discord
import json
import typing
import time
import re

from discord_slash.model import BaseCommandObject
from discord_slash import SlashCommand, SlashContext, SlashCommandOptionType
from discord_slash.utils.manage_commands import create_choice, create_option
from discord.ext import commands
from typing import List, Dict, Type, Tuple, Union, Optional
from datetime import datetime, timedelta
from random import Random

import matplotlib.pyplot as plt

from balance import Balance, balance_from_json
from user import User, user_from_json
from client import Client
from datacollector import DataCollector
from dialogue import Dialogue, YesNoDialogue
from key import KEY
from config import DATA_PATH, PREFIX, FETCHING_INTERVAL_HOURS, REKT_MESSAGES, LOG_OUTPUT_DIR, REKT_GUILDS, \
    CURRENCY_PRECISION, REKT_THRESHOLD

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

USERS_BY_ID: Dict[int, Dict[int, User]] = {}

EXCHANGES: Dict[str, Type[Client]] = {
    'binance': BinanceClient,
    'bitmex': BitmexClient,
    'ftx': FtxClient,
    'kucoin': KuCoinClient,
    'bybit': BybitClient
}

OPEN_DIALOGUES: Dict[int, Dialogue] = {}


def dm_only(coro):
    async def wrapper(ctx, *args, **kwargs):
        if ctx.guild:
            await ctx.send('This command can only be used via a Private Message.')
            return
        return await coro(ctx, *args, **kwargs)

    return wrapper


def server_only(coro):
    async def wrapper(ctx: SlashContext, *args, **kwargs):
        if not ctx.guild:
            await ctx.send('This command can only be used in a server.')
            return
        return await coro(ctx, *args, **kwargs)

    return wrapper


# Thanks Stackoverflow
def de_emojify(text):
    regrex_pattern = re.compile("["
                                u"\U0001F600-\U0001F64F"  # emoticons
                                u"\U0001F300-\U0001F5FF"  # symbols & pictographs
                                u"\U0001F680-\U0001F6FF"  # transport & map symbols
                                u"\U0001F1E0-\U0001F1FF"  # flags (iOS)
                                u"\U00002500-\U00002BEF"  # chinese char
                                u"\U00002702-\U000027B0"
                                u"\U00002702-\U000027B0"
                                u"\U000024C2-\U0001F251"
                                u"\U0001f926-\U0001f937"
                                u"\U00010000-\U0010ffff"
                                u"\u2640-\u2642"
                                u"\u2600-\u2B55"
                                u"\u200d"
                                u"\u23cf"
                                u"\u23e9"
                                u"\u231a"
                                u"\ufe0f"  # dingbats
                                u"\u3030"
                                "]+", re.UNICODE)
    return regrex_pattern.sub(r'', text)


def get_user_by_id(user_id: int,
                   guild_id: int = None,
                   exact: bool = False,
                   throw_exceptions=True) -> User:
    """
    Tries to find a matching entry for the user and guild id.
    :param exact: whether the global entry should be used if the guild isn't registered
    :return:
    The found user. It will never return None if throw_exceptions is True, since an ValueError exception will be thrown instead.
    """
    result = None

    if user_id in USERS_BY_ID:
        endpoints = USERS_BY_ID[user_id]
        if isinstance(endpoints, dict):
            result = endpoints.get(guild_id, None)
            if not result and not exact:
                result = endpoints.get(None, None)  # None entry is global
            if not result and throw_exceptions:
                raise ValueError("User {name} not registered for this guild")
        else:
            logger.error(
                f'USERS_BY_ID contains invalid entry! Associated data with {user_id=}: {result=} {endpoints=} ({guild_id=})')
            if throw_exceptions:
                raise ValueError("This is caused due to a bug in the bot. Please contact dev.")
    elif throw_exceptions:
        logger.error(f'Dont know user {user_id=}')
        raise ValueError("Unknown user {name}. Please register first.")

    return result


def add_guild_option(command: BaseCommandObject, description: str):
    command.options.append(
        create_option(
            name="guild",
            description=description,
            required=False,
            option_type=SlashCommandOptionType.STRING,
            choices=[
                create_choice(
                    name=guild.name,
                    value=str(guild.id)
                ) for guild in client.guilds
            ]
        )
    )


@client.event
async def on_ready():
    register_command: BaseCommandObject = slash.commands['register']
    unregister_command: BaseCommandObject = slash.commands['unregister']
    clear_command: BaseCommandObject = slash.commands['clear']
    add_guild_option(register_command, 'Guild to register this access for. If not given, it will be global.')
    add_guild_option(unregister_command, 'Which guild access to unregister. If not given, it will be global.')
    add_guild_option(clear_command, 'Which guild to clear your data for. If not given, it will be global.')

    collector.start_fetching()

    logger.info('Bot Ready')
    print('Bot Ready.')
    await slash.sync_all_commands()


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
    await slash.sync_all_commands()


@client.event
async def on_message(message: discord.Message):
    if message.author.id in OPEN_DIALOGUES and message.guild is None:

        open_dialogue = OPEN_DIALOGUES[message.author.id]

        if open_dialogue.possible_inputs:
            if message.content not in open_dialogue.possible_inputs:
                await message.channel.send(open_dialogue.invalid_choice_message)
                return

        if open_dialogue.success_message:
            await message.channel.send(open_dialogue.success_message)

        await open_dialogue.choice_callback(message.channel, message.content)

        OPEN_DIALOGUES.pop(message.author.id)


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
@server_only
async def balance(ctx, user: discord.Member = None, currency: str = None):
    if user is None:
        user = ctx.author
    if currency is None:
        currency = '$'
    currency = currency.upper()

    logger.info(
        f'New interaction with {ctx.author.display_name}: Get balance for {de_emojify(user.display_name)} ({currency=})')

    try:
        registered_user = get_user_by_id(user.id, None if not ctx.guild else ctx.guild.id)
    except ValueError as e:
        await ctx.send(e.args[0].replace('{name}', user.display_name))
        return

    usr_balance = collector.get_user_balance(registered_user, currency)
    if usr_balance.error is None:
        await ctx.send(f'{user.display_name}\'s balance: {usr_balance.to_string()}')
    else:
        await ctx.send(f'Error while getting {user.display_name}\'s balance: {usr_balance.error}')


async def create_history(message: discord.Message,
                         user: discord.Member,
                         guild_id: int,
                         currency: str,
                         compare: discord.Member = None,
                         since: str = None,
                         to: str = None):
    logger.info(f'New interaction with {de_emojify(user.display_name)}: Show history')

    try:
        registered_user = get_user_by_id(user.id, guild_id)
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

    user_data = collector.get_single_user_data(registered_user.id, guild_id=registered_user.guild_id, start=start,
                                               end=end, currency=currency)

    if len(user_data) == 0:
        logger.error(f'No data for this user!')
        await message.edit(content=f'Got no data for this user')
        return

    xs = []
    ys = []
    for time, balance in user_data:
        xs.append(time.replace(microsecond=0))
        ys.append(round(balance.amount, ndigits=CURRENCY_PRECISION.get(balance.currency, 3)))

    compare_data = []
    if compare:
        try:
            compare_user = get_user_by_id(compare.id, guild_id)
        except ValueError as e:
            await message.edit(content=e.args[0].replace('{name}', compare.display_name))
            return
        compare_data = collector.get_single_user_data(compare_user.id, compare_user.guild_id, start=start, end=end,
                                                      currency=currency)

    compare_xs = []
    compare_ys = []
    for time, balance in compare_data:
        compare_xs.append(time.replace(microsecond=0))
        compare_ys.append(balance.amount)

    diff = ys[len(ys) - 1] - ys[0]
    if diff == 0.0:
        total_gain = f'0'
    elif ys[0] > 0:
        total_gain = f'{round(100 * (diff / ys[0]), ndigits=3)}'
    else:
        total_gain = 'inf'

    title = f'History for {user.display_name} (Total gain: {total_gain}%)'
    plt.plot(xs, ys, label=f"{user.display_name}'s {currency} Balance")

    if compare:
        diff = compare_ys[len(compare_ys) - 1] - compare_ys[0]
        if diff == 0.0:
            total_gain = '0'
        elif compare_ys[0] > 0:
            total_gain = f'{round(100 * (diff / compare_ys[0]), ndigits=3)}'
        else:
            total_gain = 'inf'
        plt.plot(compare_xs, compare_ys, label=f"{compare.display_name}'s {currency} Balance")
        title += f' vs. {compare.display_name} (Total gain: {total_gain}%)'

    plt.gcf().autofmt_xdate()
    plt.gcf().set_dpi(100)
    plt.gcf().set_size_inches(8, 5.5)
    plt.title(title)
    plt.ylabel(currency)
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


def calc_timedelta_from_time_args(time_str: str) -> timedelta:
    """
    Calculates timedelta from given time args.
    Arg Format:
      <n><f>
      where <f> can be m (minutes), h (hours), d (days) or w (weeks)

      or valid time string

    :raise:
      ValueError if invalid arg is given
    :return:
      Calculated timedelta or None if None was passed in
    """

    if not time_str:
        return None

    time_str = time_str.lower()

    # Different time formats: True or False indicates whether the date is included.
    formats = [
        (False, "%H:%M:%S"),
        (False, "%H:%M"),
        (False, "%H"),
        (True, "%d.%m.%Y %H:%M:%S"),
        (True, "%d.%m.%Y %H:%M"),
        (True, "%d.%m.%Y %H"),
        (True, "%d.%m.%Y"),
        (True, "%d.%m. %H:%M:%S"),
        (True, "%d.%m. %H:%M"),
        (True, "%d.%m. %H"),
        (True, "%d.%m.")
    ]

    delta = None
    for includes_date, time_format in formats:
        try:
            date = datetime.strptime(time_str, time_format)
            now = datetime.now()
            if not includes_date:
                date = date.replace(year=now.year, month=now.month, day=now.day, microsecond=0)
            elif date.year == 1900:  # %d.%m. not setting year to 1970 but to 1900?
                date = date.replace(year=now.year)
            delta = datetime.now() - date
            break
        except ValueError:
            continue

    if not delta:
        minute = 0
        hour = 0
        day = 0
        week = 0
        args = time_str.split(' ')
        if len(args) > 0:
            for arg in args:
                try:
                    if 'h' in arg:
                        hour += int(arg.rstrip('h'))
                    elif 'm' in arg:
                        minute += int(arg.rstrip('m'))
                    elif 'w' in arg:
                        week += int(arg.rstrip('w'))
                    elif 'd' in arg:
                        day += int(arg.rstrip('d'))
                    else:
                        raise ValueError
                except ValueError:  # Make sure both cases are treated the same
                    raise ValueError(f'Invalid time argument: {arg}')
        delta = timedelta(hours=hour, minutes=minute, days=day, weeks=week)

    if not delta:
        raise ValueError(f'Invalid time argument: {time_str}')
    elif delta.total_seconds() <= 0:
        raise ValueError(f'Time delta can not be zero. {time_str}')

    return delta


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
    Gain for each user is stored in a list as a tuple containing user object and tuple containing relative gain and absolute gain
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
@server_only
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

    try:
        registered_user = get_user_by_id(user.id, None if not ctx.guild else ctx.guild.id)
    except ValueError as e:
        await ctx.send(content=e.args[0].replace('{name}', user.display_name))
        return

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
    user_gain = calc_gains([registered_user], search, currency, since_start=since_start)[0][1]

    if user_gain is None:
        logger.info(f'Not enough data for calculating {de_emojify(user.display_name)}\'s {time_str} gain')
        await ctx.send(f'Not enough data for calculating {user.display_name}\'s {time_str}  gain')
    else:
        user_gain_rel, user_gain_abs = user_gain
        await ctx.send(
            f'{user.display_name}\'s {time_str} gain: {round(user_gain_rel, ndigits=3)}% ({round(user_gain_abs, ndigits=CURRENCY_PRECISION.get(currency, 3))}{currency})')


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
    ]
)
@dm_only
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
                        f'Invalid keyword argument: {arg} syntax for keyword arguments: key1=value1 key2=value2 ...')
                    logging.error(f'Invalid Keyword Arg {arg} passed in')

    try:
        exchange_name = exchange_name.lower()
        exchange_cls = EXCHANGES[exchange_name]
        if issubclass(exchange_cls, Client):
            # Check if required keyword args are given
            if len(kwargs.keys()) >= len(exchange_cls.required_extra_args) and all(
                    required_kwarg in kwargs for required_kwarg in exchange_cls.required_extra_args):
                exchange: Client = exchange_cls(
                    api_key=api_key,
                    api_secret=api_secret,
                    subaccount=subaccount,
                    extra_kwargs=kwargs
                )
                existing_user = get_user_by_id(ctx.author.id, guild, exact=True, throw_exceptions=False)
                if existing_user:
                    existing_user.api = exchange
                    await ctx.send(embed=existing_user.get_discord_embed(client.get_guild(guild)))
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
                        message = f'Your balance: **{init_balance.to_string()}**. This will be used as your initial balance. Is this correct?\nYes will register you, no will cancel the process. (y/n)'
                    else:
                        message = f'An error occured while getting your balance: {init_balance.error}.'

                    await ctx.send(
                        content=message,
                        embed=new_user.get_discord_embed(client.get_guild(guild))
                    )

                    def register_user():
                        new_user.initial_balance = (datetime.now(), init_balance)

                        USERS.append(new_user)
                        if new_user.id not in USERS_BY_ID:
                            USERS_BY_ID[new_user.id] = {}
                        USERS_BY_ID[new_user.id][guild] = new_user
                        collector.add_user(new_user)
                        logger.info(f'Registered new user')
                        save_registered_users()

                    OPEN_DIALOGUES[ctx.author.id] = YesNoDialogue(
                        yes_callback=register_user,
                        yes_message='You were successfully registered!',
                        no_message='Registration canceled.'
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
@dm_only
async def unregister(ctx, guild: str = None):
    if guild:
        guild = int(guild)

    logger.info(f'New Interaction with {ctx.author.display_name}: Trying to unregister user {ctx.author.display_name}')

    try:
        registered_user = get_user_by_id(ctx.author.id, guild, exact=False)
    except ValueError as e:
        await ctx.send(e.args[0].replace('{name}', ctx.author.display_name))
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

    guild_name = ""
    if guild:
        guild_name = f' from {client.get_guild(guild).name}'
    await ctx.send(f'Do you really want to unregister{guild_name}? This will **delete all your data**. (y/n)')

    OPEN_DIALOGUES[ctx.author.id] = YesNoDialogue(
        yes_callback=unregister_user,
        yes_message='You were successfully unregistered!',
        no_message='Unregistration cancelled.'
    )


@slash.slash(
    name="info",
    description="Shows your stored information",
    options=[]
)
@dm_only
async def info(ctx):
    if ctx.author.id in USERS_BY_ID:
        registrations = USERS_BY_ID[ctx.author.id]
        for registration in registrations.values():
            guild_name = client.get_guild(registration.guild_id)
            await ctx.send(embed=registration.get_discord_embed(guild_name))
    else:
        await ctx.send(f'You are not registered.')


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
@dm_only
async def clear(ctx, since: str = None, to: str = None, guild: str = None):
    logging.info(f'New interaction with {de_emojify(ctx.author.display_name)}: clear history {since=} {to=}')

    if guild:
        guild = int(guild)

    try:
        registered_user = get_user_by_id(ctx.author.id, guild)
    except ValueError as e:
        await ctx.send(e.args[0].replace('{name}', ctx.author.display_name))
        return

    start = None
    try:
        delta = calc_timedelta_from_time_args(since)
        if delta:
            start = datetime.now() - delta
    except ValueError as e:
        logger.error(e.args[0])
        await ctx.send(e.args[0])
        return

    end = None
    try:
        delta = calc_timedelta_from_time_args(to)
        if delta:
            end = datetime.now() - delta
    except ValueError as e:
        logger.error(e.args[0])
        await ctx.send(e.args[0])
        return

    from_to = ''
    if start:
        from_to += f' since **{start}**'
    if end:
        from_to += f' till **{end}**'

    await ctx.send(f'Do you really want to **delete** your history{from_to}? (y/n)')

    def clear_user():
        collector.clear_user_data(registered_user,
                                  start=start,
                                  end=end,
                                  remove_all_guilds=True,
                                  update_initial_balance=True)
        save_registered_users()

    OPEN_DIALOGUES[ctx.author.id] = YesNoDialogue(
        yes_callback=clear_user,
        yes_message=f'Deleted your history{from_to}',
        no_message=f'Clear cancelled.',
    )


async def create_leaderboard(message, guild: discord.Guild, mode: str, time: str):
    user_scores: List[Tuple[User, float]] = []
    value_strings: Dict[User, str] = {}
    users_rekt: List[User] = []
    users_missing: List[User] = []

    footer = ''
    description = ''

    date, data = collector.fetch_data(guild_id=guild.id)
    if mode == 'balance':
        for user_id in USERS_BY_ID:
            user = get_user_by_id(user_id, guild.id, throw_exceptions=False)
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
                await message.edit(content=e.args[0])
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
            user = get_user_by_id(user_id, guild.id, throw_exceptions=False)
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
                    value_strings[user] = f'{round(user_gain_rel, ndigits=1)}% ({round(user_gain_abs, ndigits=2)}$)'
            else:
                users_missing.append(user)
    else:
        logging.error(f'Unknown mode {mode} was passed in')
        await message.edit(f'Unknown mode {mode}')
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
    await message.edit(content='', embed=embed)


@slash.subcommand(
    base="leaderboard",
    name="balance",
    description="Shows you the highest ranked users by $ balance",
    options=[]
)
@server_only
async def leaderboard_balance(ctx: SlashContext):
    logger.info(f'New Interaction: Creating balance leaderboard, requested by user {de_emojify(ctx.author.display_name)}')

    message = await ctx.send('...')

    asyncio.create_task(
        create_leaderboard(message=message, guild=ctx.guild, mode='balance', time='24h')
    )


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

    message = await ctx.send('...')

    asyncio.create_task(
        create_leaderboard(message=message, guild=ctx.guild, mode='gain', time=time)
    )


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
                    "jacksn#9149."
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
            logger.error(f'Invalid guild {guild_data} {e}')
        except AttributeError as e:
            logger.error(f'Error while sending message to guild {e}')

    save_registered_users()


def on_rekt(user: User):
    try:
        # First time this might be called is after start, in which case there's already an event loop running
        asyncio.create_task(on_rekt_async(user))
    except RuntimeError:
        asyncio.run(on_rekt_async(user))


logger = setup_logger(debug=False)

if os.path.exists(DATA_PATH):
    load_registered_users()
else:
    os.mkdir(DATA_PATH)

collector = DataCollector(USERS,
                          fetching_interval_hours=FETCHING_INTERVAL_HOURS,
                          data_path=DATA_PATH,
                          rekt_threshold=REKT_THRESHOLD,
                          on_rekt_callback=on_rekt)

client.run(KEY)
