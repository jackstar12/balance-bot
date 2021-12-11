import asyncio
import logging
import os
import random
import sys
import discord
import json
import typing
import time

from discord_slash import SlashCommand, SlashContext
from discord_slash.utils.manage_commands import create_choice, create_option
from discord.ext import commands
from typing import List, Dict, Type, Tuple
from datetime import datetime, timedelta
from random import Random

import matplotlib.pyplot as plt
import matplotlib.image as mpimg

from balance import Balance
from user import User
from client import Client
from datacollector import DataCollector
from config import DATA_PATH, PREFIX, FETCHING_INTERVAL_HOURS, KEY, REKT_MESSAGES, LOG_OUTPUT_DIR, REKT_GUILDS, \
    SLASH_GUILD_IDS, INITIAL_BALANCE, CURRENCY_PRECISION

from Exchanges.binance import BinanceClient
from Exchanges.bitmex import BitmexClient
from Exchanges.ftx import FtxClient
from Exchanges.kucoin import KuCoinClient
from Exchanges.bybit import BybitClient

intents = discord.Intents().default()
intents.members = True
intents.guilds = True

client = commands.Bot(command_prefix=PREFIX, intents=intents)
slash = SlashCommand(client, sync_commands=True)

USERS: List[User] = []

USERS_BY_ID: Dict[int, User] = {}

EXCHANGES: Dict[str, Type[Client]] = {
    'binance': BinanceClient,
    'bitmex': BitmexClient,
    'ftx': FtxClient,
    'kucoin': KuCoinClient,
    'bybit': BybitClient
}


@client.event
async def on_ready():
    logger.info('Bot Ready')
    collector.start_fetching()


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
    hasMatch = False
    for cur_user in USERS:
        if user.id == cur_user.id:
            usr_balance = collector.get_user_balance(cur_user, currency)
            if usr_balance.error is None:
                await ctx.send(f'{user.display_name}\'s balance: {round(usr_balance.amount, ndigits=CURRENCY_PRECISION.get(currency, 3))}{usr_balance.currency}')
            else:
                await ctx.send(f'Error while getting {user.display_name}\'s balance: {usr_balance.error}')
            hasMatch = True
            break
    if not hasMatch:
        await ctx.send('User unknown. Please register via a DM first.')


@slash.slash(
    name="history",
    description="Draws balance history of a user",
    options=[
        create_option(
            name="user",
            description="User to graph",
            required=False,
            option_type=6
        ),
        create_option(
            name="compare",
            description="User to compare with",
            required=False,
            option_type=6
        ),
        create_option(
            name="since",
            description="Start time for graph",
            required=False,
            option_type=3
        ),
        create_option(
            name="to",
            description="End time for graph",
            required=False,
            option_type=3
        ),
        create_option(
            name="currency",
            description="Currency to display history for (only available for some exchanges)",
            required=False,
            option_type=3
        )
    ],
    guild_ids=SLASH_GUILD_IDS
)
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

    logger.info(f'New interaction with {user.display_name}: Show history')

    if user.id in USERS_BY_ID:

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

        user_data = collector.get_single_user_data(user.id, start=start, end=end, currency=currency)

        if len(user_data) == 0:
            logger.error(f'No data for this user!')
            await ctx.send(f'Got no data for {ctx.author.display_name}')
            return

        xs = []
        ys = []
        for time, balance in user_data:
            xs.append(time.replace(microsecond=0))
            ys.append(balance.amount)

        compare_data = []
        if compare:
            if compare.id in USERS_BY_ID:
                compare_data = collector.get_single_user_data(compare.id, start=start, end=end, currency=currency)
            else:
                logger.error(f'User {compare} cant be compared with because he isn\'t registered')
                await ctx.send(f'Compare user unknown. Please register first.')
                return

        compare_xs = []
        compare_ys = []
        for time, balance in compare_data:
            compare_xs.append(time)
            compare_ys.append(balance.amount)

        diff = ys[len(ys) - 1] - ys[0]
        if ys[0] > 0:
            total_gain = f'{round(100 * (diff / ys[0]), ndigits=3)}'
        else:
            total_gain = 'inf'

        name = ctx.guild.get_member(user.id).display_name
        title = f'History for {name} (Total gain: {total_gain}%)'

        plt.plot(xs, ys, label=f"{name}'s {currency} Balance")
        if compare:
            compare_name = ctx.guild.get_member(compare.id).display_name

            diff = compare_ys[len(ys) - 1] - compare_ys[0]
            if compare_ys[0] > 0:
                total_gain = f'{round(100 * (diff / compare_ys[0]), ndigits=3)}'
            else:
                total_gain = 'inf'

            plt.plot(compare_xs, compare_ys, label=f"{compare_name}'s {currency} Balance")
            title += f' vs. {compare_name} (Total gain: {total_gain}%)'
        plt.gcf().autofmt_xdate()
        plt.gcf().set_dpi(100)
        plt.title(title)
        plt.ylabel(currency)
        plt.xlabel('Time')
        plt.grid()
        plt.legend(loc="best")
        plt.savefig(DATA_PATH + "tmp.png")
        plt.close()

        file = discord.File(DATA_PATH + "tmp.png", "history.png")
        embed = discord.Embed()
        embed.set_image(url="attachment://history.png")

        await ctx.send(file=file, embed=embed)
    else:
        logger.error(f'User unknown.')
        await ctx.send('User unknown. Please register via a DM first.')


