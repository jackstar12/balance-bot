from __future__ import annotations
import logging
import traceback

from functools import wraps

import discord

from discord_slash.utils.manage_components import create_button, create_actionrow, create_select_option
import discord_slash.utils.manage_components as discord_components
from discord_slash.model import ButtonStyle
from discord_slash import SlashCommand, ComponentContext
from typing import List, Tuple, Callable, Optional, Dict

from balancebot.common.database_async import async_session
from balancebot.common.errors import UserInputError, InternalError
from balancebot.common.models.selectionoption import SelectionOption



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
                if e.user_id:
                    if ctx.guild:
                        e.reason = e.reason.replace('{name}', ctx.guild.get_member(e.user_id).display_name)
                    else:
                        e.reason = e.reason.replace('{name}', ctx.author.display_name)
                await ctx.send(e.reason, hidden=True)
                logging.info(
                    f'{type} {coro.__name__} failed because of UserInputError: {de_emojify(e.reason)}\n{traceback.format_exc()}')
            except InternalError as e:
                if ctx.deferred:
                    await ctx.send(f'This is a bug in the test_bot. Please contact jacksn#9149. ({e.reason})', hidden=True)
                logging.error(
                    f'{type} {coro.__name__} failed because of InternalError: {e.reason}\n{traceback.format_exc()}')
            except Exception:
                if ctx.deferred:
                    await ctx.send('This is a bug in the test_bot. Please contact jacksn#9149.', hidden=True)
                logging.critical(
                    f'{type} {coro.__name__} failed because of an uncaught exception:\n{traceback.format_exc()}')
                await async_session.rollback()

        return wrapper

    return decorator


def embed_add_value_safe(embed: discord.Embed, name, value, **kwargs):
    if value:
        embed.add_field(name=name, value=value, **kwargs)



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

