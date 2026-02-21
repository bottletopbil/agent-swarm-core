import pytest
import os
from unittest.mock import patch

# Set a dummy key for testing so the OpenAI client initializes without error
os.environ["OPENAI_API_KEY"] = "mock_key_for_testing"

from sqlmodel import SQLModel, create_engine, Session
from database import Task, TaskStatus, QueueMessage
import database

# Use in-memory SQLite for tests
sqlite_url = "sqlite://"
engine = create_engine(sqlite_url)

def get_session_override():
    with Session(engine) as session:
        yield session

# Override the database session for exactly these tests
database.get_session = get_session_override
database.engine = engine

from coordinator import CoordinatorService
from worker import WorkerService
from verifier import VerifierService

@pytest.fixture(autouse=True)
def setup_db():
    SQLModel.metadata.create_all(engine)
    yield
    SQLModel.metadata.drop_all(engine)

@patch('llm_client.LLMClient.generate_text')
@patch('llm_client.LLMClient.verify_result')
def test_decoupled_happy_path(mock_verify, mock_generate):
    """
    Test Phase 5 Decoupled Path using mocked LLM responses.
    This proves that the exact sequence of Queue pushes/pops works correctly between 3 separate objects.
    """
    mock_generate.return_value = "This is a decoupled LLM poem."
    mock_verify.return_value = (True, "Good job LLM.")
    
    # 0. Simulate the Dashboard adding a task
    with next(database.get_session()) as session:
        task = Task(prompt="Decoupled prompt")
        session.add(task)
        session.commit()
        session.refresh(task)
        task_id = task.id
        
    coordinator = CoordinatorService()
    worker = WorkerService()
    verifier = VerifierService()
    
    # 1. Coordinator picks it up and puts it on worker_queue
    coordinator.run_once()
    
    with next(database.get_session()) as session:
        db_task = session.get(Task, task_id)
        assert db_task.status == TaskStatus.IN_PROGRESS
        
    # 2. Worker pops from worker_queue
    msg1, msg_id1 = worker.worker_queue.pop()
    assert msg1 is not None
    assert msg1["task_id"] == task_id
    worker.process_message(msg1)
    worker.worker_queue.ack(msg_id1)
    
    with next(database.get_session()) as session:
        db_task = session.get(Task, task_id)
        assert db_task.status == TaskStatus.VERIFYING
        assert db_task.result == "This is a decoupled LLM poem."
        
    # 3. Verifier pops from verifier_queue
    msg2, msg_id2 = verifier.verifier_queue.pop()
    assert msg2 is not None
    assert msg2["task_id"] == task_id
    verifier.process_message(msg2)
    verifier.verifier_queue.ack(msg_id2)
    
    with next(database.get_session()) as session:
        db_task = session.get(Task, task_id)
        assert db_task.status == TaskStatus.DONE


@patch('llm_client.LLMClient.generate_text')
@patch('llm_client.LLMClient.verify_result')
def test_decoupled_sabotage_path(mock_verify, mock_generate):
    """
    Test Phase 5 Decoupled Sabotage:
    Worker output is rejected by the Verifier.
    """
    mock_generate.return_value = "Terrible output."
    mock_verify.return_value = (False, "Rejected for being terrible.")
    
    with next(database.get_session()) as session:
        task = Task(prompt="Write a terrible poem")
        session.add(task)
        session.commit()
        session.refresh(task)
        task_id = task.id
        
    coordinator = CoordinatorService()
    worker = WorkerService()
    verifier = VerifierService()
    
    coordinator.run_once()
    
    msg1, msg1_id = worker.worker_queue.pop()
    worker.process_message(msg1)
    worker.worker_queue.ack(msg1_id)
    
    msg2, msg2_id = verifier.verifier_queue.pop()
    verifier.process_message(msg2)
    verifier.verifier_queue.ack(msg2_id)
    
    with next(database.get_session()) as session:
        db_task = session.get(Task, task_id)
        assert db_task.status == TaskStatus.FAILED
        assert db_task.verifier_notes == "Rejected for being terrible."
        assert db_task.result is None
