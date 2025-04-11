from pydantic import BaseModel
from typing import List, Optional
from datetime import datetime

class GroupCreate(BaseModel):
    name: str
    members: List[str]
    description: Optional[str] = None

class GroupUpdate(BaseModel):
    name: Optional[str] = None
    description: Optional[str] = None
    members: Optional[List[str]] = None

class Group(BaseModel):
    groupId: str
    name: str
    description: Optional[str] = None
    members: List[str]
    admins: List[str]
    createdTime: datetime