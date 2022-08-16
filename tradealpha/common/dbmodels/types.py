from __future__ import annotations

from typing import Optional

from pydantic import Extra

from sqlalchemy import TypeDecorator
from sqlalchemy.dialects.postgresql import JSONB

# class DataModel(BaseModel):
from tradealpha.common.models import BaseModel


class Mark(BaseModel):
    type: str
    attrs: Optional[dict]


class DocumentModel(BaseModel):
    type: str
    content: 'Optional[list[DocumentModel]]'
    type: 'Optional[str]'
    text: 'Optional[str]'
    attrs: 'Optional[dict]'
    marks: 'Optional[list[Mark]]'

    def title(self):
        titleNode = self.content[0]
        return titleNode.content[0].text if titleNode else None

    def __getitem__(self, i) -> 'DocumentModel' | None:
        if self.content:
            return self.content[i]
        return None

    def __setitem__(self, key, value):
        return self.content.__setitem__(key, value)

    def __len__(self):
        return self.content.__len__()

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


class Document(TypeDecorator):
    impl = JSONB

    def process_bind_param(self, value, dialect):
        if isinstance(value, DocumentModel):
            return value.dict()
        return value

    def process_result_value(self, value, dialect):
        if value:
            return DocumentModel.construct(**value)
        return value


class Data(TypeDecorator):
    impl = JSONB

    def process_bind_param(self, value, dialect):
        return value

    def process_result_value(self, value, dialect):
        return value
