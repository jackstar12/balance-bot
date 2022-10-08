import asyncio
from functools import wraps
from typing import Dict, Optional, TypeVar, Generic, Any

from sqlalchemy.sql import Select
from sqlalchemy.ext.asyncio import AsyncSession
from common.utils import CoroOrCallable
from common.dbsync import Base
from common.dbasync import db_unique
from common.messenger import Category
from common.messenger import Messenger, MessengerNameSpace


TTable = TypeVar('TTable', bound=Base)


class SyncedService(Generic[TTable]):

    def __init__(self,
                 messenger: Messenger,
                 namespace: MessengerNameSpace,
                 db: AsyncSession,
                 base_stmt: Select,
                 get_stmt: CoroOrCallable,
                 update: CoroOrCallable,
                 cleanup: CoroOrCallable):
        self._identity_map: dict[Any, TTable] = {}
        self._messenger = messenger
        self._namespace = namespace
        self._get_stmt = get_stmt
        self._update = update
        self._cleanup = cleanup
        self._identity_map_lock = asyncio.Lock()
        self._db = db
        self._base_stmt = base_stmt

    @property
    def namespace(self):
        return self._namespace

    @property
    def messenger(self):
        return self._messenger

    def uses_identity(self, coro_or_callback):
        @wraps(coro_or_callback)
        async def wrapper(*args, **kwargs):
            async with self._identity_map_lock:
                if asyncio.iscoroutinefunction(coro_or_callback):
                    return await coro_or_callback(*args, **kwargs)
                else:
                    return coro_or_callback(*args, **kwargs)
        return wrapper

    async def sub(self):
        await self._messenger.v2_bulk_sub(
            self.namespace,
            {
                Category.NEW: self.uses_identity(self._on_add),
                Category.DELETE: self.uses_identity(self._on_delete),
                Category.UPDATE: self.uses_identity(self._on_update)
            }
        )
    async def get_ident(self, identity: Any) -> Optional[TTable]:
        async with self._identity_map_lock:
            return self._identity_map.get(identity)

    async def identity_map(self):
        async with self._identity_map_lock:
            yield self._identity_map

    async def all_values(self):
        async with self.identity_map() as ident:
            yield ident.values()

    async def _on_delete(self, data: Dict):
        instance = self._identity_map.pop(data['id'])
        await self._cleanup(instance)

    async def _on_add(self, data: Dict):
        instance = await db_unique(
            self._base_stmt.filter_by(id=data['id']),
            session=self._db
        )
        if instance:
            self._identity_map[data['id']] = instance

    async def _on_update(self, data: dict):
        existing = self._identity_map.get(data['id'])
        if existing:
            self._identity_map[data['id']] = await self._update(existing)
