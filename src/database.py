from typing import Optional
from sqlmodel import Field, SQLModel, create_engine, Session, select
from enum import Enum
import uuid

class TaskStatus(str, Enum):
    PENDING = "Pending"
    IN_PROGRESS = "In Progress"
    VERIFYING = "Verifying"
    LOCKED = "Locked"
    DONE = "Done"
    FAILED = "Failed"


class Task(SQLModel, table=True):
    id: str = Field(default_factory=lambda: str(uuid.uuid4()), primary_key=True)
    prompt: str
    status: TaskStatus = Field(default=TaskStatus.PENDING)
    result: Optional[str] = None
    verifier_notes: Optional[str] = None
    # For Reproducibility
    seed: int = Field(default_factory=lambda: uuid.uuid4().int % 1000000)
    temperature: float = Field(default=1.0)
    
    # Phase 6.5: DAG Sub-tasking
    parent_id: Optional[str] = Field(default=None, index=True)
    requires_planning: bool = Field(default=False)
    depends_on: Optional[str] = Field(default="[]") # JSON string of task IDs this task depends on

# Create a sqlite engine
import os
sqlite_file_name = os.getenv("DB_NAME", "swarm_state.db")
sqlite_url = f"sqlite:///{sqlite_file_name}"
engine = create_engine(sqlite_url)

def create_db_and_tables():
    """Create the sqlite database and tables if they don't exist."""
    SQLModel.metadata.create_all(engine)

def get_session():
    """Yields a database session."""
    with Session(engine) as session:
        yield session
