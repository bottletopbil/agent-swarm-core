import pytest
import os
import json
from unittest.mock import patch

os.environ["OPENAI_API_KEY"] = "mock_key_for_testing"

from sqlmodel import SQLModel, create_engine, Session, select
from database import Task, TaskStatus
import database

from sqlalchemy.pool import StaticPool

sqlite_url = "sqlite://"
engine = create_engine(sqlite_url, connect_args={"check_same_thread": False}, poolclass=StaticPool)

def get_session_override():
    with Session(engine) as session:
        yield session

database.get_session = get_session_override
database.engine = engine

from coordinator import CoordinatorService
from worker import WorkerService
from verifier import VerifierService
from planner import PlannerService

@pytest.fixture(autouse=True)
def setup_db():
    SQLModel.metadata.create_all(engine)
    yield
    SQLModel.metadata.drop_all(engine)

@patch('llm_client.LLMClient.plan_task')
@patch('llm_client.LLMClient.generate_text')
@patch('llm_client.LLMClient.verify_result')
def test_phase6_5_dag_resolution(mock_verify, mock_generate, mock_plan):
    """
    Test Phase 6.5: DAG Dependency Resolution
    """
    # 0. Setup Mock Responses
    mock_plan.return_value = [
        {"id": "write_1", "prompt": "Write chapter 1", "depends_on": []},
        {"id": "edit_1", "prompt": "Edit chapter 1", "depends_on": ["write_1"]}
    ]
    mock_generate.return_value = "Worker output."
    mock_verify.return_value = (True, "Good.")
    
    # 1. User adds a Complex Task
    with next(database.get_session()) as session:
        task = Task(prompt="Write a book", requires_planning=True)
        session.add(task)
        session.commit()
        session.refresh(task)
        parent_id = task.id
        
    coordinator = CoordinatorService()
    planner = PlannerService()
    worker = WorkerService()
    verifier = VerifierService()
    
    # 2. Coordinator routes to Planner
    coordinator.run_once()
    
    # 3. Planner breaks it down into DAG
    msg, msg_id = planner.planner_queue.pop()
    planner.process_message(msg)
    planner.planner_queue.ack(msg_id)
    
    with next(database.get_session()) as session:
        children = session.exec(select(Task).where(Task.parent_id == parent_id)).all()
        assert len(children) == 2
        
        task_write = next(c for c in children if "Write chapter 1" in c.prompt)
        task_edit = next(c for c in children if "Edit chapter 1" in c.prompt)
        
        assert task_write.status == TaskStatus.PENDING
        assert task_edit.status == TaskStatus.LOCKED
        
    # 4. Coordinator pushes PENDING tasks (Task Write) but NOT Locked ones
    coordinator.run_once()
    
    # Task Write goes to worker -> verifier
    msg1, msg1_id = worker.worker_queue.pop()
    worker.process_message(msg1)
    worker.worker_queue.ack(msg1_id)
    
    v_msg1, v_msg1_id = verifier.verifier_queue.pop()
    verifier.process_message(v_msg1)
    verifier.verifier_queue.ack(v_msg1_id)
    
    # 5. Coordinator runs again. It sees Task Write is DONE, so it unlocks Task Edit
    coordinator.run_once()
    
    with next(database.get_session()) as session:
        task_edit_db = session.get(Task, task_edit.id)
        assert task_edit_db.status == TaskStatus.PENDING
        assert "Output from precursor" in task_edit_db.prompt # Context was injected
        
    # 6. Task Edit goes to worker -> verifier
    coordinator.run_once() # Actually push it to worker queue
    
    msg2, msg2_id = worker.worker_queue.pop()
    worker.process_message(msg2)
    worker.worker_queue.ack(msg2_id)
    
    v_msg2, v_msg2_id = verifier.verifier_queue.pop()
    verifier.process_message(v_msg2)
    verifier.verifier_queue.ack(v_msg2_id)
    
    # 7. Rollup to Parent
    coordinator.run_once()
    
    with next(database.get_session()) as session:
        parent_db = session.get(Task, parent_id)
        assert parent_db.status == TaskStatus.DONE
