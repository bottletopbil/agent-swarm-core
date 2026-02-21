import pytest
import os
from unittest.mock import patch, MagicMock

# Set a dummy key for testing so the OpenAI client initializes without error
os.environ["OPENAI_API_KEY"] = "mock_key_for_testing"

from sqlmodel import SQLModel, create_engine, Session
from database import Task, TaskStatus
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

from monolith import Coordinator, Worker, Verifier

@pytest.fixture(autouse=True)
def setup_db():
    SQLModel.metadata.create_all(engine)
    yield
    SQLModel.metadata.drop_all(engine)

@patch('llm_client.LLMClient.generate_text')
@patch('llm_client.LLMClient.verify_result')
def test_happy_path_workflow_llm(mock_verify, mock_generate):
    """
    Test Phase 2 Happy Path using mocked LLM responses.
    """
    mock_generate.return_value = "This is a real LLM poem."
    mock_verify.return_value = (True, "Good job LLM.")

    coordinator = Coordinator()
    task = coordinator.add_task("Write a 5 line poem about space.")
    
    coordinator.run_until_complete()
    
    # Needs to be fetched from DB to verify
    with next(database.get_session()) as session:
        db_task = session.get(Task, task.id)
        assert db_task.status == TaskStatus.DONE
        assert db_task.result == "This is a real LLM poem."
        assert db_task.verifier_notes == "Good job LLM."


@patch('llm_client.LLMClient.generate_text')
@patch('llm_client.LLMClient.verify_result')
def test_sabotage_verifier_rejection_llm(mock_verify, mock_generate):
    """
    Test Phase 2 Sabotage Path: LLM Verifier rejects the output.
    """
    mock_generate.return_value = "potato"
    # The JSON verification fails it
    mock_verify.return_value = (False, "You just said potato.")

    coordinator = Coordinator()
    task = coordinator.add_task("Write a poem about dirt.")
    
    coordinator.run_until_complete()
    
    with next(database.get_session()) as session:
        db_task = session.get(Task, task.id)
        assert db_task.status == TaskStatus.FAILED
        assert db_task.verifier_notes == "You just said potato."
        assert db_task.result is None
