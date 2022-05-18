from __future__ import annotations

import asyncio
import re
import logging
import traceback
from asyncio import Future
from decimal import Decimal
from functools import wraps

import discord
import inspect
import matplotlib.pyplot as plt
import pytz

from prettytable import PrettyTable

from discord_slash.utils.manage_components import create_button, create_actionrow, create_select_option
import discord_slash.utils.manage_components as discord_components
from discord_slash.model import ButtonStyle
from discord_slash import SlashCommand, ComponentContext, SlashContext
from datetime import datetime, timedelta
from typing import List, Tuple, Callable, Optional, Union, Dict, Any

from sqlalchemy import asc, select

import balancebot.common.dbmodels.event as db_event
import balancebot.common.dbmodels.client as db_client
from balancebot.common.database_async import async_session, db_all
from balancebot.common.dbmodels.guildassociation import GuildAssociation
from balancebot.common.errors import UserInputError, InternalError
from balancebot.common.models.daily import Daily
from balancebot.common.models.gain import Gain
from balancebot.common import dbutils
from balancebot.common.dbmodels.discorduser import DiscordUser
from balancebot.common.dbmodels.balance import Balance
from balancebot.bot.config import CURRENCY_PRECISION, REKT_THRESHOLD
from balancebot.common.models.selectionoption import SelectionOption
import balancebot.common.config as config
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from balancebot.common.dbmodels.client import Client


def validate_kwargs(kwargs: Dict, required: List[str]):
    return len(kwargs.keys()) >= len(required) and all(required_kwarg in kwargs for required_kwarg in required)



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
            return
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


def time_args(names: List[Tuple[str, Optional[str]]], allow_future=False):
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
                ctx = e.ctx or ctx
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
                ctx = e.ctx or ctx
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


