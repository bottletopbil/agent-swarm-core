import asyncio
from database import get_session, Task, TaskStatus
from nats_bus import NatsBus
from envelope import MessageEnvelope
from llm_client import LLMClient

class WorkerService:
    def __init__(self):
        self.bus = NatsBus()
        self.llm = LLMClient()

    def _do_work(self, task_id: str) -> bool:
        if not task_id: return False
        
        with next(get_session()) as session:
            task = session.get(Task, task_id)
            if not task: return
            
            print(f"[WORKER] Picked up Task {task.id} (Prompt: '{task.prompt}')")
            system_prompt = "You are an intelligent and concise Agent Swarm Worker. Perform the requested task."
            try:
                result = self.llm.generate_text(
                    system_prompt=system_prompt, 
                    user_prompt=task.prompt,
                    seed=task.seed,
                    temperature=task.temperature
                )
                task.result = result
                task.status = TaskStatus.VERIFYING
                session.add(task)
                session.commit()
                
                print(f"[WORKER] Finished Task {task.id}. Returning control to async loop.")
                return True
            except Exception as e:
                print(f"[WORKER] Error: {e}")
                task.status = TaskStatus.FAILED
                task.result = f"Worker Error: {e}"
                session.add(task)
                session.commit()
                return False

    async def _message_handler(self, envelope: MessageEnvelope, msg):
        task_id = envelope.payload.get("task_id")
        if task_id:
            success = await asyncio.to_thread(self._do_work, task_id)
            if success:
                print(f"[WORKER] Publishing to tasks.verifier.")
                env = MessageEnvelope(sender="worker", payload={"task_id": task_id})
                await self.bus.publish("tasks.verifier", env)
        await msg.ack()

    async def loop(self):
        print("Starting Worker Service... (Press CTRL+C to stop)")
        await self.bus.connect()
        await self.bus.subscribe("tasks.worker", "workers", self._message_handler)
        
        try:
            while True:
                await asyncio.sleep(1)
        except asyncio.CancelledError:
            print("\nWorker Service stopped.")
        finally:
            await self.bus.close()

if __name__ == "__main__":
    from dotenv import load_dotenv
    load_dotenv()
    service = WorkerService()
    try:
        asyncio.run(service.loop())
    except KeyboardInterrupt:
        pass
