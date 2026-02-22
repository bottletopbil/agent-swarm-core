import asyncio
import json
from nats.aio.client import Client as NATS

async def main():
    nc = NATS()
    await nc.connect("nats://localhost:4222")
    js = nc.jetstream()
    
    print("Replaying NATS Event Bus History:")
    try:
        # Create a pull subscription to read from the start of the stream
        sub = await js.pull_subscribe("tasks.>", "replay_consumer")
        msgs = await sub.fetch(100, timeout=2)
        for i, msg in enumerate(msgs):
            data = json.loads(msg.data.decode())
            sender = data.get("sender", "unknown")
            payload = data.get("payload", {})
            task_id = payload.get("task_id", "unknown")
            print(f"  [{i+1}] {msg.subject:<15} | Sender: {sender:<11} | Task: {task_id}")
            await msg.ack()
    except Exception as e:
        print(f"No more messages or timeout: {e}")
    finally:
        await nc.close()

if __name__ == '__main__':
    asyncio.run(main())
