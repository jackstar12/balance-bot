import asyncio
import logging
import os
import random
import sys
import discord
import json
import typing


from discord_slash import SlashCommand, SlashContext
from discord.ext import commands
from typing import List, Dict, Type, Tuple
from datetime import datetime, timedelta
from random import Random

import matplotlib.pyplot as plt
import matplotlib.image as mpimg

from user import User
from client import Client
from datacollector import DataCollector
from config import DATA_PATH, PREFIX, FETCHING_INTERVAL_HOURS, KEY, REKT_MESSAGES, LOG_OUTPUT, REKT_GUILDS

from Exchanges.binance import BinanceClient
from Exchanges.bitmex import BitmexClient
from Exchanges.ftx import FtxClient
from Exchanges.kucoin import KuCoinClient


intents = discord.Intents().all()
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
    'kucoin': KuCoinClient
}


@client.event
async def on_ready():
    logger.info('Bot Ready')
    collector.start_fetching()


@slash.slash(
    name="ping",
    description="Ping"
)
async def ping(ctx):
    await ctx.reply(f'Ping beträgt {round(client.latency * 1000)} ms')


@slash.slash(
    name="balance",
    description="Gets Balance of user"
)
#@client.command()
async def balance(ctx, user: discord.Member = None):
    if user is None:
        user = ctx.author
    hasMatch = False
    for cur_user in USERS:
        if user.id == cur_user.id:
            usr_balance = cur_user.api.getBalance()
            if usr_balance.error is None:
                await ctx.send(f'{user.display_name}\'s balance: {round(usr_balance.amount, ndigits=3)}$')
            else:
                await ctx.send(f'Error while getting {user.display_name}\'s balance: {usr_balance.error}')
            hasMatch = True
            break
    if not hasMatch:
        await ctx.send('User unknown. Please register via a DM first.')


@slash.slash(
    name="history",
    description="Graphs user data"
)
#@client.command(
#    name="history",
#    brief="Draws balance history of a user"
#)
async def history(ctx, user: discord.Member = None, *args):
    if user is None:
        user = ctx.author

    logger.info(f'New interaction with {user.display_name}: Show history')

    if user.id in USERS_BY_ID:
        user_data = collector.get_single_user_data(user.id)

        xs = []
        ys = []
        for time, balance in user_data:
            xs.append(time)
            ys.append(balance.amount)

        plt.plot(xs, ys, scalex=True)
        plt.gcf().autofmt_xdate()
        plt.title(f'History for {ctx.guild.get_member(user.id).display_name}')
        plt.ylabel('$')
        plt.xlabel('Time')
        plt.savefig(DATA_PATH + "tmp.png")
        plt.close()

        file = discord.File(DATA_PATH + "tmp.png", "history.png")
        embed = discord.Embed()
        embed.set_image(url="attachment://history.png")

        await ctx.send(file=file, embed=embed)
    else:
        logger.error(f'User unknown.')
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
            diff_seconds = cur_diff.total_seconds()
            prev_diff_seconds = (prev_timestamp - search).total_seconds()
            #if abs(prev_diff_seconds) < abs(diff_seconds):
            #    data = prev_data
            #    cur_time = prev_timestamp
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

    logger.info(f'New Interaction with {ctx.author.display_name}: Calculate gain for {user.display_name} {args=}')

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
                    logger.error(f'Invalid argument {e.args[0]} was passed in')
                    await ctx.send(f'Invalid argument {e.args[0]}')
                    return

                if delta.total_seconds() <= 0:
                    await ctx.send(f'Time can not be negative or zero. For more information type {PREFIX}help gain')
                    return

                time = datetime.now()
                search = time - delta

                user_gain = calc_gain(cur_user, search)
                if user_gain is None:
                    logger.info(f'Not enough data for calculating {user.display_name}\'s gain')
                    await ctx.send(f'Not enough data for calculating {user.display_name}\'s gain')
                else:
                    await ctx.send(f'{user.display_name}\'s  gain: {round(user_gain, ndigits=3)}%')
                break
        if not hasMatch:
            logger.error(f'User unknown!')
            await ctx.send('User unknown! Please register via a DM first.')
    else:
        await ctx.send('Please specify a user.')


async def check_arg(ctx, value, default, name: str) -> int:
    if value == default:
        logger.error(f'Argument {name} was not given')
        await ctx.send(f'Argument {name} is required.')
        return 1
    return 0


