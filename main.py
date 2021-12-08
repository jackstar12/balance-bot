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
from config import DATA_PATH, PREFIX, FETCHING_INTERVAL_HOURS, KEY, REKT_MESSAGES, LOG_OUTPUT_DIR, REKT_GUILDS, GUILD_IDS, INITIAL_BALANCE

from Exchanges.binance import BinanceClient
from Exchanges.bitmex import BitmexClient
from Exchanges.ftx import FtxClient
from Exchanges.kucoin import KuCoinClient

intents = discord.Intents().default()
intents.members = True
intents.guilds = True

client = commands.Bot(command_prefix=PREFIX, intents=intents)
slash = SlashCommand(client, sync_commands=True, debug_guild=GUILD_IDS[0])

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
    description="Ping",
    guild_ids=GUILD_IDS
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
        )
    ],
    guild_ids=GUILD_IDS
)
async def balance(ctx, user: discord.Member = None):
    if user is None:
        user = ctx.author
    hasMatch = False
    for cur_user in USERS:
        if user.id == cur_user.id:
            usr_balance = collector.get_user_balance(cur_user)
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
    description="Draws balance history of a user",
    options=[
        create_option(
            name="user",
            description="User to draw history for",
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
        )
    ],
    guild_ids=GUILD_IDS
)
async def history(ctx, user: discord.Member = None, compare: discord.Member = None, since: str = None):
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

        compare_data = []
        if compare:
            if compare.id in USERS_BY_ID:
                compare_data = collector.get_single_user_data(compare.id)
            else:
                logger.error(f'User {compare} cant be compared with because he isn\'t registered')
                await ctx.send(f'Compare user unknown. Please register first.')
                return

        compare_xs = []
        compare_ys = []
        for time, balance in compare_data:
            compare_xs.append(time)
            compare_ys.append(balance.amount)

        name = ctx.guild.get_member(user.id).display_name
        title = f'History for {ctx.guild.get_member(user.id).display_name}'
        plt.plot(xs, ys, label=f"{name}'s Balance")
        if compare:
            compare_name = ctx.guild.get_member(compare.id).display_name
            plt.plot(compare_xs, compare_ys, label=f"{compare_name}'s Balance")
            title += f' vs. {compare_name}'
        plt.gcf().autofmt_xdate()
        plt.title(title)
        plt.ylabel('$')
        plt.xlabel('Time')
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


def calc_gains(users: List[User], search: datetime) -> List[Tuple[User, float]]:
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
                        balance_then = data[user.id].amount
                        balance_now = collector.get_latest_user_balance(user.id).amount
                        users_done.append(user.id)
                        if balance_then > 0:
                            results.append((user, (balance_now / balance_then - 1) * 100))
                        else:
                            results.append((user, 0.0))
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
        )
    ],
    guild_ids=GUILD_IDS
)
async def gain(ctx, user: discord.Member = None, time: str = '24h'):

    if user is None:
        user = ctx.author

    time_str = time

    logger.info(f'New Interaction with {ctx.author}: Calculate gain for {user.display_name} {time=}')

    if user is not None:
        hasMatch = False
        for cur_user in USERS:
            if user.id == cur_user.id:
                hasMatch = True
                try:
                    if time_str:
                        time_args = time_str.split()
                        delta = calc_timedelta_from_time_args(*time_args)
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

                user_gain = calc_gains([cur_user], search)[0][1]
                if user_gain is None:
                    logger.info(f'Not enough data for calculating {user.display_name}\'s {time_str} gain')
                    await ctx.send(f'Not enough data for calculating {user.display_name}\'s {time_str}  gain')
                else:
                    await ctx.send(f'{user.display_name}\'s {time_str} gain: {round(user_gain, ndigits=3)}%')
                break
        if not hasMatch:
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
                    ctx.send(f'Invalid keyword argument: {arg} syntax for keyword arguments: key1=value1 key2=value2 ...')
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


async def calc_leaderboard(message, guild: discord.Guild, mode: str, time: str):
    user_scores: List[Tuple[User, float]] = []
    users_rekt: List[User] = []
    users_missing: List[User] = []
    footer = ''
    date, data = collector.fetch_data()
    if mode == 'balance':
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
            if time:
                args = time.split(' ')
                if len(args) > 0:
                    delta = calc_timedelta_from_time_args(*args)
                else:
                    delta = timedelta(hours=24)
            else:
                delta = timedelta(hours=24)
        except ValueError as e:
            logging.error(f'Invalid argument {e.args[0]} was passed in')
            await message.edit(f'Invalid argument {e.args[0]}')
            return

        if delta.total_seconds() <= 0:
            logging.error(f'Time was negative or zero.')
            await message.edit(f'Time can not be negative or zero. For more information type {PREFIX}help gain')
            return

        time = datetime.now()
        search = time - delta

        user_gains = calc_gains(USERS, search)

        for user, user_gain in user_gains:
            if user_gain is not None:
                user_scores.append((user, user_gain))
            else:
                users_missing.append(user)

        footer += f'Gain since {search.replace(microsecond=0)} was calculated'

        unit = '%'
    else:
        logging.error(f'Unknown mode {mode} was passed in')
        await message.edit(f'Unknown mode {mode}')
        return

    user_scores.sort(key=lambda x: x[1], reverse=True)
    description = ''
    rank = 1

    if len(user_scores) > 0:
        prev_score = user_scores[0][1]
        for user, score in user_scores:
            if score < prev_score:
                rank += 1
            member = guild.get_member(user.id)
            description += f'{rank}. **{member.display_name}** {round(score, ndigits=3)}{unit}\n'
            prev_score = score

    if len(users_rekt) > 0:
        description += f'\n**Rekt**\n'
        for user_rekt in users_rekt:
            member = guild.get_member(user_rekt.id)
            description += f'{member.display_name}'
            if user_rekt.rekt_on:
                description += f' since {user_rekt.rekt_on.replace(microsecond=0)}'
            description += '\n'

    if len(users_missing) > 0:
        description += f'\n**Missing**\n'
        for user_missing in users_missing:
            member = guild.get_member(user_missing.id)
            description += f'{member.display_name}\n'

    description += f'\n{footer}'

    embed = discord.Embed(
        title='Leaderboard :medal:',
        description=description
    )
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
    guild_ids=GUILD_IDS
)
async def leaderboard(ctx: SlashContext, mode: str = 'balance', time: str = None):
    logger.info(f'New Interaction: Creating leaderboard, requested by user {ctx.author.display_name}: {mode=} {time=}')

    message = await ctx.send('...')

    asyncio.create_task(calc_leaderboard(
        message=message, guild=ctx.guild, mode=mode, time=time
    ))


@slash.slash(
    name="exchanges",
    description="Shows available exchanges",
    guild_ids=GUILD_IDS
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
    save_registered_users()
else:
    os.mkdir(DATA_PATH)

collector = DataCollector(USERS,
                          fetching_interval_hours=FETCHING_INTERVAL_HOURS,
                          data_path=DATA_PATH,
                          on_rekt_callback=on_rekt)

client.run(KEY)
