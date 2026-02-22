import asyncio
import json
import logging
import os
import signal
import sys
import hashlib
from datetime import datetime

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..', 'src')))
from nats_bus import NatsBus
from envelope import MessageEnvelope

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(message)s")

class AuditDaemon:
    def __init__(self, log_dir="logs"):
        self.bus = NatsBus()
        self.log_dir = log_dir
        os.makedirs(self.log_dir, exist_ok=True)
        self.log_file = os.path.join(self.log_dir, "audit.jsonl")
        self.running = True

    async def connect(self):
        await self.bus.connect()
        logging.info("[AUDIT] Connected to NATS.")

    def _get_last_hash(self) -> str:
        """Reads the last line of the audit log to retrieve the previous hash. Returns '0'*64 if file is empty."""
        if not os.path.exists(self.log_file) or os.path.getsize(self.log_file) == 0:
            return "0" * 64
        
        try:
            with open(self.log_file, "rb") as f:
                f.seek(-2, os.SEEK_END)
                while f.tell() > 0:
                    f.seek(-1, os.SEEK_CUR)
                    if f.read(1) == b'\n':
                        break
                    f.seek(-1, os.SEEK_CUR)
                last_line = f.readline().decode()
            
            last_entry = json.loads(last_line)
            return last_entry.get("hash", "0" * 64)
        except Exception: 
            with open(self.log_file, "r") as f:
                lines = f.readlines()
                if lines:
                    last_entry = json.loads(lines[-1])
                    return last_entry.get("hash", "0" * 64)
                return "0" * 64

    async def process_message(self, env: MessageEnvelope, msg):
        try:
            prev_hash = self._get_last_hash()
            
            # Serialize the envelope payload
            payload_str = json.dumps(env.model_dump(), sort_keys=True)
            
            # Cryptographically chain the new line to the old line
            sha = hashlib.sha256()
            sha.update((prev_hash + payload_str).encode('utf-8'))
            current_hash = sha.hexdigest()

            log_entry = {
                "prev_hash": prev_hash,
                "envelope": env.model_dump(),
                "hash": current_hash,
                "logged_at": datetime.utcnow().isoformat()
            }

            # Pre-flight check before write (to catch P8-3 disk pressure before NATS ack)
            with open(self.log_file, "a") as f:
                f.write(json.dumps(log_entry, sort_keys=True) + "\n")
                f.flush() # Force OS to write to disk
                os.fsync(f.fileno()) # Guarantee physical persistence
            
            # If disk write succeeds, ACK the reliable JetStream message
            await msg.ack()
            logging.info(f"[AUDIT] Logged: {env.id} via {env.sender} (Hash: {current_hash[:8]}...)")
            
        except OSError as e:
            # P8-3 Disk Pressure: Intentionally NAK so NATS instantly redelivers, then crash safely
            logging.critical(f"[AUDIT] FATAL OS/DISK ERROR. CRASHING TO PREVENT LOG LOSS: {e}")
            if hasattr(msg, 'nak'):
                await msg.nak()
            self.running = False
            sys.exit(1)
        except Exception as e:
            logging.error(f"[AUDIT] Unknown error handling message: {e}")
            await msg.term() # Terminal error, data is bad, discard

    async def run(self):
        await self.connect()
        # Durable JetStream Pull subscription. If we crash, NATS remembers our sequence.
        self.sub = await self.bus.subscribe("tasks.>", "audit_logger", self.process_message)
        
        logging.info("[AUDIT] Daemon running. Press CTRL+C to stop.")
        while self.running:
            await asyncio.sleep(1)
        
        await self.bus.close()

async def main():
    daemon = AuditDaemon()
    
    def shutdown(sig, frame):
        logging.info("[AUDIT] Shutting down gracefully...")
        daemon.running = False

    signal.signal(signal.SIGINT, shutdown)
    signal.signal(signal.SIGTERM, shutdown)
    
    await daemon.run()

if __name__ == "__main__":
    asyncio.run(main())
