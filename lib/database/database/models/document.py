from __future__ import annotations
from datetime import datetime
from enum import Enum
from typing import Optional, Literal, Any

from database.models import BaseModel


class Operator(Enum):
    GT = "gt"
    LT = "lt"
    EQ = "eq"
    NE = "ne"
    INCLUDES = "includes"
    EXCLUDES = "excludes"


class Mark(BaseModel):
    type: str
    attrs: Optional[dict]


class Dates(BaseModel):
    since: datetime
    to: datetime


class FilterInput(BaseModel):
    op: Operator
    value: Any


FilterOptions = dict[str, list[FilterInput]]


class TradeData(BaseModel):
    clientIds: list[int]
    tradeIds: list[int]
    dates: Dates
    tradeSource: Literal['all', 'select', 'children']
    filters: FilterOptions


class DocumentModel(BaseModel):
    type: str
    content: 'Optional[list[DocumentModel]]'
    type: 'Optional[str]'
    text: 'Optional[str]'
    attrs: 'Optional[dict[str, Any]]'
    marks: 'Optional[list[Mark]]'

    @property
    def title(self):
        titleNode = self[0]
        return getattr(titleNode[0], 'text', None)

    def __getitem__(self, i) -> 'DocumentModel' | None:
        if self.content:
            return self.content[i]
        return None

    def __setitem__(self, key, value):
        return self.content.__setitem__(key, value)

    def __len__(self):
        if self.content:
            return self.content.__len__()
        return 0

    def json(
            self,
            **kwargs
    ) -> str:
        return super().json(**kwargs, exclude_none=True)

    def dict(
            self,
            **kwargs
    ) -> dict:
        kwargs['exclude_none'] = True
        return super().dict(**kwargs)

    def get_from_heading(self, heading_id: str) -> Optional[DocumentModel]:
        result: Optional[DocumentModel] = None

        def recursive(current: DocumentModel):
            nonlocal result

            if current.content:
                for node in current.content:

                    if node.type == "heading":
                        if result is None:
                            if node.attrs.get('id') == heading_id:
                                result = DocumentModel(type='doc', content=[])
                        elif node.attrs['level'] >= result[0].attrs['level']:
                            return True

                    if result is None:
                        if recursive(node):
                            return True
                    else:
                        result.content.append(node)

        recursive(self)

        return result

    @property
    def all_data(self):
        results = []

        def recursive(current: DocumentModel):
            if current.attrs and current.attrs['data']:
                results.append(current.attrs['data'])

            if current.content:
                for node in current.content:
                    recursive(node)

        recursive(self)

        return results

    @property
    def all_trades(self):
        return [
            result['tradeIds']
            for result in self.all_data
        ]


DocumentModel.update_forward_refs()
