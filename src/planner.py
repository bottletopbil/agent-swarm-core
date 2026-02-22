import asyncio
from database import get_session, Task, TaskStatus
from nats_bus import NatsBus
from envelope import MessageEnvelope
from llm_client import LLMClient

class PlannerService:
    def __init__(self):
        self.bus = NatsBus()
        self.llm = LLMClient()

    def _do_work(self, task_id: str):
        if not task_id: return
        
        with next(get_session()) as session:
            task = session.get(Task, task_id)
            if not task: return
            
            print(f"[\033[95mPLANNER\033[0m] Picked up Task {task.id} for Planning: '{task.prompt}'")
            try:
                # 1. Ask LLM to break down the task
                dag_objects = self.llm.plan_task(
                    prompt=task.prompt,
                    seed=task.seed,
                    temperature=task.temperature
                )
                
                print(f"[\033[95mPLANNER\033[0m] Broke task into {len(dag_objects)} DAG sub-tasks.")
                
                # 2. Map LLM strings to real DB UUIDs so dependencies link correctly
                import uuid
                import json
                id_map = {}
                for obj in dag_objects:
                    llm_id = obj.get("id", str(uuid.uuid4())) # fallback if LLM omitted it
                    id_map[llm_id] = str(uuid.uuid4())
                
                # 3. Create the child Tasks in the database with parent_id = task.id
                for obj in dag_objects:
                    llm_id = obj.get("id")
                    sub_prompt = obj.get("prompt", "Task")
                    depends_list = obj.get("depends_on", [])
                    
                    real_id = id_map.get(llm_id)
                    real_depends = [id_map[dep] for dep in depends_list if dep in id_map]
                    
                    status = TaskStatus.PENDING if not real_depends else TaskStatus.LOCKED
                    
                    child_task = Task(
                        id=real_id,
                        prompt=f"[Context: Part of a larger goal to '{task.prompt}']\nSpecific Task: {sub_prompt}",
                        parent_id=task.id,
                        requires_planning=False,
                        status=status,
                        depends_on=json.dumps(real_depends)
                    )
                    session.add(child_task)
                
                # 4. Mark the parent task as currently IN_PROGRESS (waiting for children)
                task.status = TaskStatus.IN_PROGRESS
                task.result = f"Planned into {len(dag_objects)} DAG sub-tasks."
                
                session.add(task)
                session.commit()
                
            except Exception as e:
                print(f"[\033[95mPLANNER\033[0m] Error: {e}")
                task.status = TaskStatus.FAILED
                task.result = f"Planner Error: {e}"
                session.add(task)
                session.commit()

    async def _message_handler(self, envelope: MessageEnvelope, msg):
        task_id = envelope.payload.get("task_id")
        if task_id:
            await asyncio.to_thread(self._do_work, task_id)
        await msg.ack()

    async def loop(self):
        print("Starting Planner Service... (Press CTRL+C to stop)")
        await self.bus.connect()
        await self.bus.subscribe("tasks.planner", "planners", self._message_handler)
        
        try:
            while True:
                await asyncio.sleep(1)
        except asyncio.CancelledError:
            print("\nPlanner Service stopped.")
        finally:
            await self.bus.close()

if __name__ == "__main__":
    from dotenv import load_dotenv
    load_dotenv()
    service = PlannerService()
    try:
        asyncio.run(service.loop())
    except KeyboardInterrupt:
        pass
