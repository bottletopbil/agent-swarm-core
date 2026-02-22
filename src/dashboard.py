from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from contextlib import asynccontextmanager
from sqlmodel import select
from database import get_session, Task
from nats_bus import NatsBus
from envelope import MessageEnvelope
import os
import asyncio

bus = NatsBus()
recent_events = []

async def event_handler(env: MessageEnvelope, msg):
    recent_events.insert(0, {
        "id": env.id,
        "sender": env.sender,
        "task_id": env.payload.get("task_id", "unknown"),
        "timestamp": env.timestamp,
        "subject": msg.subject
    })
    # Keep only last 100
    if len(recent_events) > 100:
        recent_events.pop()
    await msg.ack()

@asynccontextmanager
async def lifespan(app: FastAPI):
    await bus.connect()
    # Subscribe to all tasks to monitor
    sub = await bus.subscribe("tasks.>", "dashboard_monitor", event_handler)
    yield
    await bus.close()

app = FastAPI(title="CAN Swarm Core - Dashboard", lifespan=lifespan)

# Create templates directory if it doesn't exist
os.makedirs("templates", exist_ok=True)

# Generate a simple inline template for the dashboard
html_content = """
<!DOCTYPE html>
<html>
<head>
    <title>CAN Swarm Core - Live Dashboard</title>
    <style>
        body { font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Helvetica, Arial, sans-serif; background-color: #f5f5f5; color: #333; margin: 0; padding: 20px; }
        h1 { color: #2c3e50; text-align: center; }
        .board { display: flex; gap: 20px; overflow-x: auto; padding-bottom: 20px; }
        .column { flex: 1; min-width: 250px; background: white; border-radius: 8px; padding: 15px; box-shadow: 0 2px 4px rgba(0,0,0,0.1); }
        .column h2 { text-align: center; font-size: 1.2em; border-bottom: 2px solid #ecf0f1; padding-bottom: 10px; margin-top: 0; }
        
        .c-pending h2 { color: #7f8c8d; border-color: #7f8c8d; }
        .c-locked h2 { color: #8e44ad; border-color: #8e44ad; }
        .c-inprogress h2 { color: #3498db; border-color: #3498db; }
        .c-verifying h2 { color: #f39c12; border-color: #f39c12; }
        .c-done h2 { color: #2ecc71; border-color: #2ecc71; }
        .c-failed h2 { color: #e74c3c; border-color: #e74c3c; }
        .c-final h2 { color: #16a085; border-color: #16a085; background-color: #e8f8f5; border-radius: 4px; padding: 10px 0;}

        .task-card { background: white; border-radius: 6px; padding: 15px; margin-bottom: 15px; box-shadow: 0 2px 4px rgba(0,0,0,0.05); border-left: 5px solid #bdc3c7; }
        .task-card.pending { border-left-color: #f39c12; }
        .task-card.locked { border-left-color: #8e44ad; }
        .task-card.in-progress { border-left-color: #3498db; }
        .task-card.verifying { border-left-color: #9b59b6; }
        .task-card.done { border-left-color: #2ecc71; }
        .task-card.failed { border-left-color: #e74c3c; }
        
        .task-id { font-size: 0.7em; color: #aaa; font-family: monospace; word-break: break-all; margin-bottom: 5px; }
        .task-prompt { font-weight: bold; margin-bottom: 10px; font-size: 0.9em; }
        .task-detail { font-size: 0.8em; color: #555; background: #f0f3f4; padding: 6px; border-radius: 4px; margin-top: 5px; white-space: pre-wrap; word-wrap: break-word;}
        .label { font-weight: bold; color: #333; }
        
        .controls { text-align: center; margin-bottom: 20px; display: flex; justify-content: center; align-items: center; gap: 10px; }
        button { background-color: #3498db; color: white; border: none; padding: 10px 20px; border-radius: 5px; cursor: pointer; font-size: 1em; }
        button:hover { background-color: #2980b9; }
        input[type="text"] { padding: 10px; width: 300px; border-radius: 5px; border: 1px solid #ccc; font-size: 1em; }
        label { font-size: 0.9em; font-weight: bold; color: #555; cursor: pointer; display: flex; align-items: center; gap: 5px; }
    </style>
</head>
<body>
    <h1>🐝 CAN Swarm Core - Live Dashboard</h1>
    
    <div class="controls">
        <input type="text" id="newPrompt" placeholder="Enter a new task prompt...">
        <label>
            <input type="checkbox" id="requiresPlanning"> 
            Complex Task (Use Planner)
        </label>
        <button onclick="submitTask()">Add Task</button>
    </div>

    <div style="margin-bottom: 30px; background: white; padding: 20px; border-radius: 8px; box-shadow: 0 2px 4px rgba(0,0,0,0.1);">
        <h2>📡 Live NATS Event Bus</h2>
        <div id="event-log" style="height: 200px; overflow-y: auto; background: #2c3e50; color: #ecf0f1; padding: 10px; border-radius: 5px; font-family: monospace; font-size: 0.9em; box-shadow: inset 0 2px 5px rgba(0,0,0,0.5);">
            <!-- JS populated -->
        </div>
    </div>

    <div class="board" id="board">
        <!-- populated by JS -->
    </div>

    <script>
        async function fetchTasks() {
            try {
                const response = await fetch('/api/tasks');
                const tasks = await response.json();
                renderBoard(tasks);
            } catch (error) {
                console.error("Error fetching tasks:", error);
            }
        }

        async function fetchEvents() {
            try {
                const res = await fetch('/api/events');
                const evts = await res.json();
                let logHtml = '';
                evts.forEach(e => {
                    const date = new Date(e.timestamp * 1000).toLocaleTimeString();
                    logHtml += `<div style="padding: 4px; border-bottom: 1px solid #34495e;">
                        <span style="color:#7f8c8d">[${date}]</span> 
                        <strong style="color:#e67e22; width: 120px; display:inline-block">${e.subject}</strong> 
                        <span style="color:#bdc3c7">| Sender:</span> <span style="color:#3498db; width: 100px; display:inline-block">${e.sender}</span> 
                        <span style="color:#bdc3c7">| Task:</span> <span style="color:#2ecc71">${e.task_id}</span> 
                        <span style="color:#bdc3c7">| EnvID:</span> <span style="color:#95a5a6">${e.id.substring(0,8)}</span>
                    </div>`;
                });
                document.getElementById('event-log').innerHTML = logHtml;
            } catch (e) {
                console.error("Error fetching events:", e);
            }
        }

        async function submitTask() {
            const promptInput = document.getElementById('newPrompt');
            const plannerCheck = document.getElementById('requiresPlanning');
            const prompt = promptInput.value.trim();
            if (!prompt) return;

            try {
                await fetch('/api/tasks', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ 
                        prompt: prompt,
                        requires_planning: plannerCheck.checked
                    })
                });
                promptInput.value = '';
                fetchTasks(); // immediate refresh
            } catch (error) {
                console.error("Error submitting task:", error);
            }
        }

        function createCard(task) {
            let detailsHtml = '';
            
            // Highlight complex/sub tasks visually
            const taskType = task.requires_planning ? '🤖 [COMPLEX PARENT]' : 
                            (task.parent_id ? '↳ [SUB-TASK]' : '');
            
            if (taskType) {
                detailsHtml += `<div class="task-detail" style="background:#fff3cd; color:#856404; font-weight:bold;">${taskType}</div>`;
            }
            
            if (task.result) {
                detailsHtml += `<div class="task-detail"><span class="label">Result:</span><br>${task.result}</div>`;
            }
            if (task.verifier_notes) {
                detailsHtml += `<div class="task-detail"><span class="label">Notes:</span><br>${task.verifier_notes}</div>`;
            }

            return `
                <div class="task-card ${task.status.toLowerCase().replace(' ', '-')}">
                    <div class="task-id">${task.id}</div>
                    <div class="task-prompt">${task.prompt}</div>
                    ${detailsHtml}
                </div>
            `;
        }

        function renderBoard(tasks) {
            const columns = {
                'Pending': [],
                'Locked': [],
                'In Progress': [],
                'Verifying': [],
                'Done': [],
                'Failed': [],
                'Final Output': []
            };

            tasks.forEach(task => {
                if (task.status === 'Done' && !task.parent_id) {
                    columns['Final Output'].push(task);
                } else if (columns[task.status]) {
                    columns[task.status].push(task);
                }
            });

            const boardHtml = `
                <div class="column c-pending"><h2>Pending (${columns['Pending'].length})</h2>${columns['Pending'].map(createCard).join('')}</div>
                <div class="column c-locked"><h2>Locked (${columns['Locked'].length})</h2>${columns['Locked'].map(createCard).join('')}</div>
                <div class="column c-inprogress"><h2>In Progress (${columns['In Progress'].length})</h2>${columns['In Progress'].map(createCard).join('')}</div>
                <div class="column c-verifying"><h2>Verifying (${columns['Verifying'].length})</h2>${columns['Verifying'].map(createCard).join('')}</div>
                <div class="column c-done"><h2>Sub-Tasks Done (${columns['Done'].length})</h2>${columns['Done'].map(createCard).join('')}</div>
                <div class="column c-failed"><h2>Failed (${columns['Failed'].length})</h2>${columns['Failed'].map(createCard).join('')}</div>
                <div class="column c-final"><h2>Final Output (${columns['Final Output'].length})</h2>${columns['Final Output'].map(createCard).join('')}</div>
            `;
            
            document.getElementById('board').innerHTML = boardHtml;
        }

        // Poll every 1 second
        setInterval(() => {
            fetchTasks();
            fetchEvents();
        }, 1000);
        
        // Initial fetch
        fetchTasks();
        fetchEvents();
    </script>
</body>
</html>
"""

# Write the template file dynamically
with open("templates/index.html", "w") as f:
    f.write(html_content)

templates = Jinja2Templates(directory="templates")

@app.get("/", response_class=HTMLResponse)
async def read_root(request: Request):
    return templates.TemplateResponse("index.html", {"request": request})

@app.get("/api/tasks")
def get_tasks():
    with next(get_session()) as session:
        tasks = session.exec(select(Task)).all()
        return tasks

@app.get("/api/events")
def get_events():
    return recent_events

from pydantic import BaseModel
class NewTask(BaseModel):
    prompt: str
    requires_planning: bool = False

@app.post("/api/tasks")
def create_task(new_task: NewTask):
    with next(get_session()) as session:
        task = Task(prompt=new_task.prompt, requires_planning=new_task.requires_planning)
        session.add(task)
        session.commit()
        session.refresh(task)
        return task

if __name__ == "__main__":
    import uvicorn
    # Make sure DB exists
    from database import create_db_and_tables
    create_db_and_tables()
    print("Starting Dashboard on http://localhost:8000")
    uvicorn.run(app, host="0.0.0.0", port=8000)
