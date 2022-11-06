from __future__ import annotations

import asyncio
import itertools
import logging
import math
import re
import traceback
from asyncio import Future
from datetime import datetime, timedelta
from functools import wraps
from typing import List, Tuple, Callable, Optional, Union, Dict, Literal
from typing import TYPE_CHECKING

import discord
import discord_slash.utils.manage_components as discord_components
import matplotlib.colors as mcolors
import matplotlib.dates as mdates
import matplotlib.pyplot as plt
import numpy as np
import pytz
from discord_slash import SlashCommand, ComponentContext, SlashContext
from discord_slash.model import ButtonStyle
from discord_slash.utils.manage_components import create_button, create_actionrow, create_select_option
from matplotlib.collections import LineCollection
from matplotlib.patches import Polygon
from scipy import interpolate
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

import core.env as config
import database.dbmodels as dbmodels
from database import utils as dbutils
import core
from database.calc import transfer_gen
from database.dbasync import async_session, db_all, async_maker, time_range
from database.dbmodels.balance import Balance
from database.dbmodels.discord.discorduser import DiscordUser
from database.dbmodels.pnldata import PnlData
from database.dbmodels.trade import Trade
from database.dbmodels.transfer import Transfer
from database.dbmodels.user import User
from database.errors import UserInputError, InternalError
from database.models.eventinfo import EventScore, Leaderboard
from database.models.history import History
from database.models.selectionoption import SelectionOption
from core.utils import calc_percentage, return_unknown_function, groupby, utc_now

if TYPE_CHECKING:
    from database.dbmodels.client import Client

# Some consts to make TF tables prettier
MINUTE = 60
HOUR = MINUTE * 60
DAY = HOUR * 24
WEEK = DAY * 7


def with_db(coro):
    @wraps(coro)
    async def wrapper(*args, **kwargs):
        async with async_maker() as session:
            kwargs['db'] = session
            await coro(*args, **kwargs)

    return wrapper


def admin_only(coro, cog=True):
    @wraps(coro)
    async def wrapper(*args, **kwargs):
        ctx = args[1] if cog else args[0]
        if ctx.author.guild_permissions.administrator:
            return await coro(*args, **kwargs)
        else:
            await ctx.send('This command can only be used by administrators', hidden=True)

    return wrapper


def server_only(coro, cog=True):
    @wraps(coro)
    async def wrapper(*args, **kwargs):
        ctx = args[1] if cog else args[0]
        if not ctx.guild:
            await ctx.send('This command can only be used in a server.')
        else:
            return await coro(*args, **kwargs)

    return wrapper


def set_author_default(name: str, cog=True):
    def decorator(coro):
        @wraps(coro)
        async def wrapper(*args, **kwargs):
            ctx = args[1] if cog else args[0]
            user = kwargs.get(name)
            if user is None:
                kwargs[name] = ctx.author
            return await coro(*args, **kwargs)

        return wrapper

    return decorator


def time_args(*names: Tuple[str, Optional[str]], allow_future=False):
    """
    Handy decorator for using time arguments.
    After applying this decorator you also have to apply log_and_catch_user_input_errors
    :param names: Tuple for each time argument: (argument name, default value)
    :param allow_future: whether dates in the future are permitted
    :return:
    """

    def decorator(coro):
        @wraps(coro)
        async def wrapper(*args, **kwargs):
            for name, default in names:
                time_arg = kwargs.get(name)
                if not time_arg:
                    time_arg = default
                if time_arg:
                    time = calc_time_from_time_args(time_arg, allow_future)
                    kwargs[name] = time
            return await coro(*args, **kwargs)

        return wrapper

    return decorator


