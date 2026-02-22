import pytest
import pytest_asyncio
import asyncio
import os
import sys
import json
import shutil
import subprocess
from unittest.mock import patch

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..', 'src')))
from audit_daemon import AuditDaemon
from verify_audit import AuditVerifier
from nats_bus import NatsBus
from envelope import MessageEnvelope

TEST_NATS_PORT = 4226
TEST_LOG_DIR = "tests/test_logs"

@pytest_asyncio.fixture(autouse=True)
async def isolated_nats():
    """Starts a clean NATS server specifically for Phase 8 testing."""
    if os.path.exists("nats_data_audit"):
        shutil.rmtree("nats_data_audit")
    if os.path.exists(TEST_LOG_DIR):
        shutil.rmtree(TEST_LOG_DIR)
        
    print(f"Starting isolated NATS on {TEST_NATS_PORT}...")
    proc = subprocess.Popen(
        ["nats-server", "-js", "-sd", "nats_data_audit", "-p", str(TEST_NATS_PORT)],
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL
    )
    
    # Let NATS initialize
    await asyncio.sleep(2)
    os.environ["NATS_URL"] = f"nats://localhost:{TEST_NATS_PORT}"

    yield
    
    # Cleanup
    proc.terminate()
    proc.wait()
    if os.path.exists("nats_data_audit"):
        shutil.rmtree("nats_data_audit")
    if os.path.exists(TEST_LOG_DIR):
        shutil.rmtree(TEST_LOG_DIR)


@pytest.mark.asyncio
async def test_p8_1_the_gap_stream_replay():
    """P8-1: Kill the daemon, run tasks, restart it, assert zero logs were missed."""
    bus = NatsBus()
    await bus.connect()
    
    # 1. Start daemon for the first time
    daemon1 = AuditDaemon(log_dir=TEST_LOG_DIR)
    
    # Send MSG 1 while daemon is sleeping (not running loop yet, but it will pull it)
    await bus.js.publish("tasks.worker", b'{"id":"1", "sender":"test", "payload":{}}')
    
    # Manually step the daemon once
    await daemon1.connect()
    def cb1(env, msg):
        asyncio.create_task(daemon1.process_message(env, msg))
    
    sub1 = await daemon1.bus.subscribe("tasks.>", "audit_logger", cb1)
    await asyncio.sleep(1) # Let it processMSG 1
    
    # Assert MSG 1 is logged
    with open(daemon1.log_file, "r") as f:
        lines = f.readlines()
        assert len(lines) == 1
        
    # SILENTLY KILL DAEMON 1
    # DO NOT unsubscribe as this deletes the durable consumer state in NATS!
    await daemon1.bus.close()
    
    # Send MSG 2 and 3 while NO DAEMON IS RUNNING
    await bus.js.publish("tasks.verifier", b'{"id":"2", "sender":"test", "payload":{}}')
    await bus.js.publish("tasks.done", b'{"id":"3", "sender":"test", "payload":{}}')
    await asyncio.sleep(1)
    
    # 2. Restart a completely fresh daemon instance
    daemon2 = AuditDaemon(log_dir=TEST_LOG_DIR)
    await daemon2.connect()
    
    received = []
    async def cb2(env, msg):
        received.append(env)
        await daemon2.process_message(env, msg)
        
    sub2 = await daemon2.bus.subscribe("tasks.>", "audit_logger", cb2)
    await asyncio.sleep(2) # Give it time to replay from JetStream
    
    # Assert MSG 2 and 3 were caught upon restart
    assert len(received) == 2
    
    with open(daemon2.log_file, "r") as f:
        lines = f.readlines()
        assert len(lines) == 3 # 1 from before, 2 replayed
        
    await daemon2.bus.close()
    await bus.close()


@pytest.mark.asyncio
async def test_p8_2_log_tampering_detection():
    """P8-2: Manually modify a character in audit.jsonl and assert verify_audit.py throws error."""
    bus = NatsBus()
    await bus.connect()
    
    daemon = AuditDaemon(log_dir=TEST_LOG_DIR)
    await daemon.connect()
    
    # Generate valid logs
    await bus.js.publish("tasks.test", b'{"id":"A", "sender":"test", "payload":{}}')
    await bus.js.publish("tasks.test", b'{"id":"B", "sender":"test", "payload":{}}')
    
    async def cb(env, msg):
        await daemon.process_message(env, msg)
        
    sub = await daemon.bus.subscribe("tasks.>", "audit_logger", cb)
    await asyncio.sleep(1)
    
    # Verify mathematically that it passes
    verifier = AuditVerifier(log_path=daemon.log_file)
    assert verifier.verify_hash_chain() is True
    
    # TAMPER THE LOG (Change MSG A's payload)
    with open(daemon.log_file, "r") as f:
        lines = f.readlines()
    
    lines[0] = lines[0].replace('"id": "A"', '"id": "HACKED"')
    
    with open(daemon.log_file, "w") as f:
        f.writelines(lines)
        
    # Verify mathematically that it now FAILS
    assert verifier.verify_hash_chain() is False
    
    await sub.unsubscribe()
    await daemon.bus.close()
    await bus.close()


@pytest.mark.asyncio
async def test_p8_3_disk_pressure_safe_crash():
    """P8-3: Simulate an OSError on file write, proving the daemon crashes safely without acking."""
    bus = NatsBus()
    await bus.connect()
    
    daemon = AuditDaemon(log_dir=TEST_LOG_DIR)
    await daemon.connect()
    
    # Mock python's built-in open to throw an OSError exactly on the audit file
    original_open = builtins_open = __builtins__.get('open', open)
    
    def mocked_open(file, mode='r', *args, **kwargs):
        if "audit.jsonl" in str(file) and "a" in mode:
            raise OSError("No space left on device")
        return original_open(file, mode, *args, **kwargs)
        
    # Publish a message that needs logging
    await bus.js.publish("tasks.test", b'{"id":"CRASH", "sender":"test", "payload":{}}')
    
    # We must mock sys.exit because process_message calls sys.exit(1) on OSError
    with patch('builtins.open', side_effect=mocked_open):
        with patch('sys.exit') as mock_exit:
            
            async def cb(env, msg):
                await daemon.process_message(env, msg)
                # Simulate actual crash by dropping the NATS connection immediately 
                # to prevent the test mock from entering a NAK infinite loop
                await daemon.bus.close()
                
            sub = await daemon.bus.subscribe("tasks.>", "audit_logger", cb)
            await asyncio.sleep(1)
            
            # Assert sys.exit was called exactly once before the simulated process died
            mock_exit.assert_called_once_with(1)
            
    # Restart daemon naturally (no mock) and prove the message is still in JetStream (redelivered)
    daemon_rebooted = AuditDaemon(log_dir=TEST_LOG_DIR)
    await daemon_rebooted.connect()
    
    recovered = []
    async def cb2(env, msg):
        recovered.append(env)
        await daemon_rebooted.process_message(env, msg)
        
    sub2 = await daemon_rebooted.bus.subscribe("tasks.>", "audit_logger", cb2)
    
    # Wait just 1 second, msg.nak() should guarantee instant redelivery
    print("\nWaiting 1 second for NATS JetStream explicit NAK redelivery...")
    await asyncio.sleep(1)
    
    assert len(recovered) == 1
    assert recovered[0].id == "CRASH"
    
    await daemon_rebooted.bus.close()
    await bus.close()
