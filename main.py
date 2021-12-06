import logging
import sys
import discord
import json
import typing

from discord_slash import SlashCommand, SlashContext
from discord.ext import commands
from typing import List, Dict, Type, Tuple
from datetime import datetime, timedelta

from user import User
from client import Client
from key import key
from datacollector import DataCollector

from Exchanges.binance import BinanceClient
from Exchanges.bitmex import BitmexClient
from Exchanges.ftx import FtxClient
from Exchanges.kucoin import KuCoinClient

PREFIX = 'c '
intents = discord.Intents().default()
intents.members = True
client = commands.Bot(command_prefix=PREFIX, intents=intents)

slash = SlashCommand(client, sync_commands=False)

USERS: List[User] = []
EXCHANGES: Dict[str, Type[Client]] = {
    'binance': BinanceClient,
    'bitmex': BitmexClient,
    'ftx': FtxClient,
    'kucoin': KuCoinClient
}


@client.event
async def on_ready():
    logger.info('Bot Ready')


@slash.slash(
    name="ping",
    description="Ping"
)
async def ping(ctx):
    await ctx.reply(f'Ping beträgt {round(client.latency * 1000)} ms')


@client.command()
async def balance(ctx, user: discord.Member = None):
    if user is None:
        user = ctx.author
    hasMatch = False
    for cur_user in USERS:
        if user.id == cur_user.id:
            usr_balance = cur_user.api.getBalance()
            if usr_balance.error is None:
                await ctx.send(f'{user.display_name}\'s balance: {usr_balance.amount}$')
            else:
                await ctx.send(f'Error while getting {user.display_name}\'s balance: {usr_balance.error}')
            hasMatch = True
            break
    if not hasMatch:
        await ctx.send('User unknown. Please register via a DM first.')


def calc_timedelta_from_time_args(*args) -> timedelta:
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
    minute = 0
    hour = 0
    day = 0
    week = 0
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
                    raise ValueError(arg)
            except ValueError:  # Make sure both cases are treated the same
                raise ValueError(arg)

    return timedelta(hours=hour, minutes=minute, days=day, weeks=week)


def calc_gain(user: User, search: datetime):
    user_data = collector.get_user_data()
    prev_timestamp = search
    prev_data = {}
    # Reverse data since latest data is at the top
    for cur_time, data in reversed(user_data):
        cur_diff = cur_time - search
        if cur_diff.total_seconds() <= 0:
            if abs(cur_diff.total_seconds()) < abs((prev_timestamp - search).total_seconds()):
                data = prev_data
            try:
                balance_then = data[user.id].amount
                balance_now = user.api.getBalance().amount
                if balance_then > 0:
                    return (balance_now / balance_then - 1) * 100
                else:
                    return 0.0
            except KeyError:
                # User isn't included in data set
                continue
        prev_timestamp = cur_time
        prev_data = data
    return None


@client.command()
async def gain(ctx, user: discord.Member = None, *args):
    if user is not None:
        hasMatch = False
        for cur_user in USERS:
            if user.id == cur_user.id:
                hasMatch = True

                try:
                    if len(args) > 0:
                        delta = calc_timedelta_from_time_args(*args)
                    else:
                        delta = timedelta(hours=24)
                except ValueError as e:
                    await ctx.send(f'Invalid argument {e.args[0]}')
                    return

                if delta.total_seconds() <= 0:
                    await ctx.send(f'Time can not be negative or zero. For more information type {PREFIX}help gain')
                    return

                time = datetime.now()
                search = time - delta

                user_gain = calc_gain(cur_user, search)
                if user_gain is None:
                    await ctx.send(f'Not enough data for calculating {user.display_name}\'s gain')
                else:
                    await ctx.send(f'{user.display_name}\'s  gain: {round(user_gain, ndigits=3)}%')
                break
        if not hasMatch:
            await ctx.send('User unknown! Please register via a DM first.')
    else:
        await ctx.send('Please specify a user.')


async def check_arg(ctx, value, default, name: str) -> int:
    if value == default:
        await ctx.send(f'Argument {name} is required.')
        return 1
    return 0