def calc_timedelta_from_time_args(time_str: str) -> timedelta:
    """
    Calculates timedelta from given time args.
    Arg Format:
      <n><f>
      where <f> can be m (minutes), h (hours), d (days) or w (weeks)

    :raise:
      ValueError if invalid arg is given
    :return:
      Calculated timedelta
    """

    if not time_str:
        return None

    # Different time formats: True or False indicates whether the date is included.
    formats = [
        (False, "%H:%M:%S"),
        (True,  "%Y-%m-%d %H:%M:%S"),
        (True,  "%Y-%m-%d"),
        (True,  "%Y/%m/%d %H:%M:%S"),
        (True,  "%Y/%m/%d"),
        (True,  "%d.%m.%Y %H:%M:%S"),
        (True,  "%d.%m.%Y")
    ]

    delta = None
    for includes_date, time_format in formats:
        try:
            date = datetime.strptime(time_str, time_format)
            now = datetime.now()
            if not includes_date:
                date = date.replace(year=now.year, month=now.month, day=now.day, microsecond=0)
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


def calc_gains(users: List[User], search: datetime, currency: str = None) -> List[Tuple[User, Tuple[float, float]]]:
    """
    :param users:
    :param search:
    :return:
    Gain for each user is stored in a list as a tuple containing user object and tuple containing relative gain and absolute gain
    """

    if currency is None:
        currency = '$'

    user_data = collector.get_user_data()
    users_done = []
    results = []
    # Reverse data since latest data is at the top
    for cur_time, data in reversed(user_data):
        cur_diff = cur_time - search
        if cur_diff.total_seconds() <= 0:
            for user in users:
                if user.id not in users_done:
                    try:
                        balance_then = data[user.id]
                        balance_then = collector.match_balance_currency(balance_then, currency)
                        if balance_then:
                            balance_now = collector.get_latest_user_balance(user.id, currency)
                            users_done.append(user.id)
                            diff = balance_now.amount - balance_then.amount
                            if balance_then.amount > 0:
                                results.append((user, (100 * (diff / balance_then.amount), diff)))
                            else:
                                results.append((user, (0.0, diff)))
                    except KeyError:
                        # User isn't included in data set
                        continue
            if len(users) == len(users_done):
                break

    for user in users:
        if user.id not in users_done:
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
            description="Time frame for gain. Default 24h",
            required=False,
            option_type=3
        ),
        create_option(
            name="currency",
            description="Currency to calculate gain for",
            required=False,
            option_type=3
        )
    ],
    guild_ids=SLASH_GUILD_IDS
)
async def gain(ctx, user: discord.Member = None, time: str = None, currency: str = None):

    if user is None:
        user = ctx.author

    if time is None:
        time = '24h'

    if currency is None:
        currency = '$'
    currency = currency.upper()

    time_str = time

    logger.info(f'New Interaction with {ctx.author}: Calculate gain for {user.display_name} {time=}')

    if user is not None:
        if user.id in USERS_BY_ID:
            try:
                delta = calc_timedelta_from_time_args(time)
            except ValueError as e:
                logger.error(e.args[0])
                await ctx.send({e.args[0]})
                return
            if delta.total_seconds() <= 0:
                await ctx.send(f'Time can not be negative or zero. For more information type {PREFIX}help gain')
                return

            time = datetime.now()
            search = time - delta
            user_gain = calc_gains([USERS_BY_ID[user.id]], search, currency)[0][1]

            if user_gain is None:
                logger.info(f'Not enough data for calculating {user.display_name}\'s {time_str} gain')
                await ctx.send(f'Not enough data for calculating {user.display_name}\'s {time_str}  gain')
            else:
                user_gain_rel, user_gain_abs = user_gain
                await ctx.send(f'{user.display_name}\'s {time_str} gain: {round(user_gain_rel, ndigits=3)}% ({round(user_gain_abs, ndigits=CURRENCY_PRECISION.get(currency, 3))}{currency})')
        else:
            logger.error(f'User unknown!')
            await ctx.send('User unknown! Please register via a DM first.')
    else:
        await ctx.send('Please specify a user.')


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
async def register(ctx,
                   exchange_name: str,
                   api_key: str,
                   api_secret: str,
                   subaccount: typing.Optional[str] = None,
                   args: str = None):
    if ctx.guild is not None:
        await ctx.send('This command can only be used via a DM.')
        await ctx.author.send(f'Type {PREFIX}help register.')
        return

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
                    ctx.send(
                        f'Invalid keyword argument: {arg} syntax for keyword arguments: key1=value1 key2=value2 ...')
                    logging.error(f'Invalid Keyword Arg {arg} passed in')

    try:
        exchange_name = exchange_name.lower()
        exchange_cls = EXCHANGES[exchange_name]
        if issubclass(exchange_cls, Client):
            # Check if required keyword args are given
            if len(kwargs.keys()) >= len(exchange_cls.required_extra_args) and all(required_kwarg in kwargs for required_kwarg in exchange_cls.required_extra_args):
                existing = False
                exchange: Client = exchange_cls(
                    api_key=api_key,
                    api_secret=api_secret,
                    subaccount=subaccount,
                    extra_kwargs=kwargs
                )
                for user in USERS:
                    if ctx.author.id == user.id:
                        user.api = exchange
                        await ctx.send(embed=user.get_discord_embed())
                        existing = True
                        logger.info(f'Updated user')
                        break
                if not existing:

                    initial_balance = None
                    try:
                        initial_time = datetime.strptime(INITIAL_BALANCE['date'], "%d/%m/%Y %H:%M:%S")
                        initial_balance = (initial_time, Balance(INITIAL_BALANCE['amount'], currency='$', error=None))
                    except ValueError as e:
                        logger.error(f'{e}: Invalid time string for Initial Balance: {INITIAL_BALANCE["date"]}')
                    except KeyError as e:
                        logger.error(f'{e}: Invalid INITIAL_BALANCE dict. Consider looking into config.example')

                    new_user = User(
                        ctx.author.id,
                        exchange,
                        initial_balance=initial_balance
                    )
                    await ctx.send(embed=new_user.get_discord_embed())
                    USERS.append(new_user)
                    USERS_BY_ID[new_user.id] = new_user
                    collector.add_user(new_user)
                    logger.info(f'Registered new user')
                save_registered_users()
            else:
                logger.error(f'Not enough kwargs for exchange {exchange_cls.exchange} were given.\nGot: {kwargs}\nRequired: {exchange_cls.required_extra_args}')
                args_readable = ''
                for arg in exchange_cls.required_extra_args:
                    args_readable += f'{arg}\n'
                await ctx.send(f'Need more keyword arguments for exchange {exchange_cls.exchange}. \nRequirements:\n {args_readable}')
        else:
            logger.error(f'Class {exchange_cls} is no subclass of Client!')
    except KeyError:
        logger.error(f'Exchange {exchange_name} unknown')
        await ctx.send(f'Exchange {exchange_name} unknown')