def log_and_catch_errors(*, log_args=True, type: str = "command", cog=True):
    """
    Decorator which handles logging/errors for all commands.
    It takes care of:
    - UserInputErrors
    - InternalErrors
    - Any other type of exceptions

    :param type:
    :param log_args: whether the args passed in should be logged (e.g. disabled when sensitive data is passed).
    :return:
    """

    def decorator(coro):
        @wraps(coro)
        async def wrapper(*args, **kwargs):
            ctx = args[1] if cog else args[0]
            logging.info(f'New Interaction: '
                         f'Execute {type} {coro.__name__}, requested by {de_emojify(ctx.author.display_name)} ({ctx.author_id}) '
                         f'guild={ctx.guild}{f" {args=}, {kwargs=}" if log_args else ""}')
            try:
                await coro(*args, **kwargs)
                logging.info(f'Done executing {type} {coro.__name__}')
            except UserInputError as e:
                # If the exception is raised after components have been used, the component ctx should be used
                # (old might be invalid)
                if e.user_id:
                    if ctx.guild:
                        e.reason = e.reason.replace('{name}', ctx.guild.get_member(e.user_id).display_name)
                    else:
                        e.reason = e.reason.replace('{name}', ctx.author.display_name)
                await ctx.send(e.reason, hidden=True)
                logging.info(
                    f'{type} {coro.__name__} failed because of UserInputError: {de_emojify(e.reason)}\n{traceback.format_exc()}')
            except TimeoutError:
                logging.info(f'{type} {coro.__name__} timed out')
            except InternalError as e:
                await ctx.send(f'This is a bug in the bot. Please contact jacksn#9149. ({e.reason})', hidden=True)
                logging.error(
                    f'{type} {coro.__name__} failed because of InternalError: {e.reason}\n{traceback.format_exc()}')
            except Exception:
                if ctx.deferred:
                    await ctx.send('This is a bug in the bot. Please contact jacksn#9149.', hidden=True)
                logging.critical(
                    f'{type} {coro.__name__} failed because of an uncaught exception:\n{traceback.format_exc()}')
                await async_session.rollback()

        return wrapper

    return decorator


def embed_add_value_safe(embed: discord.Embed, name, value, **kwargs):
    if value:
        embed.add_field(name=name, value=value, **kwargs)


