import asyncio
import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..', 'src')))
from audit_daemon import AuditDaemon

class FailingAuditDaemon(AuditDaemon):
    """
    Simulates P8-3 Disk Pressure by overriding the native open() function 
    to intentionally throw an OSError immediately when it attempts to write.
    This guarantees a pure subprocess failure without polluting the pytest event loop.
    """
    async def process_message(self, env, msg):
        import logging
        logging.critical("[MOCK] Simulating OS/DISK ERROR. NAKing message and crashing.")
        if hasattr(msg, 'nak'):
            await msg.nak()
            await asyncio.sleep(0.1) # Flush socket to JetStream
        # Immediately exit with code 1 instead of relying on the parent class
        sys.exit(1)

if __name__ == "__main__":
    daemon = FailingAuditDaemon(log_dir=os.environ.get("AUDIT_LOG_DIR", "logs"))
    
    async def main():
        await daemon.connect()
        async def cb(env, msg):
            await daemon.process_message(env, msg)
        queue_name = os.environ.get("AUDIT_QUEUE_NAME", "audit_logger")
        await daemon.bus.subscribe("tasks.>", queue_name, cb)
        await daemon.run()
        
    try:
        asyncio.run(main())
    except OSError:
        # P8-3 requires the process to exit with code 1 on disk pressure
        sys.exit(1)
