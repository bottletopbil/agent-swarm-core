import pytest
import asyncio
import subprocess
import time
import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..', 'src')))
import database
from database import Task, TaskStatus
from coordinator import CoordinatorService
from sqlmodel import select, create_engine

# Test Environment Variables to Isolate System
TEST_DB = "test_partition.db"
TEST_NATS_PORT = 4223
TEST_NATS_URL = f"nats://localhost:{TEST_NATS_PORT}"

@pytest.fixture(scope="session", autouse=True)
def isolated_nats_and_db():
    # 1. Start an isolated NATS server for tests
    print(f"Starting isolated NATS on {TEST_NATS_PORT}...")
    nats_proc = subprocess.Popen(["nats-server", "-js", "-p", str(TEST_NATS_PORT), "-sd", "nats_data_testpartition"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    
    # 2. Inject environment variables for the current process and all subprocesses
    os.environ["DB_NAME"] = TEST_DB
    os.environ["NATS_URL"] = TEST_NATS_URL
    os.environ["PYTHONPATH"] = "src"
    
    # Re-initialize the test DB engines
    database.sqlite_file_name = TEST_DB
    database.sqlite_url = f"sqlite:///{TEST_DB}"
    database.engine = create_engine(database.sqlite_url)
    database.create_db_and_tables()

    time.sleep(2) # Give NATS time to fully boot JetStream
    
    yield
    
    # Teardown isolated infrastructure
    nats_proc.terminate()
    nats_proc.wait()
    if os.path.exists(TEST_DB):
        os.remove(TEST_DB)
    import shutil
    if os.path.exists("nats_data_testpartition"):
        shutil.rmtree("nats_data_testpartition")


@pytest.mark.asyncio
async def test_partition_recovery():
    """
    Split-Brain (Network Partition) Test:
    Simulates a network partition where the Worker process crashes mid-execution.
    Validates that:
    1. The Coordinator doesn't resend the payload (avoiding duplicate work).
    2. When a Worker comes online, NATS JetStream redelivers the missing ACK message.
    3. The internal SQLite state transitions cleanly without creating duplicate row entries in the table.
    """
    coordinator = CoordinatorService()
    await coordinator.bus.connect()
    
    # 1. Insert a target task manually
    with next(database.get_session()) as session:
        task = Task(prompt="Partition Test Task")
        session.add(task)
        session.commit()
        session.refresh(task)
        task_id = task.id
        
    # 2. Coordinator runs once: task goes PENDING -> IN_PROGRESS, sent to NATS
    await coordinator.run_once()
    
    with next(database.get_session()) as session:
        t = session.get(Task, task_id)
        assert t.status == TaskStatus.IN_PROGRESS
    
    # 3. Start Mock Worker with CRASH_MIDWAY to simulate a partition drop
    env = os.environ.copy()
    env["CRASH_MIDWAY"] = "1"
    env["OPENAI_API_KEY"] = "mock_key_for_testing"
    
    print("\nStarting crashing worker...")
    worker_proc_1 = subprocess.Popen([sys.executable, "tests/mock_worker_for_partition.py"], env=env)
    
    # Wait for the worker to pick it up and crash
    worker_proc_1.wait(timeout=10)
    assert worker_proc_1.returncode == 1 # Expected a crash
    
    # 4. The worker is 'offline'. Let the Coordinator attempt to check the status.
    print("Running coordinator while worker is offline...")
    await coordinator.run_once()
    
    with next(database.get_session()) as session:
        t = session.get(Task, task_id)
        # Should remain cleanly IN_PROGRESS
        assert t.status == TaskStatus.IN_PROGRESS 
        
        # Ensure no duplicate tasks were created by coordinator failing to coordinate
        all_tasks = session.exec(select(Task)).all()
        assert len(all_tasks) == 1
        
    # 5. Wait for the NATS JetStream default push consumer AckWait (30 seconds) to expire.
    print("Waiting 32 seconds for NATS JetStream AckWait redelivery threshold...")
    await asyncio.sleep(32)
    
    # 6. Restore the connection. Start a NEW worker process, this one will run successfully
    env["CRASH_MIDWAY"] = "0"
    print("Starting healthy recovering worker...")
    worker_proc_2 = subprocess.Popen([sys.executable, "tests/mock_worker_for_partition.py"], env=env)
    
    # Give the recovering worker time to receive the redelivered message (from AckWait timeout) and process it
    await asyncio.sleep(3)
    
    worker_proc_2.terminate()
    worker_proc_2.wait()
    
    # 7. Verify the task was completed successfully via redelivery!
    with next(database.get_session()) as session:
        t = session.get(Task, task_id)
        # Verify it transitioned correctly
        assert t.status == TaskStatus.VERIFYING
        assert t.result == "Recovered Result!"
        
        # Ensure still no duplicate entries in the tasks table!
        all_tasks = session.exec(select(Task)).all()
        assert len(all_tasks) == 1
        
    await coordinator.bus.close()
