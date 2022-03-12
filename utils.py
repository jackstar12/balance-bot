import re
import logging
import traceback
from functools import wraps

import discord
import inspect
import api.dbutils
import matplotlib.pyplot as plt

from prettytable import PrettyTable

import api.dbmodels.client as client
from api import dbutils
from api.dbmodels.client import Client
from api.dbmodels.discorduser import DiscordUser
from errors import UserInputError, InternalError
from discord_slash.utils.manage_components import create_button, create_actionrow, create_select, create_select_option
import discord_slash.utils.manage_components as discord_components
from discord_slash.model import ButtonStyle
from discord_slash import SlashCommand, ComponentContext, SlashContext
from usermanager import UserManager
from datetime import datetime, timedelta
from discord_slash import SlashContext, SlashCommandOptionType
from typing import List, Tuple, Callable, Optional, Union, Dict, Any
from api.dbmodels.balance import Balance
from config import CURRENCY_PRECISION, REKT_THRESHOLD


def admin_only(coro):
    @wraps(coro)
    async def wrapper(ctx: SlashContext, *args, **kwargs):
        if ctx.author.guild_permissions.administrator:
            return await coro(ctx, *args, **kwargs)
        else:
            await ctx.send('This command can only be used by administrators', hidden=True)
    return wrapper


def server_only(coro):
    @wraps(coro)
    async def wrapper(ctx: SlashContext, *args, **kwargs):
        if not ctx.guild:
            await ctx.send('This command can only be used in a server.')
            return
        return await coro(ctx, *args, **kwargs)

    return wrapper


def set_author_default(name: str):
    def decorator(coro):
        @wraps(coro)
        async def wrapper(ctx: SlashContext, *args, **kwargs):
            user = kwargs.get(name)
            if user is None:
                kwargs[name] = ctx.author
            return await coro(ctx, *args, **kwargs)
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


def log_and_catch_errors(log_args=True, type: str = "command"):
    """
    Decorator which handles logging/errors for all commands.
    It takes care of:
    - UserInputErrors
    - InternalErrors
    - Any other type of exceptions

    :param log_args: whether the args passed in should be logged (e.g. disabled when sensitive data is passed).
    :return:
    """
    def decorator(coro):
        @wraps(coro)
        async def wrapper(ctx: SlashContext, *args, **kwargs):
            logging.info(f'New Interaction: '
                         f'Execute {type} {coro.__name__}, requested by {de_emojify(ctx.author.display_name)} ({ctx.author_id}) '
                         f'guild={ctx.guild}{f" {args=}, {kwargs=}" if log_args else ""}')
            try:
                await coro(ctx, *args, **kwargs)
                logging.info(f'Done executing {type} {coro.__name__}')
            except UserInputError as e:
                if e.user_id:
                    if ctx.guild:
                        e.reason = e.reason.replace('{name}', ctx.guild.get_member(e.user_id).display_name)
                    else:
                        e.reason = e.reason.replace('{name}', ctx.author.display_name)
                await ctx.send(e.reason, hidden=True)
                logging.info(f'{coro.__name__} failed because of UserInputError: {de_emojify(e.reason)}\n{traceback.format_exc()}')
            except InternalError as e:
                await ctx.send(f'This is a bug in the bot. Please contact jacksn#9149. ({e.reason})', hidden=True)
                logging.error(f'{coro.__name__} failed because of InternalError: {e.reason}\n{traceback.format_exc()}')
            except Exception:
                await ctx.send('This is a bug in the bot. Please contact jacksn#9149.', hidden=True)
                logging.critical(f'{coro.__name__} failed because of an uncaught exception:\n{traceback.format_exc()}')

        return wrapper
    return decorator


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


