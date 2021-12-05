import logging
import sys
import discord
import typing
import json

from typing import List, Dict, Type
from discord.ext import commands
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
intents = discord.Intents.default()
intents.members = True
client = commands.Bot(command_prefix=PREFIX, intents=intents)

USERS: List[User] = []
exchanges: Dict[str, Type[Client]] = {
    'binance': BinanceClient,
    'bitmex': BitmexClient,
    'ftx': FtxClient,
    'kucoin': KuCoinClient
}


@client.event
async def on_ready():
    logger.info('Bot Ready')


@client.command(
    aliases=['Balance'],
    brief="Gives Balance of specified user",
    full="Gives Balance of specified user"
)
async def balance(ctx, user: discord.Member = None):
    if user is not None:
        hasMatch = False
        for cur_user in USERS:
            if user.id == cur_user.id:
                usr_balance = cur_user.api.getBalance()
                if usr_balance.error is None:
                    await ctx.send(f'{user.display_name}\'s balance: {usr_balance.amount}$')
                else:
                    await ctx.send(f'Error while getting {user.display_name}\`s balance: {usr_balance.error}')
                hasMatch = True
                break
        if not hasMatch:
            await ctx.send('User unknown! Please register via a DM first.')
    else:
        await ctx.send('Please specify a user.')


def calc_gain(user: User, search: datetime):
    user_data = collector.get_user_data()
    prev_timestamp = search
    # Reverse data since latest data is at the top
    for cur_time, data in reversed(user_data):
        if abs(cur_time - search) < abs(prev_timestamp - cur_time):
            try:
                yesterday_balance = data[user.id].amount
                today_balance = user.api.getBalance()
                if yesterday_balance > 0:
                    return (today_balance.amount / yesterday_balance - 1) * 100
                else:
                    return 0
            except KeyError:
                # User isn't included in data
                break
        prev_timestamp = cur_time
    return None


def calc_timedelta_from_time_args(*args) -> timedelta:
    minute = 0
    hour = 0
    day = 0
    week = 0
    if len(args) > 0:
        for arg in args:
            try:
                if 'h' in arg:
                    hour = int(arg.rstrip('h'))
                elif 'm' in arg:
                    minute = int(arg.rstrip('m'))
                elif 'w' in arg:
                    week = int(arg.rstrip('w'))
                elif 'd' in arg:
                    day = int(arg.rstrip('d'))
                else:
                    raise ValueError
            except ValueError:  # Make sure both cases are treated the same
                raise ValueError(arg)

    return timedelta(hours=hour, minutes=minute, days=day, weeks=week)


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
                    await ctx.send(f'{user.display_name}\'s  gain: {round(user_gain)}%')
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
    brief="Registers user",
    description="Some exchanges might require additional args, for example:\n"
                "<prefix> register kucoin <api key> <api secret> <subaccount> passphrase=<passphrase>",
    aliases=["Register"]
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
        exchange_cls = exchanges[exchange_name]
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
    user_scores = {}

    if mode == 'balance':
        date, data = collector.fetch_data()
        user_scores = {data[user_id].amount: user_id for user_id in data}
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

        user_scores = {}
        for user in USERS:
            user_gain = calc_gain(user, search)
            if user_gain is not None:
                user_scores[user_gain] = user.id

        unit = '%'

    values = [value for value in user_scores.keys()]
    values.sort(reverse=True)

    description = ''
    rank = 1
    for value in values:
        member = ctx.guild.get_member(user_scores[value])
        description += f'{rank}. **{member.display_name}** {round(value, ndigits=3)}{unit}\n'
        rank += 1
    embed = discord.Embed(title='Leaderboard', description=description, color=0xEE8700)
    await ctx.send(embed=embed)


@client.command(
    aliases=["exchanges", "available"]
)
async def available_exchanges(ctx):
    description = ''
    for exchange in exchanges.keys():
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
                exchange_cls = exchanges[exchange_name]
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
