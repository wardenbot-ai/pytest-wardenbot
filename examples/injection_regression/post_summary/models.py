from pydantic import BaseModel


class PostSummary(BaseModel):
    themes: list[str]
    summary: str
    flagged_post_ids: list[str]
