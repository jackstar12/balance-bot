from dataclasses import dataclass
from dataclasses import dataclass
from datetime import datetime
from typing import Callable

import pytz
from apscheduler.triggers.date import DateTrigger
from sqlalchemy import select, and_
import tradealpha.common.dbmodels
from tradealpha.collector.services.syncedservice import SyncedService
from tradealpha.collector.services.baseservice import BaseService
from tradealpha.common.dbasync import db_all, db_select
from tradealpha.common.dbmodels import Client
from tradealpha.common.dbmodels.event import Event, EventState
from tradealpha.common.dbmodels.score import EventScore
from tradealpha.common.messenger import Category, TableNames, EVENT
from tradealpha.common.models.balance import Balance


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
        now = datetime.now(tz=pytz.utc)

        for event in await db_all(
                select(Event).where(Event.is_expr(EventState.ACTIVE))
        ):
            self._schedule(event)
            await Event.save_leaderboard(event.id, self._db)
        await self._db.commit()

        #await self.event_sync.sub()

        await self._messenger.v2_sub_channel(TableNames.EVENT, Category.END, self._on_event_end)
        await self._messenger.v2_sub_channel(TableNames.BALANCE, Category.NEW, self._on_balance)

    async def _on_balance(self, data: dict):
        async with self._db_lock:
            scores: list[EventScore] = await db_all(
                select(EventScore).filter(
                    EventScore.client_id == data['client_id']
                ).join(Event, and_(
                    Event.id == EventScore.event_id,
                    Event.is_expr(EventState.ACTIVE)
                )),
                EventScore.init_balance,
                session=self._db
            )
            balance = Balance(**data)

            for score in scores:
                event = await self._db.get(Event, score.event_id)

                if score.init_balance is None:
                    score.init_balance = await Client.get_balance_at_time(
                        data['client_id'],
                        event.start,
                        db=self._db
                    )

                score.update(balance)
                await Event.save_leaderboard(event.id, self._db)
            await self._db.commit()

    async def _on_event_end(self, data: dict):
        scores: list[EventScore] = await db_all(
            select(EventScore).filter(
                EventScore.event_id == data['id']
            ),
            EventScore.init_balance,
            EventScore.client,
            session=self._db
        )
        # await self._redis.zadd('event:leaderboard', )
        # await self._redis.zrange()
        event: Event = await self._db.get(Event, data['id'])
        for score in scores:
            if score.init_balance is None:
                score.init_balance = await Client.get_balance_at_time(
                    data['client_id'],
                    event.start,
                    db=self._db
                )
            score.update(
                await Client.get_balance_at_time(score.client_id, event.end, db=self._db)
            )
        await Event.save_leaderboard(event.id, self._db)
        await self._db.commit()

    async def _get_event(self, data: dict):
        event = await db_select(Event, session=self._db, id=data['id'])
        self._schedule(event)
        return event

    def _on_event_delete(self, data: dict):
        self._unregister(data['id'])

    def _schedule(self, event: Event):
        self._schedule_event_job(event, event.start, Category.START)
        self._schedule_event_job(event, event.end, Category.END)
        self._schedule_event_job(event, event.registration_start, Category.REGISTRATION_START)
        self._schedule_event_job(event, event.registration_end, Category.REGISTRATION_END)

    def _unregister(self, event_id: int):
        self._remove_event_job(event_id, Category.START)
        self._remove_event_job(event_id, Category.END)
        self._remove_event_job(event_id, Category.REGISTRATION_START)
        self._remove_event_job(event_id, Category.REGISTRATION_END)

    def _remove_event_job(self, event_id: id, category: Category):
        self._scheduler.remove_job(f'{event_id}{category.value}')

    def _schedule_event_job(self, event: Event, run_date: datetime, category: Category):
        event_id = f'{event.id}{category.value}'
        if self._scheduler.get_job(event_id):
            self._scheduler.reschedule_job(
                event_id,
                trigger=DateTrigger(run_date=run_date)
            )
        else:
            self._scheduler.add_job(
                lambda: self._pub_event(event, category),
                trigger=DateTrigger(run_date=run_date),
                id=event_id
            )

    def _pub_event(self, event: Event, category: Category):
        self._messenger.pub_channel(TableNames.EVENT, category,
                                    obj=event.serialize(),
                                    channel_id=event.id)

