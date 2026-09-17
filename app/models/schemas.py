from pydantic import BaseModel
from typing import Optional


class UploadResponse(BaseModel):
    file_id: str
    filename: str
    url: str
    total_pages: int


class PageInfo(BaseModel):
    page: int
    text: Optional[str]
    image_url: Optional[str]


class StatusResponse(BaseModel):
    task_id: str
    status: str
    detail: Optional[str]
