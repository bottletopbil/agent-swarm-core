from typing import Optional, List
from llm_client import LLMClient
from database import Task, TaskStatus, get_session, create_db_and_tables
from sqlmodel import select

class Worker:
    def __init__(self):
        self.llm = LLMClient()

    def execute(self, task: Task) -> str:
        """
        Executes a task using the LLM.
        """
        print(f"[WORKER] Asking LLM: '{task.prompt}' (Seed: {task.seed})...")
        system_prompt = "You are an intelligent and concise Agent Swarm Worker. Perform the requested task."
        return self.llm.generate_text(
            system_prompt=system_prompt, 
            user_prompt=task.prompt,
            seed=task.seed,
            temperature=task.temperature
        )


class Verifier:
    def __init__(self):
        self.llm = LLMClient()

    def verify(self, task: Task, result: str) -> tuple[bool, str]:
        """
        Verifies a task using the LLM.
        """
        print(f"[VERIFIER] Reviewing LLM result...")
        return self.llm.verify_result(task.prompt, result)


class Coordinator:
    def __init__(self):
        # We don't need a local self.tasks list because truth lives in the DB
        self.worker = Worker()
        self.verifier = Verifier()

    def add_task(self, prompt: str) -> Task:
        task = Task(prompt=prompt)
        with next(get_session()) as session:
            session.add(task)
            session.commit()
            session.refresh(task)
        print(f"[COORDINATOR] Added Task {task.id}: '{task.prompt}'")
        return task

    def _process_task(self, session, task: Task):
        if task.status == TaskStatus.PENDING:
            task.status = TaskStatus.IN_PROGRESS
            session.add(task)
            session.commit()
            
            # 1. Assign to Worker
            print(f"[COORDINATOR] Assigning Task {task.id} to Worker...")
            result = self.worker.execute(task)
            
            task.status = TaskStatus.VERIFYING
            session.add(task)
            session.commit()
            
            # 2. Assign to Verifier
            print(f"[COORDINATOR] Assigning Task {task.id} to Verifier...")
            passed, notes = self.verifier.verify(task, result)
            task.verifier_notes = notes
            
            # 3. Handle Verdict
            if passed:
                task.status = TaskStatus.DONE
                task.result = result
                print(f"[COORDINATOR] Task {task.id} marked DONE.")
            else:
                task.status = TaskStatus.FAILED
                task.result = None # Clear result on failure
                print(f"[COORDINATOR] Task {task.id} marked FAILED. Notes: {notes}")
            
            session.add(task)
            session.commit()

    def run_until_complete(self):
        """
        Simple loop that reads from database and processes until none are active.
        """
        print("\n[COORDINATOR] Starting run loop...")
        while True:
            with next(get_session()) as session:
                statement = select(Task).where(
                    Task.status.in_([TaskStatus.PENDING, TaskStatus.IN_PROGRESS, TaskStatus.VERIFYING])
                )
                active_tasks = session.exec(statement).all()
                
                if not active_tasks:
                    break
                    
                for task in active_tasks:
                    self._process_task(session, task)
        print("[COORDINATOR] Run loop complete.\n")


# Visual Walkthrough
if __name__ == "__main__":
    from dotenv import load_dotenv
    load_dotenv() # Load variables from .env file

    import os
    if not os.environ.get("OPENAI_API_KEY"):
        print("ERROR: OPENAI_API_KEY environment variable not found.")
        print("Please create an .env file with OPENAI_API_KEY=sk-your-key")
        exit(1)

    print("=" * 50)
    print("CAN Swarm Core - Phase 3 (SQLite Persistent State)")
    print("=" * 50)
    
    # Initialize the database file
    create_db_and_tables()
    
    coord = Coordinator()
    
    print("\n--- Testing Happy Path ---")
    coord.add_task("Write a poem about the ocean in two lines.")
    coord.run_until_complete()
    
    # We won't test sabotage directly here because the LLM is smart and will likely pass
    # but the automated tests will mock the LLM for sabotage.