@slash.slash(
    name="unregister",
    description="Unregisters you from tracking"
)
async def unregister(ctx):
    if ctx.guild is not None:
        await ctx.send(f'This command can only be used via a DM.')
        return

    logger.error(f'New Interaction with {ctx.author.display_name}: Trying to unregister user {ctx.author.display_name}')

    for user in USERS:
        if ctx.author.id == user.id:
            USERS_BY_ID.pop(user.id)
            USERS.remove(user)
            collector.remove_user(user)
            save_registered_users()
            logger.error(f'Successfully unregistered user {ctx.author.display_name}')
            await ctx.send(f'You were successfully unregistered!')
            return
    logger.error(f'User is not registered')
    await ctx.send(f'You are not registered.')


@slash.slash(
    name="info",
    description="Shows your stored information"
)
async def info(ctx):
    if ctx.guild is not None:
        await ctx.send(f'This command can only be used via a DM.')
        return

    for user in USERS:
        if ctx.author.id == user.id:
            await ctx.send(embed=user.get_discord_embed())
            return
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
async def clear(ctx, since: str = None, to: str = None):

    logging.info(f'New interaction with {ctx.author.display_name}: clear history {since=} {to=}')

    if ctx.author.id in USERS_BY_ID:

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

        message = f'Deleting your history'
        if start:
            message += f' since {start}'
        if end:
            message += f' till {end}'
        await ctx.send(message)
        collector.clear_user_data(ctx.author.id, start, end)
    else:
        logger.error(f'User not registered.')
        await ctx.send(f'You are not registered.')


