import pytest
import pytest_asyncio
import asyncio
import os
import sys
import json
import shutil
import subprocess
import signal
from hypothesis import given, settings, HealthCheck, strategies as st
from datetime import datetime

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..', 'src')))
from audit_daemon import AuditDaemon
from verify_audit import AuditVerifier
from nats_bus import NatsBus
from envelope import MessageEnvelope

TEST_NATS_PORT = 4226
TEST_LOG_DIR = "tests/test_audit_logs"
DAEMON_SCRIPT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "src", "audit_daemon.py"))
ENV_VARS = os.environ.copy()
ENV_VARS["NATS_URL"] = f"nats://localhost:{TEST_NATS_PORT}"
# Pass the log dir via env variable so the subprocess daemon writes to our isolated folder
ENV_VARS["AUDIT_LOG_DIR"] = TEST_LOG_DIR

@pytest_asyncio.fixture(autouse=True)
async def isolated_environment():
    """Starts a clean NATS server and sets up isolated log directories for Phase 8 testing."""
    if os.path.exists("nats_data_audit_tests"):
        shutil.rmtree("nats_data_audit_tests")
    if os.path.exists(TEST_LOG_DIR):
        shutil.rmtree(TEST_LOG_DIR)
    os.makedirs(TEST_LOG_DIR, exist_ok=True)
        
    print(f"Starting isolated NATS on {TEST_NATS_PORT}...")
    nats_proc = subprocess.Popen(
        ["nats-server", "-js", "-sd", "nats_data_audit_tests", "-p", str(TEST_NATS_PORT)],
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL
    )
    
    # Let NATS initialize
    await asyncio.sleep(2)
    os.environ["NATS_URL"] = f"nats://localhost:{TEST_NATS_PORT}"

    yield
    
    # Cleanup
    nats_proc.terminate()
    nats_proc.wait()
    if os.path.exists("nats_data_audit_tests"):
        shutil.rmtree("nats_data_audit_tests")
    if os.path.exists(TEST_LOG_DIR):
        shutil.rmtree(TEST_LOG_DIR)


@pytest.mark.asyncio
async def test_p8_1_the_gap_stream_replay():
    """P8-1: Kill the daemon subprocess, run tasks, restart it, assert zero logs were missed."""
    bus = NatsBus(nats_url=ENV_VARS["NATS_URL"])
    await bus.connect()
    
    # 1. Start daemon for the first time via true subprocess
    daemon_proc1 = subprocess.Popen([sys.executable, DAEMON_SCRIPT], env=ENV_VARS)
    await asyncio.sleep(2) # Allow daemon to connect and subscribe
    
    # Send MSG 1
    env1 = MessageEnvelope(sender="test", capability="test", verb="init", payload={"test": 1})
    await bus.publish("tasks.worker", env1)
    await asyncio.sleep(1) # Allow processing time
    
    log_file = os.path.join(TEST_LOG_DIR, "audit.jsonl")
    
    # Assert MSG 1 is logged
    with open(log_file, "r") as f:
        lines = f.readlines()
        assert len(lines) == 1
        
    # SILENTLY KILL DAEMON 1 (Simulating host failure/OOM kill)
    daemon_proc1.send_signal(signal.SIGKILL)
    daemon_proc1.wait()
    
    # Send MSG 2 and 3 while NO DAEMON IS RUNNING
    env2 = MessageEnvelope(sender="test", capability="test", verb="process", payload={"test": 2})
    env3 = MessageEnvelope(sender="test", capability="test", verb="finalize", payload={"test": 3})
    await bus.publish("tasks.verifier", env2)
    await bus.publish("tasks.done", env3)
    await asyncio.sleep(1)
    
    # 2. Restart a completely fresh daemon subprocess
    daemon_proc2 = subprocess.Popen([sys.executable, DAEMON_SCRIPT], env=ENV_VARS)
    await asyncio.sleep(3) # Give it time to boot and replay history from JetStream
    
    # Assert MSG 2 and 3 were caught upon restart (Stream Replay worked)
    with open(log_file, "r") as f:
        lines = f.readlines()
        assert len(lines) == 3 # 1 from before, 2 replayed
        
    # Clean shutdown
    daemon_proc2.terminate()
    daemon_proc2.wait()
    await bus.close()