def get_available_exchanges() -> str:
    exchange_list = ''
    for exchange in EXCHANGES.keys():
        exchange_list += f'{exchange}\n'
    return exchange_list


@client.command(
    name="register",
    description=f"Register you for tracking. \nAvailable exchanges:\n{get_available_exchanges()}"
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

    logger.info(f'New Interaction with {ctx.author.display_name}: Trying to register user')

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
                    logger.info(f'Updated user')
                    break
            if not existing:
                new_user = User(ctx.author.id, exchange)
                await ctx.send(embed=new_user.get_discord_embed())
                USERS.append(new_user)
                USERS_BY_ID[new_user.id] = new_user
                collector.add_user(new_user)
                logger.info(f'Registered new user')
            save_registered_users()
        else:
            logger.error(f'Class {exchange_cls} is no subclass of Client!')
    except KeyError:
        logger.error(f'Exchange {exchange_name} unknown')
        await ctx.send(f'Exchange {exchange_name} unknown')


@client.command()
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
    user_scores: List[Tuple[User, float]] = []
    users_rekt: List[User] = []
    users_missing: List[User] = []

    footer = ''

    emoji = '✅'
    await ctx.message.add_reaction(emoji)

    logger.info(f'New Interaction: Creating leaderboard, requested by user {ctx.author.display_name}: {mode=} {args=}')

    if mode == 'balance':
        date, data = collector.fetch_data()
        for user in USERS:
            if user.rekt_on:
                users_rekt.append(user)
            else:
                if user.id not in data:
                    amount = collector.get_latest_user_balance(user.id).amount
                else:
                    amount = data[user.id].amount
                if amount is None:
                    users_missing.append(user)
                elif amount > 0:
                    user_scores.append((user, amount))
                else:
                    users_rekt.append(user)

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
            logging.error(f'Invalid argument {e.args[0]} was passed in')
            await ctx.send(f'Invalid argument {e.args[0]}')
            return

        if delta.total_seconds() <= 0:
            logging.error(f'Time was negative or zero.')
            await ctx.send(f'Time can not be negative or zero. For more information type {PREFIX}help gain')
            return

        time = datetime.now()
        search = time - delta

        for user in USERS:
            user_gain = calc_gain(user, search)
            if user_gain is not None:
                user_scores.append((user, user_gain))
            else:
                users_missing.append(user)

        footer += f'Gain since {search.replace(microsecond=0)} was calculated'

        unit = '%'
    else:
        logging.error(f'Unknown mode {mode} was passed in')
        await ctx.send(f'Unknown mode {mode}')
        return

    user_scores.sort(key=lambda x: x[1], reverse=True)
    description = ''
    rank = 1

    if len(user_scores) > 0:
        prev_score = user_scores[0][1]
        for user, score in user_scores:
            if score < prev_score:
                rank += 1
            member = ctx.guild.get_member(user.id)
            description += f'{rank}. **{member.display_name}** {round(score, ndigits=3)}{unit}\n'
            prev_score = score

    if len(users_rekt) > 0:
        description += f'\n**Rekt**\n'
        for user_rekt in users_rekt:
            member = ctx.guild.get_member(user_rekt.id)
            description += f'{member.display_name} since {user_rekt.rekt_on.replace(microsecond=0)}\n'

    if len(users_missing) > 0:
        description += f'\n**Missing**\n'
        for user_missing in users_missing:
            member = ctx.guild.get_member(user_missing.id)
            description += f'{member.display_name}\n'

    description += f'\n{footer}'

    embed = discord.Embed(
        title='Leaderboard :medal:',
        description=description
    )
    await ctx.send(embed=embed)
    await ctx.message.remove_reaction(member=client.user, emoji=emoji)


@client.command(
    aliases=["available"]
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
    log_stream = open(LOG_OUTPUT, "w")
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
                        user = User(
                            id=user_json['id'],
                            api=exchange,
                            rekt_on=rekt_on
                        )
                        USERS.append(user)
                        USERS_BY_ID[user.id] = user
                except KeyError as e:
                    logger.error(f'{e} occurred while parsing user data {user_json} from users.json')
    except FileNotFoundError:
        logger.info(f'No user information found')


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
                embed = discord.Embed(description=message)
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
