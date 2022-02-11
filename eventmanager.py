from typing import List, Dict, Callable
from models.event import Event
from dataclasses import dataclass
from datetime import datetime
from threading import Timer, Lock
from api.dbmodels.event import Event
from usermanager import UserManager
import logging


@dataclass
class FutureCallback:
    time: datetime
    callback: Callable


class EventManager:

    def __init__(self, discord_client):
        self._scheduled: List[FutureCallback] = []
        self._schedule_lock = Lock()
        self._cur_timer = None
        self._um = UserManager()
        self._dc_client = discord_client

    def register(self, event: Event):
        self._schedule(
            FutureCallback(
                time=event.start,
                callback=self._event_start
            )
        )
        self._schedule(
            FutureCallback(
                time=event.end,
                callback=self._event_end
            )
        )

    async def _event_start(self, event):

        try:
            guild = self._dc_client.get_guild(event.guild_id)
            channel = guild.get_channel(event.channel_id)
            embed = event.get_discord_embed()
            await channel.send(content=f'Event **{event.name}** just started!', embed=embed)
            member = guild.get_member(user.user_id)
            if member:
                message_replaced = message.replace("{name}", member.display_name)
                embed = discord.Embed(description=message_replaced)
                await channel.send(embed=embed)
        except AttributeError as e:
            logging.error(f'Error while sending message to guild {e}')


    async def _event_end(self, event):
        pass

    def _event_registration_start(self, event):
        pass

    def _event_registration_end(self, event):
        pass

    def _schedule(self, callback: FutureCallback):
        self._scheduled.append(callback)
        if len(self._scheduled) == 1:
            self._execute()
        else:
            self._scheduled.sort(key=lambda x: x.time)

    def _execute(self):
        if len(self._scheduled) > 0:
            cur_event = self._scheduled[0]
            diff_seconds = (cur_event.time - datetime.now()).total_seconds()

            def wrapper():
                self._scheduled.remove(cur_event)
                try:
                    cur_event.callback()
                except Exception as e:
                    logging.error(f'Unhandled exception during event callback {cur_event.callback}: {e}')
                self._execute()

            self._cur_timer = Timer(diff_seconds, wrapper)
            self._cur_timer.start()