def create_history(to_graph: List[Tuple[client.Client, str]],
                   guild_id: int,
                   start: datetime,
                   end: datetime,
                   currency_display: str,
                   currency: str,
                   percentage: bool,
                   path: str,
                   custom_title: str = None,
                   archived=False):
    """
    Creates a history image for a given list of clients and stores it in the given path.

    :param to_graph: List of Clients to graph.
    :param guild_id: Current guild id (determines event context)
    :param start: Start time of the history
    :param end: End time of the history
    :param currency_display: Currency which will be shown to the user
    :param currency: Currency which will be used internally
    :param percentage: Whether to display the balance absolute or in % relative to the first balance of the graph (default True if multiple clients are drawn)
    :param path: Path to store image file at
    :param custom_title: Custom Title to replace default title with
    :param archived: Whether the data to search for is archived
    """

    first = True
    title = ''
    um = UserManager()
    um.fetch_data([graph[0] for graph in to_graph])
    for registered_client, name in to_graph:

        user_data = um.get_client_history(registered_client,
                                          guild_id=guild_id,
                                          start=start,
                                          end=end,
                                          currency=currency,
                                          archived=archived)

        if len(user_data) == 0:
            raise UserInputError(f'Got no data for {name}!')

        xs, ys = calc_xs_ys(user_data, percentage)

        total_gain = calc_percentage(ys[0], ys[len(ys) - 1])

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
    if abs((prev.time - search).total_seconds()) < abs((after.time - search).total_seconds()):
        return prev
    else:
        return after


def calc_daily(client: client.Client,
               amount: int = None,
               guild_id: int = None,
               currency: str = None,
               string=False,
               forEach: Callable[[Balance], Any] = None) -> Union[List[Tuple[datetime, float, float, float]], str]:
    """
    Calculates daily balance changes for a given client.
    :param forEach: function to be performed for each balance
    :param client: Client to calculate changes
    :param amount: Amount of days to calculate
    :param guild_id:
    :param currency: Currency that will be used
    :param string: Whether the created table should be stored as a string using prettytable or as an array containing each row as a Tuple of the Cols
    :return:
    """
    if len(client.history) == 0:
        raise UserInputError(reason='Got no data for this user')

    if currency is None:
        currency = '$'

    daily_end = datetime.now().replace(hour=0, minute=0, second=0)

    if amount:
        try:
            daily_start = daily_end - timedelta(days=amount - 1)
        except OverflowError:
            raise ValueError('Invalid daily amount given')
    else:
        daily_start = client.history[0].time.replace(hour=0, minute=0, second=0)

    if guild_id:
        event = dbutils.get_event(guild_id)
        if event and event.start > daily_start:
            daily_start = event.start

    um = UserManager()

    current_day = daily_start
    current_search = daily_start + timedelta(days=1)
    prev_balance = um.db_match_balance_currency(client.history[0], currency)
    prev_daily = client.history[0]
    prev_daily.time = prev_daily.time.replace(hour=0, minute=0, second=0)

    if string:
        results = PrettyTable(
            field_names=["Date", "Amount", "Diff", "Diff %"]
        )
    else:
        results = []
    for balance in client.history:
        if balance.time >= current_search:

            daily = um.db_match_balance_currency(get_best_time_fit(current_search, prev_balance, balance), currency)
            daily.time = daily.time.replace(minute=0, second=0)

            prev_daily = prev_daily or daily
            values = (
                        current_day.strftime('%Y-%m-%d'),
                        daily.amount,
                        round(daily.amount - prev_daily.amount, ndigits=CURRENCY_PRECISION.get(currency, 2)),
                        calc_percentage(prev_daily.amount, daily.amount, string=False)
                     )
            if string:
                results.add_row([*values])
            else:
                results.append(values)
            prev_daily = daily
            current_day = current_search
            current_search = current_search + timedelta(days=1)
        prev_balance = balance
        if callable(forEach):
            forEach(balance)

    if prev_balance.time < current_search:
        values = (
            current_day.strftime('%Y-%m-%d'),
            prev_balance.amount,
            round(prev_balance.amount - prev_daily.amount, ndigits=CURRENCY_PRECISION.get(currency, 2)),
            calc_percentage(prev_daily.amount, prev_balance.amount, string=False)
        )
        if string:
            results.add_row([*values])
        else:
            results.append(values)

    return results


def calc_percentage(then: float, now: float, string=True) -> Union[str, float]:
    diff = now - then
    if diff == 0.0:
        result = '0' if string else 0.0
    elif then > 0:
        result = f'{round(100 * (diff / then), ndigits=3)}' if string else round(100 * (diff / then), ndigits=3)
    else:
        result = 'nan' if string else 0.0
    return result


