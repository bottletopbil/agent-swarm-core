from database import get_session, Task, TaskStatus

with next(get_session()) as session:
    task = Task(prompt="Write a 3-chapter book about a space dog", requires_planning=True)
    session.add(task)
    session.commit()
    print("Inserted task:", task.id)
