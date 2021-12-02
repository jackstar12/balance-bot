import logging
import sys
import discord
import typing
from typing import List

from discord.ext import commands
from user import User
from client import Client

client = commands.Bot(command_prefix='c')

users: List[User] = []
exchanges: List[Client] = []


@client.event
async def on_ready():
    logger.info('Bot Ready')


@client.event
async def on_message(message):
    # TODO: Register user through DM
    raise NotImplementedError()


@client.command(
    aliases=['Balance']
)
async def balance(ctx, user: discord.Member = None):

    if user is not None:
        hasMatch = False
        for cur_user in users:
            if user.id == cur_user.id:
                balance = cur_user.api.getBalance()
                await ctx.send(f'{user.display_name}\'s balance: {balance}$')
                hasMatch = True
                break
        if not hasMatch:
            await ctx.send(f'User unknown! Please register first.')
    else:
        await ctx.send('Please specify a user.')


@client.command()
async def register(ctx,
                   user: discord.Member = None,
                   exchange = None,
                   api_key = None,
                   subaccount: typing.Optional[str] = None):

    if user is not None:
        # TODO: Add new User to registered list
        raise NotImplementedError()
    else:
        await ctx.send('Please specify a user.')


def setup_logger(debug: bool = False):
    logger = logging.getLogger()
    logger.setLevel(logging.DEBUG if debug else logging.INFO)  # Change this to DEBUG if you want a lot more info
    formatter = logging.Formatter("%(asctime)s - %(name)s - %(levelname)s - %(message)s")
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(formatter)

    logger.addHandler(handler)
    return logger


def get_registered_users():
    # TODO: Implement saving and loading registered users from file
    raise NotImplementedError()


logger = setup_logger(debug=True)

client.run()  # TODO: Insert API Key