async def create_history(to_graph: List[Tuple[Client, str]],
                         event: db_event.Event,
                         start: datetime,
                         end: datetime,
                         currency_display: str,
                         currency: str,
                         percentage: bool,
                         path: str,
                         custom_title: str = None,
                         throw_exceptions=True):
    """
    Creates a history image for a given list of clients and stores it in the given path.

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

    #um = UserManager()
    #await um.fetch_data([graph[0] for graph in to_graph])
    for registered_client, name in to_graph:

        history = await dbutils.get_client_history(registered_client,
                                                   event=event,
                                                   since=start,
                                                   to=end,
                                                   currency=currency)

        if len(history.data) == 0:
            if throw_exceptions:
                raise UserInputError(f'Got no data for {name}!')
            else:
                continue

        xs, ys = calc_xs_ys(history.data, percentage, relative_to=history.initial)

        total_gain = calc_percentage(history.initial.unrealized, ys[len(ys) - 1])

        if first:
            title = f'History for {name} (Total: {ys[len(ys) - 1] if percentage else total_gain}%)'
            first = False
        else:
            title += f' vs. {name} (Total: {ys[len(ys) - 1] if percentage else total_gain}%)'

        plt.plot(xs, ys, label=f"{name}'s {currency_display} Balance")

    plt.gcf().autofmt_xdate()
    plt.gcf().set_dpi(100)
    plt.gcf().set_size_inches(8 + len(to_graph), 5.5 + len(to_graph) * (5.5 / 8))
    plt.title(custom_title or title)
    plt.ylabel(currency_display)
    plt.xlabel('Time')
    plt.grid()
    plt.legend(loc="best")

    plt.savefig(path)
    plt.close()


def get_best_time_fit(search: datetime, prev: Balance, after: Balance):
    if abs((prev.tz_time - search).total_seconds()) < abs((after.tz_time - search).total_seconds()):
        return prev
    else:
        return after


async def calc_daily(client: Client,
                     amount: int = None,
                     guild_id: int = None,
                     currency: str = None,
                     string=False,
                     forEach: Callable[[Balance], Any] = None,
                     throw_exceptions=True,
                     since: datetime = None,
                     to: datetime = None,
                     now: datetime = None) -> Union[List[Daily], str]:
    """
    Calculates daily balance changes for a given client.
    :param since:
    :param to:
    :param throw_exceptions:
    :param forEach: function to be performed for each balance
    :param client: Client to calculate changes
    :param amount: Amount of days to calculate
    :param guild_id:
    :param currency: Currency that will be used
    :param string: Whether the created table should be stored as a string using prettytable or as a list of
    :return:
    """

    if currency is None:
        currency = '$'

    if now is None:
        now = datetime.now(tz=pytz.UTC)

    if since is None:
        since = datetime.fromtimestamp(0)

    if to is None:
        to = now

    since = since.replace(tzinfo=pytz.UTC).replace(hour=0, minute=0, second=0)
    to = to.replace(tzinfo=pytz.UTC)

    daily_end = min(now, to)

    history = client.history.filter(
        Balance.time > since, Balance.time < now
    ).order_by(
        asc(Balance.time)
    ).all()

    if len(history) == 0:
        if throw_exceptions:
            raise UserInputError(reason='Got no data for this user')
        else:
            return "" if string else []

    if amount:
        try:
            daily_start = daily_end - timedelta(days=amount - 1)
        except OverflowError:
            raise UserInputError('Invalid daily amount given')
    else:
        daily_start = history[0].time

    daily_start = daily_start.replace(tzinfo=pytz.UTC)
    daily_start = max(since, daily_start).replace(hour=0, minute=0, second=0)

    if guild_id:
        event = await dbutils.get_event(guild_id)
        if event and event.start > daily_start:
            daily_start = event.start

    current_day = daily_start
    current_search = daily_start + timedelta(days=1)
    prev_balance = db_match_balance_currency(history[0], currency)
    prev_daily = history[0]
    prev_daily.time = prev_daily.time.replace(hour=0, minute=0, second=0)

    if string:
        results = PrettyTable(
            field_names=["Date", "Amount", "Diff", "Diff %"]
        )
    else:
        results = []
    for balance in history:
        if since <= balance.time <= to:
            if balance.time >= current_search:

                daily = db_match_balance_currency(get_best_time_fit(current_search, prev_balance, balance), currency)
                daily.time = daily.time.replace(minute=0, second=0)
                prev_daily = prev_daily or daily
                values = Daily(
                    current_day.strftime('%Y-%m-%d') if string else current_day.timestamp(),
                    daily.unrealized,
                    round(daily.unrealized - prev_daily.unrealized, ndigits=CURRENCY_PRECISION.get(currency, 2)),
                    calc_percentage(prev_daily.unrealized, daily.unrealized, string=False)
                )
                if string:
                    results.add_row([*values])
                else:
                    results.append(values)
                prev_daily = daily
                current_day = current_search
                current_search = current_search + timedelta(days=1)
            prev_balance = balance
        await call_unknown_function(forEach, balance)

    if prev_balance.time < current_search:
        values = Daily(
            current_day.strftime('%Y-%m-%d') if string else current_day.timestamp(),
            prev_balance.unrealized,
            round(prev_balance.unrealized - prev_daily.unrealized, ndigits=CURRENCY_PRECISION.get(currency, 2)),
            calc_percentage(prev_daily.unrealized, prev_balance.unrealized, string=False)
        )
        if string:
            results.add_row([*values])
        else:
            results.append(values)

    return results


def calc_percentage(then: Union[float, Decimal], now: Union[float, Decimal], string=True) -> Union[str, float]:
    diff = now - then
    num_cls = type(then)
    if diff == 0.0:
        result = '0'
    elif then > 0:
        result = f'{round(100 * (diff / then), ndigits=3)}'
    else:
        result = 'NaN'
    return result if string else num_cls(result)


async def create_leaderboard(dc_client: discord.Client,
                             guild_id: int,
                             mode: str,
                             event: db_event.Event = None,
                             time: datetime = None,
                             archived=False) -> discord.Embed:
    client_scores: List[Tuple[Client, float]] = []
    value_strings: Dict[Client, str] = {}
    clients_rekt: List[Client] = []
    clients_missing: List[Client] = []

    footer = ''
    description = ''

    guild = dc_client.get_guild(guild_id)
    if not guild:
        raise InternalError(f'Provided guild_id is not valid!')

    if not event:
        event = await dbutils.get_event(guild_id, throw_exceptions=False, eager_loads=[db_event.Event.registrations])

    if event:
        clients = event.registrations
    else:
        # All global clients
        clients = await db_all(
            select(db_client.Client).
            filter(
                db_client.Client.id.in_(
                    select(GuildAssociation.client_id).
                    filter_by(guild_id=guild.id)
                )
            )
        )

    # if not archived:
    #     user_manager = UserManager()
    #     await user_manager.fetch_data(clients=clients)

    if mode == 'balance':
        for client in clients:
            if client.rekt_on:
                clients_rekt.append(client)
                continue
            balance = await client.latest()
            if balance and not (event and balance.time < event.start):
                if balance.unrealized > REKT_THRESHOLD:
                    client_scores.append((client, balance.unrealized))
                    value_strings[client] = balance.to_string(display_extras=False)
                else:
                    clients_rekt.append(client)
            else:
                clients_missing.append(client)

    elif mode == 'gain':

        description += f'Gain {readable_time(time)}\n\n'

        client_gains = await calc_gains(clients, event, time)

        for gain in client_gains:
            if gain.relative is not None:
                if gain.client.rekt_on:
                    clients_rekt.append(gain.client)
                else:
                    client_scores.append((gain.client, gain.relative))
                    value_strings[gain.client] = f'{gain.relative}% ({gain.absolute}$)'
            else:
                clients_missing.append(gain.client)
    else:
        raise InternalError(f'Unknown mode {mode} was passed in')

    client_scores.sort(key=lambda x: x[1], reverse=True)
    rank = 1
    rank_true = 1

    if len(client_scores) > 0:
        if mode == 'gain' and not archived:
            dc_client.loop.create_task(
                dc_client.change_presence(
                    activity=discord.Activity(
                        type=discord.ActivityType.watching,
                        name=f'Best Trader: {client_scores[0][0].discord_user.get_display_name(dc_client, guild_id)}'
                    )
                )
            )

        prev_score = None
        for client, score in client_scores:
            member = guild.get_member(client.discord_user.id)
            if member:
                if prev_score is not None and score < prev_score:
                    rank = rank_true
                if client in value_strings:
                    value = value_strings[client]
                    description += f'{rank}. **{member.display_name}** {value}\n'
                    rank_true += 1
                else:
                    logging.error(f'Missing value string for {client=} even though hes in user_scores')
                prev_score = score

    if len(clients_rekt) > 0:
        description += f'\n**Rekt**\n'
        for user_rekt in clients_rekt:
            member = guild.get_member(user_rekt.discord_user.id)
            if member:
                description += f'{member.display_name}'
                if user_rekt.rekt_on:
                    description += f' since {user_rekt.rekt_on.replace(microsecond=0)}'
                description += '\n'

    if len(clients_missing) > 0:
        description += f'\n**Missing**\n'
        for client_missing in clients_missing:
            member = guild.get_member(client_missing.discord_user.id)
            if member:
                description += f'{member.display_name}\n'

    description += f'\n{footer}'

    logging.info(f"Done creating leaderboard.\nDescription:\n{de_emojify(description)}")
    return discord.Embed(
        title='Leaderboard :medal:',
        description=description
    )


async def calc_gains(clients: List[Client],
                     event: db_event.Event,
                     search: datetime,
                     currency: str = None) -> List[Gain]:
    """
    :param event:
    :param clients: users to calculate gain for
    :param search: date since when gain should be calculated
    :param currency:
    :return:
    Gain for each user is stored in a list of tuples following this structure: (User, (user gain rel, user gain abs)) success
                                                                               (User, None) missing
    """

    if currency is None:
        currency = '$'

    results = []
    for client in clients:
        if not client:
            logging.info('calc_gains: A none client was passed in?')
            continue

        # search, _ = dbutils.get_guild_start_end_times(guild_id, search, None, archived=archived)
        #
        # balance_then = user_manager.db_match_balance_currency(
        #    Balance.query.filter(
        #        Balance.client_id == client.id,
        #        Balance.tz_time >= search
        #    ).first(),
        #    currency
        # )

        search, _ = await dbutils.get_guild_start_end_times(event.guild_id, search, None)
        balance_then = await client.get_balance_at_time(search, post=True, currency=currency)
        #balance_then = db_match_balance_currency(
        #    await db_first(
        #        client.history.statement.filter(
        #            Balance.time > search
        #        ).order_by(asc(Balance.time))
        #    ),
        #    currency
        #)

        balance_now = await client.latest()

        # history = await user_manager.get_client_history(client, event, since=search, currency=currency)
        # balance_now = db_match_balance_currency(
        #     await db_first(
        #         client.statement.filter(
        #             Balance.time < search
        #         ).order_by(None).order_by(
        #             desc(Balance.time)
        #         )
        #     ),
        #     currency
        # )

        if balance_then and balance_now:
            # balance_then = history.data[0]
            # balance_now = db_match_balance_currency(history.data[len(history.data) - 1], currency)
            diff = round(balance_now.unrealized - balance_then.unrealized,
                         ndigits=CURRENCY_PRECISION.get(currency, 3))

            if balance_then.unrealized > 0:
                results.append(
                    Gain(
                        client,
                        relative=round(100 * (diff / balance_then.unrealized), ndigits=CURRENCY_PRECISION.get('%', 2)),
                        absolute=diff
                    )
                )
            else:
                results.append(
                    Gain(client, 0.0, diff)
                )
        else:
            results.append(Gain(client, None, None))

    return results


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

    if not date:
        raise UserInputError(f'Invalid time argument: {time_str}')
    elif date > now and not allow_future:
        raise UserInputError(f'Future dates are not allowed. {time_str}')

    return date


def calc_xs_ys(data: List[Balance],
               percentage=False,
               relative_to: Balance = None) -> Tuple[List[datetime], List[float]]:
    xs = []
    ys = []

    if data:
        relative_to: Balance = relative_to or data[0]
        for balance in data:
            xs.append(balance.tz_time.replace(microsecond=0))
            if percentage:
                if relative_to.unrealized > 0:
                    amount = 100 * (balance.unrealized - relative_to.unrealized) / relative_to.unrealized
                else:
                    amount = 0.0
            else:
                amount = balance.unrealized
            ys.append(round(amount, ndigits=CURRENCY_PRECISION.get(balance.currency, 3)))
        return xs, ys


async def call_unknown_function(fn: Callable, *args, **kwargs) -> Any:
    if callable(fn):
        try:
            if inspect.iscoroutinefunction(fn):
                return await fn(*args, **kwargs)
            else:
                res = fn(*args, **kwargs)
                if inspect.isawaitable(res):
                    return await res
                return res
        except Exception:
            logging.exception(
                f'Exception occured while execution {fn} {args=} {kwargs=}'
            )


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
            await call_unknown_function(callback, ctx)
            if message:
                await ctx.send(content=message, hidden=hidden)

    wrap_callback(yes_id, yes_callback, yes_message)
    wrap_callback(no_id, no_callback, no_message)

    return create_actionrow(*buttons)


async def new_create_selection(ctx: SlashContext,
                               options: List[SelectionOption],
                               msg_content: str = None,
                               msg_embeds: List[discord.Embed] = None,
                               timeout_seconds: float = 60,
                               **kwargs) -> Future[Tuple[ComponentContext, List]]:

    future = asyncio.get_running_loop().create_future()

    component_row = create_selection(
        ctx.slash,
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
        await call_unknown_function(callback, ctx, objects)

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


def db_match_balance_currency(balance: Balance, currency: str):
    result = None

    if balance is None:
        return None

    result = None

    if balance.currency != currency:
        if balance.extra_currencies:
            result_currency = balance.extra_currencies.get(currency)
            if not result_currency:
                result_currency = balance.extra_currencies.get(config.CURRENCY_ALIASES.get(currency))
            if result_currency:
                result = Balance(
                    amount=result_currency,
                    currency=currency,
                    time=balance.time
                )
    else:
        result = balance

    return result


def join_args(*args, denominator=':'):
    return denominator.join([str(arg) for arg in args if arg])
