import pytest
import asyncio
import json
from envelope import MessageEnvelope
from nats_bus import NatsBus

@pytest.mark.asyncio
async def test_nats_publish_subscribe():
    bus = NatsBus()
    await bus.connect()
    
    received_msgs = []
    
    async def cb(env, msg):
        received_msgs.append(env)
        await msg.ack()
        
    # use a unique test subject
    sub = await bus.subscribe("tasks.test_pubsub", "test_pubsub_queue", cb)
    
    # Publish a test message
    test_env = MessageEnvelope(sender="test_agent", payload={"test_data": "success"})
    await bus.publish("tasks.test_pubsub", test_env)
    
    # Wait briefly for NATS to route the message
    await asyncio.sleep(0.5)
    
    assert len(received_msgs) == 1
    assert received_msgs[0].sender == "test_agent"
    assert received_msgs[0].payload["test_data"] == "success"
    
    await sub.unsubscribe()
    await bus.close()

@pytest.mark.asyncio
async def test_nats_poison_pill_red_teaming():
    """
    Simulates a malicious or broken agent injecting malformed payloads into the stream.
    Validates that the consumer survives, handles the errors, terminates the poison pill,
    and continues processing valid tasks.
    """
    bus = NatsBus()
    await bus.connect()
    
    received_envelopes = []
    
    async def cb(env, msg):
        received_envelopes.append(env)
        await msg.ack()
        
    sub = await bus.subscribe("tasks.poison_test", "poison_test_queue", cb)
    
    # 1. Manually publish malformed non-JSON garbage
    malformed_data = b"NOT JSON... { garbage"
    await bus.js.publish("tasks.poison_test", malformed_data)
    
    # 2. Manually publish syntactically correct JSON, but missing Envelope Pydantic required fields
    missing_fields_data = b'{"hello": "world"}'
    await bus.js.publish("tasks.poison_test", missing_fields_data)

    # 3. Publish a valid message to prove the worker didn't crash and is still processing
    valid_env = MessageEnvelope(sender="survivor_agent", payload={"valid": "true"})
    await bus.publish("tasks.poison_test", valid_env)
    
    # Wait for processing
    await asyncio.sleep(1.0)
    
    # The callback should only have been able to parse the valid envelope.
    assert len(received_envelopes) == 1
    assert received_envelopes[0].sender == "survivor_agent"
    assert received_envelopes[0].payload["valid"] == "true"
    
    await sub.unsubscribe()
    await bus.close()
