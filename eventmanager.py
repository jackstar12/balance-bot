from typing import List, Dict, Callable
from models.event import Event
from dataclasses import dataclass
from datetime import datetime
from threading import Timer, Lock
import logging


@dataclass
class Event:
    time: datetime
    callback: Callable


class EventManager:

    def __init__(self):
        self._events: List[Event] = []
        self._event_lock = Lock()
        self._cur_timer = None

    def schedule(self, event: Event):
        self._events.append(event)
        if len(self._events) == 1:
            self._schedule()
        else:
            self._events.sort(key=lambda x: x.time)

    def _schedule(self):
        if len(self._events) > 0:
            cur_event = self._events[0]
            diff_seconds = (cur_event.time - datetime.now()).total_seconds()

            def wrapper():
                self._events.remove(cur_event)
                try:
                    cur_event.callback()
                except Exception as e:
                    logging.error(f'Unhandled exception during event callback {cur_event.callback}: {e}')
                self._schedule()

            self._cur_timer = Timer(diff_seconds, wrapper)
            self._cur_timer.start()
