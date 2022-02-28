from functools import wraps
from typing import List, Dict, Callable
from dataclasses import dataclass
from datetime import datetime
from threading import Timer, RLock
from api.dbmodels.event import Event
from usermanager import UserManager
import utils
import logging
from api.database import db
import discord


@dataclass
class FutureCallback:
    time: datetime
    callback: Callable


class EventManager:

    def __init__(self, discord_client: discord.Client):
        self._scheduled: List[FutureCallback] = []
        self._schedule_lock = RLock()
        self._cur_timer = None
        self._um = UserManager()
        self._dc_client = discord_client

    def initialize_events(self):
        events = Event.query.all()
        for event in events:
            self.register(event)

    def _get_event_channel(self, event: Event):
        guild = self._dc_client.get_guild(event.guild_id)
        return guild.get_channel(event.channel_id)

    async def _event_start(self, event: Event):
        self._um.synch_workers()
        await self._get_event_channel(event).send(content=f'Event **{event.name}** just started!',
                                                  embed=event.get_discord_embed(registrations=True))

    async def _event_end(self, event: Event):
        await self._get_event_channel(event).send(
            content=f'Event **{event.name}** just ended! Here\'s a little summary',
            embeds=[
                utils.create_leaderboard(self._dc_client, event.guild_id),
                event.get_summary_embed()
            ]
        )

        self._um.synch_workers()
        Event.query.filter_by(id=event.id).delete()
        db.session.commit()

    async def _event_registration_start(self, event: Event):
        await self._get_event_channel(event).send(content=f'Registration period for **{event.name}** has started!')

    async def _event_registration_end(self, event: Event):
        await self._get_event_channel(event).send(content=f'Registration period for **{event.name}** has ended!')

    def register(self, event: Event):
        event_callbacks = [
            (event.start, lambda: self._event_start(event)),
            (event.end, lambda: self._event_end(event)),
            (event.registration_start, lambda: self._event_registration_start(event)),
            (event.registration_end, lambda: self._event_registration_end(event))
        ]
        now = datetime.now()
        for time, callback in event_callbacks:
            if time > now:
                self._schedule(
                    FutureCallback(
                        time=time,
                        callback=self._wrap_async(callback)
                    )
                )

    def _wrap_async(self, coro):
        @wraps(coro)
        def func():
            self._dc_client.loop.create_task(coro())
        return func

    def _schedule(self, callback: FutureCallback):
        with self._schedule_lock:
            self._scheduled.append(callback)
            if len(self._scheduled) == 1:
                self._execute()
            else:
                # Execution has to be restarted if the callback to schedule happens before the current waiting callback
                if callback.time < self._scheduled[0].time:
                    self._cur_timer.cancel()
                    self._scheduled.sort(key=lambda x: x.time)
                    self._execute()
                else:
                    self._scheduled.sort(key=lambda x: x.time)

    def _execute(self):
        with self._schedule_lock:
            if len(self._scheduled) > 0:
                cur_event = self._scheduled[0]
                diff_seconds = (cur_event.time - datetime.now()).total_seconds()

                def wrapper():
                    try:
                        cur_event.callback()
                    except Exception as e:
                        logging.error(f'Unhandled exception during event callback {cur_event.callback}: {e}')
                    with self._schedule_lock:
                        if cur_event in self._scheduled:
                            self._scheduled.remove(cur_event)
                    self._execute()

                self._cur_timer = Timer(diff_seconds, wrapper)
                self._cur_timer.daemon = True
                self._cur_timer.start()
