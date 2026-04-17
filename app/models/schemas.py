from pydantic import BaseModel
from typing import Optional, List


class UploadResponse(BaseModel):
    file_id: str
    filename: str
    url: str


class PageInfo(BaseModel):
    page: int
    text: Optional[str]
    image_url: Optional[str]


class ExplainRequest(BaseModel):
    file_id: str
    page: Optional[int] = None
    auto_next: Optional[bool] = False
    course_name: Optional[str] = "机器学习导论"


class ExplainResponse(BaseModel):
    task_id: str
    file_id: str
    page: int
    explanation: str
    combined_text: Optional[str]
    audio_url: Optional[str]


class AudioResponse(BaseModel):
    file_id: str
    page: int
    audio_url: str


class StatusResponse(BaseModel):
    task_id: str
    status: str
    detail: Optional[str]
