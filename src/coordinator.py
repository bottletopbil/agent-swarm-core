import time
from sqlmodel import select
from database import get_session, Task, TaskStatus
from simple_queue import SimpleQueue

class CoordinatorService:
    def __init__(self):
        self.worker_queue = SimpleQueue("worker_queue")
        self.planner_queue = SimpleQueue("planner_queue")

    def run_once(self):
        """Polls the DB once for pending tasks and pushes them to the queue."""
        with next(get_session()) as session:
            # 1. Handle PENDING tasks
            statement = select(Task).where(Task.status == TaskStatus.PENDING).limit(10)
            pending_tasks = session.exec(statement).all()
            
            for task in pending_tasks:
                task.status = TaskStatus.IN_PROGRESS
                session.add(task)
                session.commit()
                
                if task.requires_planning:
                    print(f"[COORDINATOR] Found Complex Task {task.id}. Pushing to planner_queue.")
                    self.planner_queue.push({"task_id": task.id})
                else:
                    print(f"[COORDINATOR] Found Simple Task {task.id}. Pushing to worker_queue.")
                    self.worker_queue.push({"task_id": task.id})

            # 1.5 Handle LOCKED DAG dependencies
            import json
            locked_stmt = select(Task).where(Task.status == TaskStatus.LOCKED)
            locked_tasks = session.exec(locked_stmt).all()
            for locked in locked_tasks:
                try:
                    depends_list = json.loads(locked.depends_on)
                    if not depends_list:
                        locked.status = TaskStatus.PENDING
                        session.add(locked)
                        session.commit()
                        continue
                        
                    all_done = True
                    any_failed = False
                    results_to_inject = []
                    
                    for dep_id in depends_list:
                        dep_task = session.get(Task, dep_id)
                        if not dep_task:
                            any_failed = True
                            break
                        if dep_task.status == TaskStatus.FAILED:
                            any_failed = True
                            break
                        if dep_task.status != TaskStatus.DONE:
                            all_done = False
                            break
                        
                        clean_dep = dep_task.prompt.split("Specific Task: ")[-1] if "Specific Task: " in dep_task.prompt else dep_task.prompt
                        results_to_inject.append(f"-- Output from precursor '{clean_dep}':\n{dep_task.result}\n")
                        
                    if any_failed:
                        locked.status = TaskStatus.FAILED
                        locked.result = "A prerequisite task failed."
                        session.add(locked)
                        session.commit()
                        print(f"[COORDINATOR] Task {locked.id} FAILED due to failed precursor.")
                    elif all_done:
                        locked.status = TaskStatus.PENDING
                        injection_str = "\n".join(results_to_inject)
                        locked.prompt = f"{locked.prompt}\n\n[Precursor Context provided by Coordinator:]\n{injection_str}"
                        session.add(locked)
                        session.commit()
                        print(f"[COORDINATOR] Task {locked.id} UNLOCKED. Dependencies met.")
                except Exception as e:
                    print(f"[COORDINATOR] Error checking lock: {e}")

            # 2. Check for waiting parent tasks (IN_PROGRESS and requires_planning)
            wait_stmt = select(Task).where(
                Task.status == TaskStatus.IN_PROGRESS,
                Task.requires_planning == True
            )
            waiting_parents = session.exec(wait_stmt).all()
            
            for parent in waiting_parents:
                children_stmt = select(Task).where(Task.parent_id == parent.id)
                children = session.exec(children_stmt).all()
                
                if not children:
                    continue # Planner hasn't created children yet
                    
                all_done = all(c.status == TaskStatus.DONE for c in children)
                any_failed = any(c.status == TaskStatus.FAILED for c in children)
                
                if any_failed:
                    parent.status = TaskStatus.FAILED
                    parent.result = "One or more sub-tasks failed."
                    session.add(parent)
                    session.commit()
                    print(f"[COORDINATOR] Parent Task {parent.id} marked FAILED due to child failure.")
                elif all_done:
                    # Combine all the outputs of the sub-tasks into the parent's result
                    combined_result = "All sub-tasks completed successfully.\n\n=== FINAL COMBINED OUTPUT ===\n\n"
                    for child in children:
                        clean_prompt = child.prompt.replace(f"[Context: Part of a larger goal to '{parent.prompt}']\nSpecific Task: ", "")
                        combined_result += f"-- Sub-Task: {clean_prompt} --\n{child.result}\n\n"
                    
                    parent.status = TaskStatus.DONE
                    parent.result = combined_result.strip()
                    session.add(parent)
                    session.commit()
                    print(f"[COORDINATOR] Parent Task {parent.id} marked DONE (combined all children outputs).")
                
    def loop(self):
        print("Starting Coordinator Service... (Press CTRL+C to stop)")
        try:
            while True:
                self.run_once()
                time.sleep(1) # Simple polling delay
        except KeyboardInterrupt:
            print("\nCoordinator Service stopped.")

if __name__ == "__main__":
    from database import create_db_and_tables
    create_db_and_tables()
    service = CoordinatorService()
    service.loop()
