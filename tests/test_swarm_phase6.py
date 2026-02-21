import pytest
import os
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
def test_phase6_sub_tasking(mock_verify, mock_generate, mock_plan):
    """
    Test Phase 6: Sub-tasking and the Planner Agent.
    """
    mock_plan.return_value = [
        {"id": "t1", "prompt": "Sub-task 1", "depends_on": []},
        {"id": "t2", "prompt": "Sub-task 2", "depends_on": []}
    ]
    mock_generate.return_value = "Done with sub-task."
    mock_verify.return_value = (True, "Good.")
    
    # 0. User adds a Complex Task
    with next(database.get_session()) as session:
        task = Task(prompt="Complex Prompt", requires_planning=True)
        session.add(task)
        session.commit()
        session.refresh(task)
        parent_id = task.id
        
    coordinator = CoordinatorService()
    planner = PlannerService()
    worker = WorkerService()
    verifier = VerifierService()
    
    # 1. Coordinator routes to Planner
    coordinator.run_once()
    
    with next(database.get_session()) as session:
        db_task = session.get(Task, parent_id)
        assert db_task.status == TaskStatus.IN_PROGRESS
        
    # 2. Planner breaks it down
    msg, msg_id = planner.planner_queue.pop()
    assert msg is not None
    planner.process_message(msg)
    planner.planner_queue.ack(msg_id)
    
    with next(database.get_session()) as session:
        children = session.exec(select(Task).where(Task.parent_id == parent_id)).all()
        assert len(children) == 2
        assert children[0].status == TaskStatus.PENDING
        child1_id = children[0].id
        child2_id = children[1].id
        
    # 3. Coordinator picks up the 2 new pending sub-tasks
    coordinator.run_once()
    
    # 4. Worker executes them
    msg1, msg1_id = worker.worker_queue.pop()
    worker.process_message(msg1)
    worker.worker_queue.ack(msg1_id)
    
    msg2, msg2_id = worker.worker_queue.pop()
    worker.process_message(msg2)
    worker.worker_queue.ack(msg2_id)
    
    # 5. Verifier verifies them
    v_msg1, v_msg1_id = verifier.verifier_queue.pop()
    verifier.process_message(v_msg1)
    verifier.verifier_queue.ack(v_msg1_id)
    
    v_msg2, v_msg2_id = verifier.verifier_queue.pop()
    verifier.process_message(v_msg2)
    verifier.verifier_queue.ack(v_msg2_id)
    
    # 6. Coordinator checks parents and rolls up the DONE status
    coordinator.run_once()
    
    with next(database.get_session()) as session:
        db_task = session.get(Task, parent_id)
        assert db_task.status == TaskStatus.DONE
        assert "=== FINAL COMBINED OUTPUT ===" in db_task.result
        assert "Sub-task 1" in db_task.result
        assert "Sub-task 2" in db_task.result