async def calc_leaderboard(message, guild: discord.Guild, mode: str, time: str):
    user_scores: List[Tuple[User, float]] = []
    custom_user_strings: Dict[User, str] = {}
    users_rekt: List[User] = []
    users_missing: List[User] = []

    footer = ''
    description = ''

    date, data = collector.fetch_data()
    if mode == 'balance':
        for user in USERS:
            if user.rekt_on:
                users_rekt.append(user)
            else:
                if user.id not in data:
                    balance = collector.get_latest_user_balance(user.id)
                else:
                    balance = data[user.id]
                if balance is None:
                    users_missing.append(user)
                elif balance.amount > 0:
                    user_scores.append((user, balance.amount))
                else:
                    users_rekt.append(user)

        date = date.replace(microsecond=0)
        footer += f'Data used from: {date}'
        unit = '$'
    elif mode == 'gain':
        try:
            delta = calc_timedelta_from_time_args(time)
        except ValueError as e:
            logging.error(e.args[0])
            await message.edit(e.args[0])
            return

        time = datetime.now()
        search = time - delta

        user_gains = calc_gains(USERS, search)

        for user, user_gain in user_gains:
            if user_gain is not None:
                user_gain_rel, user_gain_abs = user_gain
                user_scores.append((user, user_gain_rel))
                custom_user_strings[user] = f'{round(user_gain_rel, ndigits=3)}% ({round(user_gain_abs, ndigits=3)}$)'
            else:
                users_missing.append(user)

        footer += f'Gain since {search.replace(microsecond=0)} was calculated'

        unit = '%'
    else:
        logging.error(f'Unknown mode {mode} was passed in')
        await message.edit(f'Unknown mode {mode}')
        return

    user_scores.sort(key=lambda x: x[1], reverse=True)
    rank = 1

    if len(user_scores) > 0:
        prev_score = user_scores[0][1]
        for user, score in user_scores:
            if score < prev_score:
                rank += 1
            member = guild.get_member(user.id)
            if member:
                if user in custom_user_strings:
                    value = custom_user_strings[user]
                else:
                    value = f'{round(score, ndigits=3)}{unit}'
                description += f'{rank}. **{member.display_name}** {value}\n'
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
    logger.info(f"Done creating leaderboard.\nDescription:\n{description}")
    await message.edit(content='', embed=embed)


