import re
import logging
from functools import wraps

from errors import UserInputError
from discord_slash.utils.manage_components import create_button, create_actionrow
from discord_slash.model import ButtonStyle
from discord_slash import SlashCommand, ComponentContext, SlashContext

from datetime import datetime, timedelta
from discord_slash import SlashContext, SlashCommandOptionType
from discord_slash.model import BaseCommandObject
from discord_slash.utils.manage_commands import create_choice, create_option
from typing import List, Tuple, Callable, Optional, Union
from api.dbmodels.balance import Balance
from models.discorduser import DiscordUser
from config import CURRENCY_PRECISION


def dm_only(coro):
    @wraps(coro)
    async def wrapper(ctx, *args, **kwargs):
        if ctx.guild:
            await ctx.send('This command can only be used via a Private Message.')
            return
        return await coro(ctx, *args, **kwargs)

    return wrapper


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


def log_and_catch_user_input_errors(log_args=True):
    def decorator(coro):
        @wraps(coro)
        async def wrapper(ctx: SlashContext, *args, **kwargs):
            logging.info(f'New Interaction: '
                         f'Execute command {coro.__name__}, requested by {de_emojify(ctx.author.display_name)} '
                         f'guild={ctx.guild} {f"{args=}, {kwargs=}" if log_args else ""}')
            try:
                return await coro(ctx, *args, **kwargs)
            except UserInputError as e:
                if e.user_id:
                    e.reason = e.reason.replace('{name}', ctx.guild.get_member(e.user_id).display_name)
                await ctx.send(e.reason, hidden=True)
                logging.error(f'Failed because of UserInputError: {de_emojify(e.reason)}')
        return wrapper
    return decorator


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


def get_user_by_id(users_by_id,
                   user_id: int,
                   guild_id: int = None,
                   exact: bool = False,
                   throw_exceptions=True) -> DiscordUser:
    """
    Tries to find a matching entry for the user and guild id.
    :param exact: whether the global entry should be used if the guild isn't registered
    :return:
    The found user. It will never return None if throw_exceptions is True, since an ValueError exception will be thrown instead.
    """
    result = None

    if user_id in users_by_id:
        endpoints = users_by_id[user_id]
        if isinstance(endpoints, dict):
            result = endpoints.get(guild_id, None)
            if not result and not exact:
                result = endpoints.get(None, None)  # None entry is global
            if not result and throw_exceptions:
                raise ValueError("User {name} not registered for this guild")
        else:
            logging.error(
                f'users_by_id contains invalid entry! Associated data with {user_id=}: {result=} {endpoints=} ({guild_id=})')
            if throw_exceptions:
                raise ValueError("This is caused due to a bug in the bot. Please contact dev.")
    elif throw_exceptions:
        logging.error(f'Dont know user {user_id=}')
        raise ValueError("Unknown user {name}. Please register first.")

    return result


def add_guild_option(guilds, command: BaseCommandObject, description: str):
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
                ) for guild in guilds
            ]
        )
    )


def calc_percentage(then: float, now: float, string=True) -> Union[str, float]:
    diff = now - then
    if diff == 0.0:
        result = '0' if string else 0.0
    elif then > 0:
        result = f'{round(100 * (diff / then), ndigits=3)}' if string else round(100 * (diff / then), ndigits=3)
    else:
        result = 'nan' if string else 0.0
    return result


def calc_time_from_time_args(time_str: str, allow_future=False) -> datetime:
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
                amount = 100 * (balance.amount - data[0][1].amount) / data[0][1].amount
            else:
                amount = 0.0
        else:
            amount = balance.amount
        ys.append(round(amount, ndigits=CURRENCY_PRECISION.get(balance.currency, 3)))
    return xs, ys


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
        async def wrapper(ctx: ComponentContext):

            if callable(callback):
                callback()
            await ctx.edit_origin(components=[])
            if message:
                await ctx.send(content=message, hidden=hidden)
            for button in buttons:
                slash.remove_component_callback(custom_id=button['custom_id'])

    wrap_callback(yes_id, yes_callback, yes_message)
    wrap_callback(no_id, no_callback, no_message)

    return create_actionrow(*buttons)


def create_event_selection(custom_id: str, callback: Callable[[str], None] = None, message=None):
    pass


def readable_time(time: datetime):
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
