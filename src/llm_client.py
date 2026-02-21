import os
import json
from openai import OpenAI
from pydantic import BaseModel

class LLMClient:
    def __init__(self):
        # We assume OPENAI_API_KEY is available in the environment
        self.client = OpenAI()

    def generate_text(self, system_prompt: str, user_prompt: str, seed: int = None, temperature: float = 0.7) -> str:
        """
        Calls the LLM and returns the resulting string.
        Passing a seed and a temperature of 0 ensures near-perfect reproducibility.
        """
        response = self.client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt}
            ],
            temperature=temperature,
            seed=seed
        )
        return response.choices[0].message.content

    def verify_result(self, prompt: str, result: str) -> tuple[bool, str]:
        """
        Calls the LLM and asks it to verify if the result satisfies the prompt.
        Expects a JSON response like {"passed": true, "notes": "Looks good."}
        """
        system_prompt = (
            "You are a pragmatic Verifier agent. Your job is to analyze if the Worker's Result "
            "successfully completes the core objective of the original Prompt. "
            "Focus on whether the main goals were achieved. Do NOT be overly pedantic about minor stylistic choices, "
            "formatting, or subjective preferences. If the required work is done, pass it.\n"
            "You must respond in pure JSON with exactly this schema:\n"
            '{"passed": true/false, "notes": "Your reasoning here."}'
        )
        user_prompt = f"Original Prompt: {prompt}\n\nWorker's Result: {result}"
        
        response = self.client.chat.completions.create(
            model="gpt-4o-mini",
            response_format={ "type": "json_object" },
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt}
            ],
            temperature=0.0 # Deterministic as possible for verification
        )
        
        try:
            content = response.choices[0].message.content
            parsed = json.loads(content)
            return parsed.get("passed", False), parsed.get("notes", "No notes provided.")
        except Exception as e:
            return False, f"Failed to parse LLM verification output: {e}"

    def plan_task(self, prompt: str, seed: int = None, temperature: float = 0.7) -> list[dict]:
        """
        Calls the LLM to break a complex prompt into actionable sub-tasks.
        Expects a JSON response with {"sub_tasks": [{"id": "...", "prompt": "...", "depends_on": ["..."]}]}
        """
        system_prompt = (
            "You are a master Planner Agent. Break the requested complex task down into an ordered series "
            "of smaller, distinct sub-tasks that can be executed independently by workers. "
            "Break the task down into as many granular sub-tasks as needed to maximize the accuracy and focus of each individual worker agent. "
            "Do not arbitrarily limit the number of tasks.\n"
            "You must define the dependencies between these tasks as a Directed Acyclic Graph (DAG).\n"
            "If a task does not depend on any other tasks, its 'depends_on' array should be empty [].\n"
            "If a task requires the output of another task, list that task's 'id' in its 'depends_on' array.\n\n"
            "You MUST respond in valid JSON matching this exact schema:\n"
            "{\n"
            "  \"sub_tasks\": [\n"
            "    {\"id\": \"task_1\", \"prompt\": \"Write chapter 1\", \"depends_on\": []},\n"
            "    {\"id\": \"task_2\", \"prompt\": \"Write chapter 2\", \"depends_on\": []},\n"
            "    {\"id\": \"task_3\", \"prompt\": \"Edit all chapters\", \"depends_on\": [\"task_1\", \"task_2\"]}\n"
            "  ]\n"
            "}"
        )
        
        try:
            response = self.client.chat.completions.create(
                model="gpt-4o-mini",
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": prompt}
                ],
                temperature=temperature,
                seed=seed,
                response_format={"type": "json_object"}
            )
            content = response.choices[0].message.content
            parsed = json.loads(content)
            return parsed.get("sub_tasks", [])
        except Exception as e:
            print(f"[LLM_CLIENT] Planner Error: {e}")
            # If it fails, fallback to doing the whole thing as one task
            return [{"id": "fallback_1", "prompt": prompt, "depends_on": []}]
