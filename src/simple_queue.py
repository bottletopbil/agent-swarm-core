import json
from sqlmodel import select
from database import get_session, QueueMessage

class SimpleQueue:
    def __init__(self, queue_name: str):
        self.queue_name = queue_name

    def push(self, payload: dict):
        with next(get_session()) as session:
            msg = QueueMessage(queue_name=self.queue_name, payload=json.dumps(payload))
            session.add(msg)
            session.commit()

    def pop(self) -> tuple[dict | None, str | None]:
        """Pops a message or returns (None, None).
        Returns (payload, message_id). The caller MUST call ack(message_id) when finished.
        """
        with next(get_session()) as session:
            # Poll for first pending message
            statement = select(QueueMessage).where(
                QueueMessage.queue_name == self.queue_name,
                QueueMessage.status == "pending"
            ).order_by(QueueMessage.id).limit(1)
            
            msg = session.exec(statement).first()
            if msg:
                # We mark it as "in_progress" so other workers don't grab it
                msg.status = "in_progress"
                session.add(msg)
                session.commit()
                return json.loads(msg.payload), msg.id
            return None, None
            
    def ack(self, message_id: str):
        """Marks a message as successfully processed."""
        with next(get_session()) as session:
            msg = session.get(QueueMessage, message_id)
            if msg:
                msg.status = "processed"
                session.add(msg)
                session.commit()
                
    def reset_stuck_messages(self):
        """Called on worker startup to reset 'in_progress' messages back to 'pending'"""
        with next(get_session()) as session:
            statement = select(QueueMessage).where(
                QueueMessage.queue_name == self.queue_name,
                QueueMessage.status == "in_progress"
            )
            stuck_msgs = session.exec(statement).all()
            for msg in stuck_msgs:
                msg.status = "pending"
                session.add(msg)
            session.commit()