@slash.slash(
    name="leaderboard",
    description="Shows you the highest ranked users",
    options=[
        create_option(
            name="mode",
            description="Mode for sorting. Default: balance",
            required=False,
            option_type=3,
            choices=[
                create_choice(
                    name="balance",
                    value="balance"
                ),
                create_choice(
                    name="gain",
                    value="gain"
                )
            ]
        ),
        create_option(
            name="time",
            description="Only used for gain. Timefame for gain",
            required=False,
            option_type=3
        )
    ],
    guild_ids=SLASH_GUILD_IDS
)
async def leaderboard(ctx: SlashContext, mode: str = 'balance', time: str = None):
    logger.info(f'New Interaction: Creating leaderboard, requested by user {ctx.author.display_name}: {mode=} {time=}')

    if time is None:
        time = '24h'

    message = await ctx.send('...')

    asyncio.create_task(calc_leaderboard(
        message=message, guild=ctx.guild, mode=mode, time=time
    ))


@slash.slash(
    name="exchanges",
    description="Shows available exchanges"
)
async def exchanges(ctx):
    logger.info(f'New Interaction: Listing available exchanges for user {ctx.author.display_name}')
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
    # TODO: Implement decryption for user data
    try:
        with open(DATA_PATH + 'users.json', 'r') as f:
            users_json = json.load(fp=f)
            for user_json in users_json:
                try:
                    exchange_name = user_json['exchange'].lower()
                    exchange_cls = EXCHANGES[exchange_name]
                    if issubclass(exchange_cls, Client):
                        exchange: Client = exchange_cls(
                            api_key=user_json['api_key'],
                            api_secret=user_json['api_secret'],
                            subaccount=user_json['subaccount'],
                            extra_kwargs=user_json['extra']
                        )
                        rekt_on = user_json.get('rekt_on', None)
                        if rekt_on:
                            rekt_on = datetime.fromtimestamp(rekt_on)
                        initial_balance = user_json.get('initial_balance', None)
                        if initial_balance:
                            initial_balance = (
                                datetime.fromtimestamp(initial_balance['date']),
                                Balance(amount=initial_balance['amount'], currency='$', error=None)
                            )

                        user = User(
                            id=user_json['id'],
                            api=exchange,
                            rekt_on=rekt_on,
                            initial_balance=initial_balance
                        )
                        USERS.append(user)
                        USERS_BY_ID[user.id] = user
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
                    "**USDT (TRX)**: TPf47q7143stBkWicj4SidJ1DDeYSvtWBf\n"
                    "**USDT (BSC)**: 0x694cf86962f84d281d322887569b16935b48d9dd\n\n"
                    "jacksn#9149."
    )
    await ctx.send(embed=embed)


def save_registered_users():
    # TODO: Implement encryption for user data
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
                message_replaced = message.replace("{name}", member.display_name.upper())
                embed = discord.Embed(description=message_replaced)
                await channel.send(embed=embed)
        except KeyError:
            logger.error(f'Invalid guild {guild_data}')
        except AttributeError as e:
            logger.error(f'Error while sending message to guild {e}')

    save_registered_users()


def on_rekt(user: User):
    asyncio.create_task(on_rekt_async(user))


logger = setup_logger(debug=False)

if os.path.exists(DATA_PATH):
    load_registered_users()
else:
    os.mkdir(DATA_PATH)

collector = DataCollector(USERS,
                          fetching_interval_hours=FETCHING_INTERVAL_HOURS,
                          data_path=DATA_PATH,
                          on_rekt_callback=on_rekt)

client.run(KEY)
