from pydantic import BaseModel, Field


class RosterInput(BaseModel):
    source: str = Field(default='manual.json', max_length=200)
    records: list[dict] = Field(min_length=1, max_length=20000)


class EventInput(BaseModel):
    source: str = Field(default='manual.json', max_length=200)
    records: list[dict] = Field(min_length=1, max_length=20000)
