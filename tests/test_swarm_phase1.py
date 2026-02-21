import pytest
from pydantic import ValidationError
from swarm import (
    Task, 
    TaskStatus, 
    Coordinator, 
    MockWorker, 
    MockVerifier
)

def test_happy_path_workflow():
    """
    Test the strict 'Happy Path':
    - Task starts Pending
    - Assigned to Worker -> Status: In Progress
    - Worker completes -> Status: Verifying
    - Verifier passes -> Status: Done
    """
    coordinator = Coordinator()
    task = coordinator.add_task("Write a 5 line poem about space.")
    
    assert task.status == TaskStatus.PENDING
    
    # Run the orchestrator loop until the task is no longer pending/in progress
    coordinator.run_until_complete()
    
    assert task.status == TaskStatus.DONE
    assert task.result is not None
    assert "Worker completed:" in task.result
    assert task.verifier_notes == "Passed verification."


def test_sabotage_verifier_rejection():
    """
    Test the 'Sabotage' path:
    - What happens if the Verifier rejects the Worker's output?
    - The task should return to Pending or fail gracefully.
    """
    coordinator = Coordinator()
    
    # We create a verifier that always fails the task
    strict_verifier = MockVerifier(always_fail=True)
    coordinator.verifier = strict_verifier
    
    task = coordinator.add_task("This is a bad prompt that will fail.")
    
    # Run the orchestrator loop
    coordinator.run_until_complete()
    
    # Instead of silently hanging, the task should be marked FAILED
    assert task.status == TaskStatus.FAILED
    assert "Failed verification" in task.verifier_notes
    assert task.result is None # Result is wiped or kept as evidence
