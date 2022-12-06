from dataclasses import dataclass
from datetime import datetime
from typing import Callable

from apscheduler.triggers.date import DateTrigger
from apscheduler.triggers.interval import IntervalTrigger
from sqlalchemy import select, and_

from collector.services.baseservice import BaseService
from database.dbasync import db_all, db_select
from database.dbmodels import Client
from database.dbmodels.event import Event, EventState
from database.dbmodels.evententry import EventEntry
from common.messenger import Category, TableNames, EVENT
from database.models.balance import Balance


@dataclass
class FutureCallback:
    time: datetime
    callback: Callable


class EventService(BaseService):

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # self.event_sync = SyncedService(self._messenger,
        #                                 EVENT,
        #                                 get_stmt=self._get_event,
        #                                 update=self._get_event,
        #                                 cleanup=self._on_event_delete)

    async def init(self):
        self._messenger.listen_class_all(EVENT.table, namespace=EVENT)

        for event in await db_all(
            select(Event).where(Event.is_expr(EventState.ACTIVE))
        ):
            self._schedule(event)

        await self._messenger.bulk_sub(
            TableNames.EVENT, {
                Category.NEW: self._on_event,
                Category.UPDATE: self._on_event,
                Category.DELETE: self._on_event_delete
            }
        )

        await self._messenger.bulk_sub(
            TableNames.BALANCE, {
                Category.NEW: self._on_balance,
                Category.LIVE: self._on_balance,
            }
        )

        await self._messenger.sub_channel(TableNames.TRANSFER, Category.NEW, self._on_transfer)

    async def _get_event(self, event_id: int) -> Event:
        return await db_select(Event,
                               Event.id == event_id,
                               eager=[(Event.entries, [
                                   EventEntry.client,
                                   EventEntry.init_balance
                               ])],
                               session=self._db)

    async def _on_event(self, data: dict):
        self._schedule(
            await self._db.get(Event, data['id'])
        )

    async def _on_transfer(self, data: dict):
        async with self._db_lock:
            event_entries = await db_all(
                select(EventEntry).where(
                    EventEntry.client_id == data['client_id'],
                    ~Event.allow_transfers
                ).join(EventEntry.event),
                session=self._db
            )

    async def _on_balance(self, data: dict):
        async with self._db_lock:
            scores: list[EventEntry] = await db_all(
                select(EventEntry).where(
                    EventEntry.client_id == data['client_id']
                ).join(Event, and_(
                    Event.id == EventEntry.event_id,
                    Event.is_expr(EventState.ACTIVE)
                )),
                EventEntry.init_balance,
                EventEntry.client,
                session=self._db
            )
            balance = Balance(**data)

    def _on_event_delete(self, data: dict):
        self._unregister(data['id'])

    async def _save_event(self, event_id: int):
        event = await self._get_event(event_id)
        await event.save_leaderboard()
        await self._db.commit()

    def schedule_job(self, event_id: int, run_date: datetime, category: Category):
        job_id = self.job_id(event_id, category)

        if self._scheduler.get_job(job_id):
            self._scheduler.reschedule_job(
                job_id,
                trigger=DateTrigger(run_date=run_date)
            )
        else:
            async def fn():
                event = await self._get_event(event_id)
                if event:
                    if category in (EVENT.END, EVENT.START):
                        await event.save_leaderboard()

                        if category == EVENT.END:
                            event.final_summary = await event.get_summary()

                        await self._db.commit()
                    return await self._messenger.pub_instance(event, category)

            self._scheduler.add_job(
                func=fn,
                trigger=DateTrigger(run_date=run_date),
                id=job_id
            )

    def _schedule(self, event: Event):

        self.schedule_job(event.id, event.start, EVENT.START)
        self.schedule_job(event.id, event.end, EVENT.END)
        self.schedule_job(event.id, event.registration_start, EVENT.REGISTRATION_START)
        self.schedule_job(event.id, event.registration_end, EVENT.REGISTRATION_END)

        self._scheduler.add_job(
            func=lambda: self._save_event(event.id),
            trigger=IntervalTrigger(days=1),
            id=f"event:{event.id}",
            jitter=60
        )

    def _unregister(self, event_id: int):

        def remove_job(category: Category):
            self._scheduler.remove_job(
                self.job_id(event_id, category)
            )

        remove_job(EVENT.START)
        remove_job(EVENT.END)
        remove_job(EVENT.REGISTRATION_START)
        remove_job(EVENT.REGISTRATION_END)

        self._scheduler.remove_job(f"event:{event_id}")

    @classmethod
    def job_id(cls, event_id: int, category: Category):
        return f'{event_id}:{category}'