_regrex_pattern = re.compile("["
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


# Thanks Stackoverflow
def de_emojify(text):
    return _regrex_pattern.sub(r'', text)


def gradient_fill(x, y, fill_color=None, ax=None, **kwargs):
    """
    Plot a line with a linear alpha gradient filled beneath it.

    Parameters
    ----------
    x, y : array-like
        The data values of the line.
    fill_color : a matplotlib color specifier (string, tuple) or None
        The color for the fill. If None, the color of the line will be used.
    ax : a matplotlib Axes instance
        The axes to plot on. If None, the current pyplot axes will be used.
    Additional arguments are passed on to matplotlib's ``plot`` function.

    Returns
    -------
    line : a Line2D instance
        The line plotted.
    im : an AxesImage instance
        The transparent gradient clipped to just the area beneath the curve.
    """

    if ax is None:
        ax = plt.gca()

    green = '#3eb86d'
    # green = 'green'
    red = '#FF6384FF'

    current_cut = 0
    lines = []
    colors = []
    for index, ((prev_x, prev_y), (now_x, now_y)) in enumerate(itertools.pairwise(zip(x, y))):
        if math.copysign(1, prev_y) != math.copysign(1, now_y):
            new_line = np.column_stack((x[current_cut:index + 1], y[current_cut:index + 1]))
            lines.append(new_line)
            colors.append(red if now_y > 0 else green)
            current_cut = index

    lines.append(np.column_stack((x[current_cut:], y[current_cut:])))
    colors.append(green if y[-1] > 0 else red)

    lines = LineCollection(segments=lines, colors=colors)

    ax.add_collection(lines)

    zorder = lines.get_zorder()
    alpha = lines.get_alpha()
    alpha = 1.0 if alpha is None else alpha

    if fill_color is None:
        fill_color = lines.get_color()

    def add_gradient(xmin, xmax, ymin, ymax, color, inverse):
        z = np.empty((100, 1, 4), dtype=float)
        rgb = mcolors.colorConverter.to_rgb(color)
        z[:, :, :3] = rgb
        z[:, :, -1] = np.linspace(alpha if inverse else 0, 0 if inverse else alpha, 100)[:, None]

        alpha_root = np.power(alpha, 1 / 1.2)
        alpha_values = np.arange(0, alpha_root, alpha_root / 100)
        z[:, :, -1] = np.array([
            np.power(x_val, 1.2) for x_val in
            (reversed(alpha_values) if inverse else alpha_values)
        ])[:, None]
        im = ax.imshow(z, aspect='auto', extent=[xmin, xmax, ymin, ymax],
                       origin='lower', zorder=zorder)

        xy = np.column_stack([x, y])
        y_border = ymax if inverse else ymin
        xy = np.vstack([[xmin, y_border], xy, [xmax, y_border], [xmin, y_border]])
        clip_path = Polygon(xy, facecolor='none', edgecolor='none', closed=True)
        ax.add_patch(clip_path)
        im.set_clip_path(clip_path)
        return im

    if max(y) > 0:
        im = add_gradient(min(x), max(x), 0, max(y), green, inverse=False)
    if min(y) < 0:
        im = add_gradient(min(x), max(x), min(y), 0, red, inverse=True)

    ax.xaxis_date()

    x_range = max(x) - min(x)
    y_range = max(y) - min(y)

    ax.set_xlim(min(x) - x_range * 0.05, max(x) + x_range * 0.05)
    ax.set_ylim(min(y) - y_range * 0.05, max(y) + y_range * 0.05)

    return lines, im


async def get_summary_embed(event: dbmodels.Event, dc_client: discord.Client):
    embed = discord.Embed(title=f'Summary')
    description = ''

    if len(event.all_clients) == 0:
        return embed

    summary = await event.get_summary()

    if summary:
        for name, user_id in [
            ('Best Trader :crown:', summary.gain.best),
            ('Worst Trader :disappointed_relieved:', summary.gain.worst),
            ('Highest Stakes :moneybag:', summary.stakes.best),
            ('Lowest Stakes :moneybag:', summary.stakes.worst),
            ('Most Degen Trader :grimacing:', summary.volatility.best),
            ('Still HODLing :sleeping:', summary.volatility.worst),
        ]:
            user: User = await async_session.get(User, user_id)
            embed.add_field(name=name, value=user.discord.get_display_name(dc_client, event.guild_id), inline=False)

        description += f'\nIn total you {"made" if summary.total >= 0.0 else "lost"} {round(summary.total, ndigits=3)}$' \
                       f'\nCumulative % performance: {round(summary.avg_percent, ndigits=3)}%'
    else:
        description += 'Pretty empty'

    description += '\n'
    embed.description = description

    return embed


async def create_complete_history(dc: discord.Client, event: dbmodels.Event):
    path = f'HISTORY_{event.guild_id}_{event.channel_id}_{int(event.start.timestamp())}.png'
    await create_history(
        custom_title=f'Complete history for {event.name}',
        to_graph=[
            (client, client.user.discord.get_display_name(dc, event.guild_id))
            for client in event.all_clients
        ],
        event=event,
        start=event.start,
        end=event.end,
        currency_display='%',
        currency='USD',
        percentage=True,
        path=config.DATA_PATH + path
    )

    file = discord.File(config.DATA_PATH + path, path)
    await async_session.commit()

    return file


async def create_history(to_graph: List[Tuple[Client, str]],
                         event: dbmodels.Event | None,
                         start: datetime,
                         end: datetime,
                         currency_display: str,
                         currency: str,
                         percentage: bool,
                         path: str,
                         custom_title: str = None,
                         throw_exceptions=True,
                         include_upnl=True,
                         mode: Literal['pnl', 'balance'] = 'balance'):
    """
    Creates a history image for a given list of clients and stores it in the given path.

    :param mode:
    :param throw_exceptions:
    :param event:
    :param to_graph: List of Clients to graph.
    :param guild_id: Current guild id (determines event context)
    :param start: Start time of the history
    :param end: End time of the history
    :param currency_display: Currency which will be shown to the user
    :param currency: Currency which will be used internally
    :param percentage: Whether to display the balance absolute or in % relative to the first balance of the graph (default True if multiple clients are drawn)
    :param path: Path to store image file at
    :param custom_title: Custom Title to replace default title with
    """

    first = True
    title = ''
    if True:
        for registered_client, name in to_graph:

            if event:
                start, end = event.validate_time_range(start, end)

            history = await dbutils.get_client_history(registered_client,
                                                       init_time=event.start if event else start,
                                                       since=start,
                                                       to=end,
                                                       currency=currency)

            pnl_data = await db_all(
                select(PnlData).where(
                    time_range(PnlData.time, start, end),
                    Trade.client_id == registered_client.id
                ).join(
                    PnlData.trade
                ).order_by(
                    PnlData.time
                ),
                PnlData.trade
            )

            transfers = await db_all(
                select(Transfer).where(
                    time_range(dbmodels.Execution.time, start, end),
                    Transfer.client_id == registered_client.id
                ).order_by(dbmodels.Execution.time)
            )

            if len(history.data) == 0:
                if throw_exceptions:
                    raise UserInputError(f'Got no data for {name}!')
                else:
                    continue

            xs, ys = calc_xs_ys(history,
                                pnl_data,
                                transfers=transfers,
                                ccy=currency,
                                percentage=percentage,
                                include_upnl=include_upnl,
                                mode=mode)

            total_gain = calc_percentage(history.initial.unrealized, ys[-1])

            if first:
                title = f'History for {name} (Total: {ys[-1] if percentage else total_gain}%)'
                first = False
            else:
                title += f' vs. {name} (Total: {ys[-1] if percentage else total_gain}%)'

            xs = np.array([mdates.date2num(d) for d in xs])

            new_x = np.linspace(min(xs), max(xs), num=500)
            ys = interpolate.pchip_interpolate(xs, ys, new_x)
            xs = new_x

            if mode == "balance" or len(to_graph) > 1:
                plt.plot(xs, ys, label=f"{name}'s {currency_display} Balance")
                plt.gca().xaxis_date()
            else:
                gradient_fill(xs, np.array([float(y) for y in ys]), fill_color='green', alpha=0.55)

        plt.gcf().autofmt_xdate()
        plt.gcf().set_dpi(100)
        plt.gcf().set_size_inches(12 + len(to_graph), 8 + len(to_graph) * (8 / 12))
        plt.title(custom_title or title)
        plt.ylabel(currency_display)
        plt.xlabel('Time')
        plt.grid(axis='y', color='#e9ebf0')
        plt.legend(loc="best")
        plt.savefig(path)
        plt.close()


async def get_leaderboard_embed(event: dbmodels.Event,
                                leaderboard: Leaderboard,
                                dc_client: discord.Client):
    footer = ''
    description = ''
    guild = dc_client.get_guild(event.guild_id)

    async def display_name(entry_id: int | str):
        entry_db = await event.async_session.get(dbmodels.EventEntry, int(entry_id))
        user = await event.async_session.get(dbmodels.User, entry_db.user_id)

        member = guild.get_member(int(user.discord.account_id))
        return member.display_name if member else None

    grouped = groupby(leaderboard.valid, key=lambda score: score.rekt_on is None)

    live = grouped.get(True, [])
    for score in live:
        name = await display_name(score.entry_id)
        if name:
            value = score.gain.to_string(event.currency)
            description += f'{score.rank}. **{name}** {value}\n'

    rekt = grouped.get(False)
    if rekt:
        description += f'\n**Rekt**\n'
        for score in rekt:
            name = await display_name(score.entry_id)
            if name:
                description += f'{name} since {score.rekt_on.replace(microsecond=0)}\n'

    if leaderboard.unknown:
        description += f'\n**Missing**\n'
        for entry_id in leaderboard.unknown:
            name = await display_name(entry_id)
            if name:
                description += f'{name}\n'

    description += f'\n{footer}'

    logging.info(f"Done creating leaderboard. Description:\n"
                 f"{de_emojify(description)}")

    return discord.Embed(
        title='Leaderboard :medal:',
        description=description
    )


async def get_leaderboard(dc_client: discord.Client,
                          guild_id: int,
                          channel_id: int,
                          since: datetime = None,
                          db: AsyncSession = None) -> discord.Embed:

    event = await dbutils.get_discord_event(guild_id, channel_id,
                                            throw_exceptions=True,
                                            eager_loads=[
                                                dbmodels.Event.clients
                                                if since else
                                                (dbmodels.Event.entries, [
                                                    dbmodels.EventEntry.init_balance,
                                                    (
                                                        dbmodels.EventEntry.client,
                                                        dbmodels.Client.user,
                                                    )
                                                ])
                                            ],
                                            db=db)

    leaderboard = await event.get_leaderboard(since)

    return await get_leaderboard_embed(event, leaderboard, dc_client)


def calc_time_from_time_args(time_str: str, allow_future=False) -> Optional[datetime]:
    """
    Calculates time from given time args.
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

    date = None
    now = datetime.now(pytz.utc)
    for includes_date, time_format in formats:
        try:
            date = datetime.strptime(time_str, time_format)
            if not includes_date:
                date = date.replace(year=now.year, month=now.month, day=now.day, microsecond=0)
            elif date.year == 1900:  # %d.%m. not setting year to 1970 but to 1900?
                date = date.replace(year=now.year)
            break
        except ValueError:
            continue

    if not date:
        minute = 0
        hour = 0
        day = 0
        week = 0
        second = 0
        args = time_str.split(' ')
        if len(args) > 0:
            for arg in args:
                try:
                    if 'h' in arg:
                        hour += int(arg.rstrip('h'))
                    elif 'm' in arg:
                        minute += int(arg.rstrip('m'))
                    elif 's' in arg:
                        second += int(arg.rstrip('s'))
                    elif 'w' in arg:
                        week += int(arg.rstrip('w'))
                    elif 'd' in arg:
                        day += int(arg.rstrip('d'))
                    else:
                        raise UserInputError(f'Invalid time argument: {arg}')
                except ValueError:  # Make sure both cases are treated the same
                    raise UserInputError(f'Invalid time argument: {arg}')
        date = now - timedelta(hours=hour, minutes=minute, days=day, weeks=week, seconds=second)

    if date:
        date = date.replace(tzinfo=pytz.utc)

    if not date:
        raise UserInputError(f'Invalid time argument: {time_str}')
    elif date > now and not allow_future:
        raise UserInputError(f'Future dates are not allowed. {time_str}')

    return date


def calc_xs_ys(history: History,
               pnl_data: List[PnlData],
               transfers: List[Transfer],
               ccy: str,
               percentage=False,
               include_upnl=False,
               mode: Literal['balance', 'pnl'] = 'balance') -> Tuple[List[datetime], List[float]]:
    xs = []
    ys = []

    if include_upnl and not pnl_data:
        def get_amount(balance: Balance):
            return balance.get_unrealized(ccy)
    else:
        def get_amount(balance: Balance):
            return balance.get_realized(ccy)

    if history.data:
        init = history.initial
        relative_to_amount = get_amount(init)

        offset_gen = transfer_gen(transfers, ccy=ccy, reset=False)
        offset_gen.send(None)

        upnl_by_trade = {}
        offset = 0
        amount = None
        for prev_item, item, next_item in core.prev_now_next(
                core.combine_time_series(history.data, pnl_data)
        ):
            if isinstance(item, PnlData):
                upnl_by_trade[item.trade_id] = item.unrealized_ccy(ccy)
            if isinstance(item, Balance):
                try:
                    offset = offset_gen.send(item.time)
                except StopIteration:
                    pass
                if mode == 'balance':
                    current = get_amount(item)
                else:
                    current = get_amount(item) - offset - relative_to_amount

                if percentage:
                    if relative_to_amount:
                        amount = calc_percentage(relative_to_amount, current, string=False)
                    else:
                        amount = 0
                else:
                    amount = current
            if amount is not None and (not next_item or next_item.time != item.time):
                xs.append(item.time)
                if include_upnl:
                    ys.append(amount + sum(upnl_by_trade.values()))
                else:
                    ys.append(amount)

        return xs, ys


async def ask_for_consent(ctx: Union[ComponentContext, SlashContext],
                          slash: SlashCommand,
                          msg_content: str = None,
                          msg_embeds: List[discord.Embed] = None,
                          yes_message: str = None,
                          no_message: str = None,
                          hidden=False,
                          timeout_seconds: float = 60) -> Future[Tuple[ComponentContext, bool]]:
    future = asyncio.get_running_loop().create_future()

    component_row = create_yes_no_button_row(
        slash,
        ctx.author_id,
        yes_message=yes_message,
        no_message=no_message,
        yes_callback=lambda component_ctx: future.set_result((component_ctx, True)),
        no_callback=lambda component_ctx: future.set_result((component_ctx, False)),
        hidden=hidden
    )

    await ctx.send(content=msg_content,
                   embeds=msg_embeds,
                   components=[component_row])

    return await asyncio.wait_for(future, timeout_seconds)


def create_yes_no_button_row(slash: SlashCommand,
                             author_id: int,
                             yes_callback: Callable = None,
                             no_callback: Callable = None,
                             yes_message: str = None,
                             no_message: str = None,
                             hidden=False) -> Dict:
    """

    Utility method for creating a yes/no interaction
    Takes in needed parameters and returns the created buttons as an ActionRow which are wired up to the callbacks.
    These must be added to the message.

    :param slash: Slash Command Handler to use
    :param author_id: Who are the buttons correspond to?
    :param yes_callback: Optional callback for yes button
    :param no_callback: Optional callback no button
    :param yes_message: Optional message to print on yes button
    :param no_message: Optional message to print on no button
    :param hidden: whether the response message should be hidden or not
    :return: ActionRow containing the buttons.
    """
    yes_id = f'yes_button_{author_id}'
    no_id = f'no_button_{author_id}'

    buttons = [
        create_button(
            style=ButtonStyle.green,
            label='Yes',
            custom_id=yes_id
        ),
        create_button(
            style=ButtonStyle.red,
            label='No',
            custom_id=no_id
        )
    ]

    def wrap_callback(custom_id: str, callback=None, message=None):

        if slash.get_component_callback(custom_id=custom_id) is not None:
            slash.remove_component_callback(custom_id=custom_id)

        @slash.component_callback(components=[custom_id])
        @log_and_catch_errors(type="Component callback", cog=False)
        @wraps(callback)
        async def yes_no_wrapper(ctx: ComponentContext):

            for button in buttons:
                slash.remove_component_callback(custom_id=button['custom_id'])

            await ctx.edit_origin(components=[])
            await return_unknown_function(callback, ctx)
            if message:
                await ctx.send(content=message, hidden=hidden)

    wrap_callback(yes_id, yes_callback, yes_message)
    wrap_callback(no_id, no_callback, no_message)

    return create_actionrow(*buttons)


async def new_create_selection(ctx: SlashContext,
                               slash: SlashCommand,
                               options: List[SelectionOption],
                               msg_content: str = None,
                               msg_embeds: List[discord.Embed] = None,
                               timeout_seconds: float = 60,
                               **kwargs) -> Tuple[ComponentContext, List]:
    future = asyncio.get_running_loop().create_future()

    component_row = create_selection(
        slash or ctx.slash,
        ctx.author_id,
        options,
        callback=lambda component_ctx, selections: future.set_result((component_ctx, selections)),
        **kwargs
    )

    await ctx.send(content=msg_content,
                   embeds=msg_embeds,
                   components=[component_row])
    return await asyncio.wait_for(future, timeout_seconds)


def create_selection(slash: SlashCommand,
                     author_id: int,
                     options: List[SelectionOption],
                     callback: Callable = None,
                     **kwargs) -> Dict:
    """
    Utility method for creating a discord selection component.
    It provides functionality to return user-defined objects associated with the selected option on callback


    :param max_values:
    :param min_values:
    :param slash: SlashCommand handler to use
    :param author_id: ID of the author invoking the call (used for settings custom_id)
    :param options: List of dicts describing the options.
    :param callback: Function to call when an item is selected
    :return:
    """
    custom_id = f'selection_{author_id}'

    objects_by_value = {}

    for option in options:
        objects_by_value[option.value] = option.object

    selection = discord_components.create_select(
        options=[
            create_select_option(
                label=option.name,
                value=option.value,
                description=option.description
            )
            for option in options
        ],
        custom_id=custom_id,
        min_values=1,
        **kwargs
    )

    if slash.get_component_callback(custom_id=custom_id) is not None:
        slash.remove_component_callback(custom_id=custom_id)

    @slash.component_callback(components=[custom_id])
    @log_and_catch_errors(type="Component callback", cog=False)
    @wraps(callback)
    async def on_select(ctx: ComponentContext):
        values = ctx.data['values']
        objects = [objects_by_value.get(value) for value in values]
        await return_unknown_function(callback, ctx, objects)

    return create_actionrow(selection)


def readable_time(time: datetime) -> str:
    """
    Utility for converting a date to a readable format, only showing the date if it's not equal to the current one.
    If None is passed in, the default value 'since start' will be returned
    :param time: Time to convert
    :return: Converted String
    """
    now = datetime.now(pytz.utc)
    if time is None:
        time_str = 'since start'
    else:
        if time.date() == now.date():
            time_str = f'since {time.strftime("%H:%M")}'
        elif time.year == now.year:
            time_str = f'since {time.strftime("%d.%m. %H:%M")}'
        else:
            time_str = f'since {time.strftime("%d.%m.%Y %H:%M")}'

    return time_str


def select_client(ctx, dc: discord.Client, slash: SlashCommand, user: DiscordUser, max_values=None):
    return new_create_selection(
        ctx,
        slash,
        options=[
            SelectionOption(
                name=client.name if client.name else client.exchange,
                value=str(client.id),
                description=f'From {user.get_events_and_guilds_string(dc, client)}',
                object=client
            )
            for client in user.clients
        ],
        msg_content="Select a client",
        max_values=max_values or len(user.clients),
    )


def join_args(*args, denominator=':'):
    return denominator.join([str(arg) for arg in args if arg])