@client.command(
    name="register",
    description="Register you for tracking"
)
async def register(ctx: commands.Context,
                   exchange_name: str = None,
                   api_key: str = None,
                   api_secret: str = None,
                   subaccount: typing.Optional[str] = None,
                   *args):
    if ctx.guild is not None:
        await ctx.send('This command can only be used via a DM.')
        await ctx.author.send(f'Type {PREFIX}help register.')
        return

    valid = 0
    valid += await check_arg(ctx, exchange_name, None, 'Exchange Name')
    valid += await check_arg(ctx, api_key, None, 'API Key')
    valid += await check_arg(ctx, api_secret, None, 'API Secret')

    # Some arg wasn't given
    if valid > 0:
        return

    kwargs = {}
    if len(args) > 0:
        for arg in args:
            try:
                name, value = arg.split('=')
                kwargs[name] = value
            except ValueError:
                logging.error(f'Invalid Keyword Arg {arg} passed in')

    try:
        exchange_name = exchange_name.lower()
        exchange_cls = EXCHANGES[exchange_name]
        if issubclass(exchange_cls, Client):
            exchange: Client = exchange_cls(
                api_key=api_key,
                api_secret=api_secret,
                subaccount=subaccount,
                extra_kwargs=kwargs
            )
            existing = False
            for user in USERS:
                if ctx.author.id == user.id:
                    user.api = exchange
                    await ctx.send(embed=user.get_discord_embed())
                    existing = True
                    break
            if not existing:
                new_user = User(ctx.author.id, exchange)
                await ctx.send(embed=new_user.get_discord_embed())
                USERS.append(new_user)
                collector.add_user(new_user)
            save_registered_users()
        else:
            logger.error(f'Class {exchange_cls} is no subclass of Client!')
    except KeyError:
        await ctx.send(f'Exchange {exchange_name} unknown')


@client.command()
async def unregister(ctx):
    if ctx.guild is not None:
        await ctx.send(f'This command can only be used via a DM.')
        return

    for user in USERS:
        if ctx.author.id == user.id:
            USERS.remove(user)
            collector.remove_user(user)
            save_registered_users()
            await ctx.send(f'You were successfully unregistered!')
            return
    await ctx.send(f'You are not registered.')


@client.command(
    aliases=['information']
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


@client.command()
async def leaderboard(ctx: commands.Context, mode: str = 'balance', *args):
    user_scores: List[Tuple[int, float]] = []
    users_rekt: List[int] = []

    footer = ''

    if mode == 'balance':
        date, data = collector.fetch_data()
        for user_id in data:
            amount = data[user_id].amount
            if amount > 0:
                user_scores.append((user_id, amount))
            else:
                users_rekt.append(user_id)

        date = date.replace(microsecond=0)
        footer += f'Data used from: {date}'
        unit = '$'
    elif mode == 'gain':
        try:
            if len(args) > 0:
                delta = calc_timedelta_from_time_args(*args)
            else:
                delta = timedelta(hours=24)
        except ValueError as e:
            await ctx.send(f'Invalid argument {e.args[0]}')
            return

        if delta.total_seconds() <= 0:
            await ctx.send(f'Time can not be negative or zero. For more information type {PREFIX}help gain')
            return

        time = datetime.now()
        search = time - delta

        for user in USERS:
            user_gain = calc_gain(user, search)
            if user_gain is not None:
                user_scores.append((user.id, user_gain))

        unit = '%'
    else:
        await ctx.send(f'Unknown mode {mode}')
        return

    user_scores.sort(key=lambda x: x[1], reverse=True)
    description = ''
    rank = 1
    prev_score = user_scores[0][1]
    for user_id, score in user_scores:
        if score < prev_score:
            rank += 1
        member = ctx.guild.get_member(user_id)
        description += f'{rank}. **{member.display_name}** {round(score, ndigits=3)}{unit}\n'
        prev_score = score

    if len(users_rekt) > 0:
        description += f'\n\u200B**Rekt**\u200B\n'
        for user_id_rekt in users_rekt:
            member = ctx.guild.get_member(user_id_rekt)
            description += f'{member.display_name}\n'

    description += f'\n{footer}'

    embed = discord.Embed(
        title='Leaderboard :medal:',
        description=description
    )
    await ctx.send(embed=embed)


@client.command(
    aliases=["available"]
)
async def exchanges(ctx):
    description = ''
    for exchange in EXCHANGES.keys():
        description += f'{exchange}\n'

    embed = discord.Embed(title="Available Exchanges", description=description)
    await ctx.send(embed=embed)


def setup_logger(debug: bool = False):
    logger = logging.getLogger()
    logger.setLevel(logging.DEBUG if debug else logging.INFO)  # Change this to DEBUG if you want a lot more info
    formatter = logging.Formatter("%(asctime)s - %(name)s - %(levelname)s - %(message)s")
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(formatter)

    logger.addHandler(handler)
    return logger


def load_registered_users():
    # TODO: Implement decryption for user data
    with open('users.json', 'r') as f:
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
                    USERS.append(
                        User(user_json['id'], exchange)
                    )
            except KeyError as e:
                logger.error(f'{e} occurred while parsing user data {user_json} from users.json')


def save_registered_users():
    # TODO: Implement encryption for user data
    with open('users.json', 'w') as f:
        users_json = [user.to_json() for user in USERS]
        json.dump(obj=users_json, fp=f, indent=3)


logger = setup_logger(debug=False)

load_registered_users()

collector = DataCollector(USERS, fetching_interval_hours=1)
collector.start_fetching()

client.run(key)
