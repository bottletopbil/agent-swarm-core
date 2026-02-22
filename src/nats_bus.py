import json
import asyncio
from nats.aio.client import Client as NATS
from nats.js.api import StreamConfig, RetentionPolicy, StorageType
from nats.js.errors import NotFoundError
from envelope import MessageEnvelope

class NatsBus:
    def __init__(self, nats_url="nats://localhost:4222"):
        self.nats_url = nats_url
        self.nc = NATS()
        self.js = None

    async def connect(self):
        """Connect to NATS and initialize JetStream."""
        print(f"Connecting to NATS at {self.nats_url}...")
        await self.nc.connect(self.nats_url)
        self.js = self.nc.jetstream()
        print("Connected to JetStream.")
        
        # Ensure the streams exist
        await self._ensure_stream("tasks", ["tasks.>"])

    async def _ensure_stream(self, stream_name: str, subjects: list[str]):
        try:
            stream_info = await self.js.stream_info(stream_name)
            print(f"Stream '{stream_name}' exists with subjects: {stream_info.config.subjects}")
        except NotFoundError:
            print(f"Stream '{stream_name}' not found. Creating...")
            # Use RetentionPolicy.LIMITS (default) to keep history intact for replayability
            await self.js.add_stream(name=stream_name, subjects=subjects, storage=StorageType.FILE, retention=RetentionPolicy.LIMITS)
            print(f"Stream '{stream_name}' created.")

    async def publish(self, subject: str, message: MessageEnvelope):
        """Publish an envelope to the bus."""
        payload_bytes = json.dumps(message.dict_for_bus()).encode('utf-8')
        ack = await self.js.publish(subject, payload_bytes)
        print(f"[NATS] Published {message.id} to {subject} (seq: {ack.seq})")
        return ack

    async def subscribe(self, subject: str, queue: str, callback):
        """Subscribe to a JetStream subject using queue groups to distribute load."""
        print(f"Subscribing to {subject} on queue group '{queue}'")
        
        async def message_handler(msg):
            try:
                data = json.loads(msg.data.decode('utf-8'))
                envelope = MessageEnvelope(**data)
                
                # Execute callback (await if async)
                if asyncio.iscoroutinefunction(callback):
                    await callback(envelope, msg)
                else:
                    callback(envelope, msg)
            except Exception as e:
                print(f"[NATS Error] Failed to process message on {subject}: {e}")
                # Might want to NAK the message later, wait for it to resend
                await msg.nak()

        # Using Push subscribe for now, standard for basic worker queues
        sub = await self.js.subscribe(
            subject=subject,
            queue=queue,
            cb=message_handler,
            durable=queue # durable consumer name
        )
        return sub

    async def close(self):
        """Close connection to NATS."""
        if not self.nc.is_closed:
            await self.nc.close()
            print("Disconnected from NATS.")
