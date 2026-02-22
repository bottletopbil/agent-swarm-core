import time
from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field
import uuid

class MessageEnvelope(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    sender: str
    payload: Dict[str, Any]
    timestamp: float = Field(default_factory=time.time)
    
    # Optional fields for future phases (Phase 9 Cryptography / Phase 10 Lamport etc)
    thread: Optional[str] = None
    capability: Optional[str] = None
    verb: Optional[str] = None
    content_refs: List[str] = Field(default_factory=list)
    policy_capsule_hash: Optional[str] = None
    lamport: Optional[int] = None
    sig: Optional[str] = None

    def dict_for_bus(self):
        """Serialize envelope payload to be sent over the bus cleanly."""
        return self.model_dump(exclude_none=True)
