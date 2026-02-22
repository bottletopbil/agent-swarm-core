import asyncio
import os
import sys
from unittest.mock import patch

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..', 'src')))
from worker import WorkerService
from database import create_db_and_tables

def mock_generate(*args, **kwargs):
    if os.environ.get("CRASH_MIDWAY") == "1":
        print("[MOCK WORKER] Crashing midway to simulate partition!", flush=True)
        sys.exit(1) # simulate partition drop / process crash
    print("[MOCK WORKER] Processing successfully.", flush=True)
    return "Recovered Result!"

async def main():
    service = WorkerService()
    with patch('worker.LLMClient.generate_text', side_effect=mock_generate):
        await service.loop()

if __name__ == '__main__':
    create_db_and_tables()
    asyncio.run(main())
