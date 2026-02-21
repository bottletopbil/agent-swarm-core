import time
from database import get_session, Task, TaskStatus
from simple_queue import SimpleQueue
from llm_client import LLMClient

class WorkerService:
    def __init__(self):
        self.worker_queue = SimpleQueue("worker_queue")
        self.verifier_queue = SimpleQueue("verifier_queue")
        self.llm = LLMClient()

    def process_message(self, msg: dict):
        task_id = msg.get("task_id")
        if not task_id: return
        
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
                
                print(f"[WORKER] Finished Task {task.id}. Pushing to verifier_queue.")
                self.verifier_queue.push({"task_id": task.id})
            except Exception as e:
                print(f"[WORKER] Error: {e}")
                task.status = TaskStatus.FAILED
                task.result = f"Worker Error: {e}"
                session.add(task)
                session.commit()

    def loop(self):
        print("Starting Worker Service... (Press CTRL+C to stop)")
        # If the worker previously crashed, any 'in_progress' messages should be reset
        self.worker_queue.reset_stuck_messages()
        
        try:
            while True:
                payload, msg_id = self.worker_queue.pop()
                if payload and msg_id:
                    self.process_message(payload)
                    self.worker_queue.ack(msg_id)
                else:
                    time.sleep(1) # Poll delay
        except KeyboardInterrupt:
            print("\nWorker Service stopped.")

if __name__ == "__main__":
    from dotenv import load_dotenv
    load_dotenv()
    service = WorkerService()
    service.loop()