def create_leaderboard(dc_client: discord.Client,
                       guild_id: int,
                       mode: str,
                       time: datetime = None,
                       archived=False) -> discord.Embed:

    user_scores: List[Tuple[DiscordUser, float]] = []
    value_strings: Dict[DiscordUser, str] = {}
    users_rekt: List[DiscordUser] = []
    clients_missing: List[DiscordUser] = []

    footer = ''
    description = ''

    guild = dc_client.get_guild(guild_id)
    if not guild:
        raise InternalError(f'Provided guild_id is not valid!')
    event = dbutils.get_event(guild.id, state='archived' if archived else 'active', throw_exceptions=False)

    if event:
        clients = event.registrations
    else:
        clients = []
        # All global clients
        users = DiscordUser.query.filter(DiscordUser.global_client_id is not None).all()
        for user in users:
            member = guild.get_member(user.user_id)
            if member:
                clients.append(user.global_client)

    if not archived:
        user_manager = UserManager()
        user_manager.fetch_data(clients=clients)

    if mode == 'balance':
        for client in clients:
            if client.rekt_on:
                users_rekt.append(client)
            elif len(client.history) > 0:
                balance = client.history[len(client.history) - 1]
                if balance.amount > REKT_THRESHOLD:
                    user_scores.append((client, balance.amount))
                    value_strings[client] = balance.to_string(display_extras=False)
                else:
                    users_rekt.append(client)
            else:
                clients_missing.append(client)
    elif mode == 'gain':

        description += f'Gain {readable_time(time)}\n\n'

        client_gains = calc_gains(clients, guild.id, time, archived=archived)

        for client, client_gain in client_gains:
            if client_gain is not None:
                if client.rekt_on:
                    users_rekt.append(client)
                else:
                    user_gain_rel, user_gain_abs = client_gain
                    user_scores.append((client, user_gain_rel))
                    value_strings[client] = f'{user_gain_rel}% ({user_gain_abs}$)'
            else:
                clients_missing.append(client)
    else:
        raise UserInputError(f'Unknown mode {mode} was passed in')

    user_scores.sort(key=lambda x: x[1], reverse=True)
    rank = 1
    rank_true = 1

    if len(user_scores) > 0:
        if mode == 'gain' and not archived:
            dc_client.loop.create_task(
                dc_client.change_presence(
                    activity=discord.Activity(
                        type=discord.ActivityType.watching,
                        name=f'Best Trader: {user_scores[0][0].discorduser.get_display_name(dc_client, guild_id)}'
                    )
                )
            )
        prev_score = None
        for client, score in user_scores:
            member = guild.get_member(client.discorduser.user_id)
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

    if len(users_rekt) > 0:
        description += f'\n**Rekt**\n'
        for user_rekt in users_rekt:
            member = guild.get_member(user_rekt.discorduser.user_id)
            if member:
                description += f'{member.display_name}'
                if user_rekt.rekt_on:
                    description += f' since {user_rekt.rekt_on.replace(microsecond=0)}'
                description += '\n'

    if len(clients_missing) > 0:
        description += f'\n**Missing**\n'
        for client_missing in clients_missing:
            member = guild.get_member(client_missing.discorduser.user_id)
            if member:
                description += f'{member.display_name}\n'

    description += f'\n{footer}'

    logging.info(f"Done creating leaderboard.\nDescription:\n{de_emojify(description)}")
    return discord.Embed(
        title='Leaderboard :medal:',
        description=description
    )


