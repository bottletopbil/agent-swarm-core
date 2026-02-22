import asyncio
import os
import sys
import signal
import time

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..', 'src')))
from worker import WorkerService
from database import create_db_and_tables

def mock_generate(*args, **kwargs):
    behavior = os.environ.get("MOCK_BEHAVIOR")
    if behavior == "HARD_CRASH":
        print("[MOCK WORKER] MOCK: SIGKILL BEFORE DB COMMIT!")
        os.kill(os.getpid(), signal.SIGKILL)
    elif behavior == "SLOW_CONSUMER":
        print("[MOCK WORKER] MOCK: SLEEPING 35 SECONDS TO TRIGGER NATS ACKWAIT TIMEOUT")
        time.sleep(35)
    elif behavior == "SLEEP_2":
        time.sleep(2)
    return "[MOCK] Processed via Subprocess Worker"

async def main():
    service = WorkerService()
    import unittest.mock
    with unittest.mock.patch('worker.LLMClient.generate_text', side_effect=mock_generate):
        await service.loop()

if __name__ == '__main__':
    create_db_and_tables()
    asyncio.run(main())
