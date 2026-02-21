import time
from database import get_session, Task, TaskStatus
from simple_queue import SimpleQueue
from llm_client import LLMClient

class VerifierService:
    def __init__(self):
        self.verifier_queue = SimpleQueue("verifier_queue")
        self.llm = LLMClient()

    def process_message(self, msg: dict):
        task_id = msg.get("task_id")
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

    def loop(self):
        print("Starting Verifier Service... (Press CTRL+C to stop)")
        # If the verifier previously crashed, any 'in_progress' messages should be reset
        self.verifier_queue.reset_stuck_messages()
        
        try:
            while True:
                payload, msg_id = self.verifier_queue.pop()
                if payload and msg_id:
                    self.process_message(payload)
                    self.verifier_queue.ack(msg_id)
                else:
                    time.sleep(1) # Poll delay
        except KeyboardInterrupt:
            print("\nVerifier Service stopped.")

if __name__ == "__main__":
    from dotenv import load_dotenv
    load_dotenv()
    service = VerifierService()
    service.loop()
