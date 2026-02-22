import asyncio
from database import get_session, Task, TaskStatus
from nats_bus import NatsBus
from envelope import MessageEnvelope
from llm_client import LLMClient

class VerifierService:
    def __init__(self):
        self.bus = NatsBus()
        self.llm = LLMClient()

    def _do_work(self, task_id: str):
        if not task_id: return
        
        with next(get_session()) as session:
            task = session.get(Task, task_id)
            if not task: return
            
            print(f"[VERIFIER] Picked up Task {task.id} for Review.")
            try:
                passed, notes = self.llm.verify_result(task.prompt, task.result)
                task.verifier_notes = notes
                
                if passed:
                    task.status = TaskStatus.DONE
                    print(f"[VERIFIER] Task {task.id} marked DONE.")
                else:
                    task.status = TaskStatus.FAILED
                    task.result = None # Clear bad result
                    print(f"[VERIFIER] Task {task.id} marked FAILED. Notes: {notes}")
                    
                session.add(task)
                session.commit()
            except Exception as e:
                print(f"[VERIFIER] Error: {e}")
                task.status = TaskStatus.FAILED
                task.verifier_notes = f"Verifier Error: {e}"
                session.add(task)
                session.commit()

    async def _message_handler(self, envelope: MessageEnvelope, msg):
        task_id = envelope.payload.get("task_id")
        if task_id:
            await asyncio.to_thread(self._do_work, task_id)
        await msg.ack()

    async def loop(self):
        print("Starting Verifier Service... (Press CTRL+C to stop)")
        await self.bus.connect()
        await self.bus.subscribe("tasks.verifier", "verifiers", self._message_handler)

        try:
            while True:
                await asyncio.sleep(1)
        except asyncio.CancelledError:
            print("\nVerifier Service stopped.")
        finally:
            await self.bus.close()

if __name__ == "__main__":
    from dotenv import load_dotenv
    load_dotenv()
    service = VerifierService()
    try:
        asyncio.run(service.loop())
    except KeyboardInterrupt:
        pass