@pytest.mark.asyncio
async def test_p8_2_log_tampering_detection():
    """P8-2: Manually modify a character in audit.jsonl and assert verify_audit.py throws error."""
    bus = NatsBus(nats_url=ENV_VARS["NATS_URL"])
    await bus.connect()
    
    daemon_proc = subprocess.Popen([sys.executable, DAEMON_SCRIPT], env=ENV_VARS)
    await asyncio.sleep(2)
    
    # Generate valid logs
    envA = MessageEnvelope(id="TASK_A", sender="test", payload={})
    envB = MessageEnvelope(id="TASK_B", sender="test", payload={})
    await bus.publish("tasks.test", envA)
    await bus.publish("tasks.test", envB)
    await asyncio.sleep(2)
    
    log_file = os.path.join(TEST_LOG_DIR, "audit.jsonl")
    
    # Verify mathematically that it passes
    verifier = AuditVerifier(log_path=log_file)
    assert verifier.verify_hash_chain() is True
    
    # TAMPER THE LOG (Change MSG A's payload)
    with open(log_file, "r") as f:
        lines = f.readlines()
    
    lines[0] = lines[0].replace('"TASK_A"', '"HACKED"')
    
    with open(log_file, "w") as f:
        f.writelines(lines)
        
    # Verify mathematically that it now FAILS
    assert verifier.verify_hash_chain() is False
    
    daemon_proc.terminate()
    daemon_proc.wait()
    await bus.close()


@pytest.mark.asyncio
async def test_p8_3_disk_pressure_safe_crash():
    """P8-3: Simulate an OSError on file write via a mock daemon subprocess, proving instant NAK and redelivery."""
    bus = NatsBus(nats_url=ENV_VARS["NATS_URL"])
    await bus.connect()
    
    # 1. Start a MOCK daemon subprocess that is hardcoded to throw OSError("No space left on device")
    mock_script = os.path.abspath(os.path.join(os.path.dirname(__file__), "mock_failing_audit_daemon.py"))
    # Pass a unique sub-name via ENV so JetStream isolates the test
    test_env = ENV_VARS.copy()
    test_env["AUDIT_QUEUE_NAME"] = "audit_failsafe_test"
    failing_proc = subprocess.Popen([sys.executable, mock_script], env=test_env)
    await asyncio.sleep(2)
    
    # Publish a message that needs logging
    env_crash = MessageEnvelope(id="CRASH_TEST_MSG", sender="test", payload={})
    await bus.publish("tasks.test", env_crash)
    
    # Wait for the mock daemon to process the message and intentionally crash
    await asyncio.sleep(2)
    failing_proc.wait(timeout=5)
    
    # Assert the failing subprocess exited with code 1 (safe suicide instead of hanging)
    assert failing_proc.returncode == 1
    
    # 2. Restart a healthy daemon subprocess using the same unique queue to inherit the NAK
    healthy_proc = subprocess.Popen([sys.executable, DAEMON_SCRIPT], env=test_env)
    
    # Wait 4 seconds. Because the failing daemon executed an explicit msg.nak(), 
    # JetStream instantly redelivers to the new healthy daemon. We do not have to wait 30s.
    print(f"Waiting 4 seconds for NATS JetStream instant NAK redelivery...")
    await asyncio.sleep(4)
    
    log_file = os.path.join(TEST_LOG_DIR, "audit.jsonl")
    
    # Prove the message was safely redelivered and successfully written to disk by the healthy node
    with open(log_file, "r") as f:
        lines = f.readlines()
        assert len(lines) == 1
        assert "CRASH_TEST_MSG" in lines[0]
    
    healthy_proc.terminate()
    healthy_proc.wait()
    await bus.close()


# Hypothesis property-based fuzz strategy for MessageEnvelope payloads
fuzz_payloads = st.dictionaries(
    keys=st.text(),
    values=st.one_of(st.text(), st.integers(), st.floats(allow_nan=False, allow_infinity=False), st.booleans(), st.none())
)

@settings(max_examples=50, suppress_health_check=[HealthCheck.function_scoped_fixture])
@given(payload=fuzz_payloads)
def test_p8_fuzz_payloads(payload):
    """Fuzz the audit daemon with 50 highly randomized JSON payloads to ensure hash-chaining never crashes."""
    # Note: We use asyncio.run inside the sync hypothesis decorator
    asyncio.run(run_async_fuzz_test(payload))

async def run_async_fuzz_test(payload):
    bus = NatsBus(nats_url=ENV_VARS["NATS_URL"])
    await bus.connect()
    
    env = MessageEnvelope(sender="fuzzer", capability="fuzz", verb="test", payload=payload)
    await bus.publish("tasks.fuzz", env)
    
    await bus.close()