def calc_gains(clients: List[Client],
               guild_id: int,
               search: datetime,
               currency: str = None,
               archived=False) -> List[Tuple[Client, Tuple[float, float]]]:
    """
    :param guild_id:
    :param clients: users to calculate gain for
    :param search: date since when gain should be calculated
    :param currency:
    :param since_start: should the gain since the start be calculated?
    :return:
    Gain for each user is stored in a list of tuples following this structure: (User, (user gain rel, user gain abs)) success
                                                                               (User, None) missing
    """

    if currency is None:
        currency = '$'

    results = []
    user_manager = UserManager()
    for client in clients:
        if not client:
            logging.info('calc_gains: A none client was passed in?')
            continue
        data = user_manager.get_client_history(client, guild_id, start=search, archived=archived)
        if len(data) > 0:
            balance_then = user_manager.db_match_balance_currency(data[0], currency)
            balance_now = user_manager.db_match_balance_currency(data[len(data) - 1], currency)
            diff = round(balance_now.amount - balance_then.amount,
                         ndigits=CURRENCY_PRECISION.get(currency, 3))
            if balance_then.amount > 0:
                results.append((client,
                                (round(100 * (diff / balance_then.amount),
                                       ndigits=CURRENCY_PRECISION.get('%', 2)), diff)))
            else:
                results.append((client, (0.0, diff)))
        else:
            results.append((client, None))

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
    now = datetime.now()
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
                        raise UserInputError(f'Invalid time argument: {arg}')
                except ValueError:  # Make sure both cases are treated the same
                    raise UserInputError(f'Invalid time argument: {arg}')
        date = now - timedelta(hours=hour, minutes=minute, days=day, weeks=week)

    if not date:
        raise UserInputError(f'Invalid time argument: {time_str}')
    elif date > now and not allow_future:
        raise UserInputError(f'Future dates are not allowed. {time_str}')

    return date


def calc_xs_ys(data: List[Balance],
               percentage=False) -> Tuple[List[datetime], List[float]]:
    xs = []
    ys = []
    for balance in data:
        xs.append(balance.time.replace(microsecond=0))
        if percentage:
            if data[0].amount > 0:
                amount = 100 * (balance.amount - data[0].amount) / data[0].amount
            else:
                amount = 0.0
        else:
            amount = balance.amount
        ys.append(round(amount, ndigits=CURRENCY_PRECISION.get(balance.currency, 3)))
    return xs, ys


async def call_unknown_function(fn: Callable, *args, **kwargs) -> Any:
    if callable(fn):
        if inspect.iscoroutinefunction(fn):
            return await fn(*args, **kwargs)
        else:
            return fn(*args, **kwargs)


def create_yes_no_button_row(slash: SlashCommand,
                             author_id: int,
                             yes_callback: Callable = None,
                             no_callback: Callable = None,
                             yes_message: str = None,
                             no_message: str = None,
                             hidden=False):
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
        @log_and_catch_errors(type="component callback")
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


def create_selection(slash: SlashCommand,
                     author_id: int,
                     options: List[Dict],
                     callback: Callable = None) -> Dict:
    """
    Utility method for creating a discord selection component.
    It provides functionality to return user-defined objects associated with the selected option on callback

    Options must be given like the following:

    ```{code-block} python
    options=[
        {
            'name': Name of the Option,
            'value': Object which will be provided on callback if the option is selected,
            'description': Optional description of the option
        },
        ...
    ]
    ```


    :param slash: SlashCommand handler to use
    :param author_id: ID of the author invoking the call (used for settings custom_id)
    :param options: List of dicts describing the options.
    :param callback: Function to call when an item is selected
    :return:
    """
    custom_id = f'selection_{author_id}'

    objects_by_label = {}

    for option in options:
        objects_by_label[option['name']] = option['value']

    selection = discord_components.create_select(
        options=[
            create_select_option(
                label=option['name'],
                value=option['name'],
                description=option['description']
            )
            for option in options
        ],
        custom_id=custom_id,
        min_values=1
    )

    if slash.get_component_callback(custom_id=custom_id) is not None:
        slash.remove_component_callback(custom_id=custom_id)

    @slash.component_callback(components=[custom_id])
    @log_and_catch_errors(type="component callback")
    async def on_select(ctx: ComponentContext):
        values = ctx.data['values']
        objects = [objects_by_label.get(value) for value in values]
        await call_unknown_function(callback, ctx, objects)

    return create_actionrow(selection)


def readable_time(time: datetime) -> str:
    """
    Utility for converting a date to a readable format, only showing the date if it's not equal to the current one.
    If None is passed in, the default value 'since start' will be returned
    :param time: Time to convert
    :return: Converted String
    """
    now = datetime.now()
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
