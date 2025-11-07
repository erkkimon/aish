#!/usr/bin/env python3
import sys
import os
import json
import re
import requests
import subprocess
from datetime import datetime
import yaml
from rich.console import Console
from rich.panel import Panel
from rich.syntax import Syntax
from rich.text import Text

# --- Configuration Loader ---
CONFIG_PATH = "config.yaml"
DEFAULT_CONFIG = """
# Configuration for the aish agent.
model: Devstral-Small-2505-abliterated.i1-Q2_K_S
endpoint_url: http://localhost:11435/v1/chat/completions
# api_key: not-needed # Uncomment if you use a provider that requires an api key
"""

def load_config():
    """Loads configuration from config.yaml, creating it if it doesn't exist."""
    if not os.path.exists(CONFIG_PATH):
        print(f"Configuration file not found. Creating default {CONFIG_PATH}")
        with open(CONFIG_PATH, 'w') as f:
            f.write(DEFAULT_CONFIG)
        with open(CONFIG_PATH, 'r') as f:
            return yaml.safe_load(f)
    try:
        with open(CONFIG_PATH, 'r') as f:
            return yaml.safe_load(f)
    except (yaml.YAMLError, IOError) as e:
        print(f"Error reading {CONFIG_PATH}: {e}. Using default settings.", file=sys.stderr)
        with open(CONFIG_PATH, 'r') as f:
            return yaml.safe_load(f)

CONFIG = load_config()

# --- Colors and Emojis ---
C_BLUE = "\033[94m"
C_GREEN = "\033[92m"
C_YELLOW = "\033[93m"
C_RED = "\033[91m"
C_END = "\033[0m"
C_BOLD = "\033[1m"

EMOJI_AGENT = "🤖"
EMOJI_COMMAND = "🛠️"
EMOJI_EXECUTE = "🚀"
EMOJI_OUTPUT = "📄"
EMOJI_STOP = "🛑"
EMOJI_COMMENT = "💬"
EMOJI_ERROR = "❌"
EMOJI_SUMMARY = "📝"
EMOJI_COMMENT = "💬"

C_BG_SUBTLE = "\033[48;5;236m" # A subtle dark grey background

# --- Core Functions ---

def get_initial_context():
    """Gathers initial context to provide to the agent."""
    return {
        "current_directory": os.getcwd(),
        "current_datetime": datetime.now().isoformat(),
        "operating_system": sys.platform,
        "shell": os.environ.get("SHELL", "unknown"),
    }

def call_llm(messages):
    """Calls the LLM API with the given messages."""
    headers = {"Content-Type": "application/json"}
    api_key = CONFIG.get("api_key")
    if api_key and api_key != "not-needed":
        headers["Authorization"] = f"Bearer {api_key}"

    data = {
        "model": CONFIG.get("model"),
        "messages": messages,
        "temperature": 0.7,
    }
    try:
        response = requests.post(CONFIG.get("endpoint_url"), headers=headers, data=json.dumps(data))
        response.raise_for_status()
        return response.json()
    except requests.exceptions.RequestException as e:
        print(f"{C_RED}{EMOJI_ERROR} Error calling LLM: {e}{C_END}", file=sys.stderr)
        return None

def get_system_prompt():
    """Defines the agent's instructions and persona."""
    return """
    You are a helpful AI assistant running in a shell environment. Your goal is to assist the user by executing shell commands to accomplish their tasks.

    ## Your Workflow:
    1.  **Analyze:** Understand the user's request and the context provided.
    2.  **Plan:** Formulate a step-by-step plan.
    3.  **Propose:** Explain your plan clearly and concisely in plain text. Do NOT use markdown for the explanation. Then, propose the *next single shell command* in a fenced code block like ```bash\ncommand\n```. The explanation must always precede the code block.
    4.  **Summarize:** When you believe the user's original request is fully resolved, do NOT propose a command. Instead, provide a concise summary of the key findings and the final outcome. Start your summary with the phrase "Final Summary:".

    ## Important Rules:
    -   **Efficiency:** To be maximally efficient, use shell script constructs like `for` loops, pipes, and command chains (`&&`) to perform multiple steps in a single command when it is safe and logical to do so. This reduces the need for user interaction.
    -   **Clarity:** Propose only one command block at a time. Explain your reasoning for the entire block clearly.
    -   **Safety:** If a command is complex or potentially destructive, break it down into smaller, safer steps.
    -   If a command fails, analyze the error and try to correct it.
    -   Your task is complete when you believe the user's original request has been fully addressed.
    """

def parse_llm_response(response_text):
    """Extracts the plan explanation and a shell command from the LLM's response."""
    command_match = re.search(r"```(?:bash|sh)?\n(.*?)```", response_text, re.DOTALL)
    command = None
    explanation = response_text.strip()

    if command_match:
        command = command_match.group(1).strip()
        explanation = response_text.replace(command_match.group(0), "").strip()

    explanation = re.sub(r"^#+ ", "", explanation)
    explanation = re.sub(r"(\*\*{1,2}|_{1,2})(.*?)\1", r"\2", explanation)

    return explanation, command

def execute_command(command):
    """Executes a shell command and returns its raw output."""
    try:
        shell = os.environ.get("SHELL", "/bin/bash")
        result = subprocess.run(command, shell=True, check=False, capture_output=True, text=True, executable=shell)
        return result.stdout, result.stderr, result.returncode
    except Exception as e:
        return None, f"Execution error: {e}", 1

# --- Main Execution ---

if __name__ == "__main__":
    console = Console()

    if len(sys.argv) < 2:
        console.print("Usage: [bold blue]./aish.py <your command>")
        sys.exit(1)

    user_command = " ".join(sys.argv[1:])
    initial_context = get_initial_context()
    context_str = json.dumps(initial_context, indent=2)

    system_prompt = get_system_prompt()
    user_initial_msg = f"""
    Here is the initial context:\n{context_str}\n\nMy command is: "{user_command}"\nPlease create a plan and propose the first command.
    """

    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": user_initial_msg},
    ]

    while True:
        with console.status("[bold green]Agent is thinking..."): 
            llm_response = call_llm(messages)
        
        if not llm_response:
            console.print(Panel("Agent did not return a response.", title="Error", border_style="red"))
            break

        assistant_response = llm_response.get("choices", [{}])[0].get("message", {}).get("content", "")
        messages.append({"role": "assistant", "content": assistant_response})
        
        explanation, command_to_run = parse_llm_response(assistant_response)

        if not command_to_run:
            console.print(Panel(explanation, title=f"{EMOJI_SUMMARY} Summary", border_style="green"))
            break

        # --- Plan and Command Panels ---
        console.print(Panel(Text(explanation, justify="left"), title=f"{EMOJI_AGENT} Plan", border_style="blue"))
        console.print(Panel(Syntax(command_to_run, "bash", theme="monokai", line_numbers=False), title=f"{EMOJI_COMMAND} Command", border_style="blue"))

        # --- User Prompt ---
        try:
            choice_prompt = f"[bold yellow]Execute? (y/n/c):[/bold yellow] "
            choice = console.input(choice_prompt).lower().strip()
        except (EOFError, KeyboardInterrupt):
            choice = 'n'

        if choice in ('n', 'no'):
            console.print("[yellow]Execution stopped by user.[/yellow]")
            break
        elif choice in ('c', 'comment'):
            try:
                comment_prompt = f"[yellow]{EMOJI_COMMENT} Comment: [/yellow]"
                comment = console.input(comment_prompt)
                if not comment.strip():
                    console.print("[red]Comment cannot be empty.[/red]")
                    continue
                messages.append({"role": "user", "content": f"User comment: {comment}"})
                continue
            except (EOFError, KeyboardInterrupt):
                console.print("\n[yellow]Execution stopped by user.[/yellow]")
                break
        elif choice in ('y', 'yes', ''):
            stdout, stderr, return_code = execute_command(command_to_run)
            
            output_for_llm = []
            output_panels = []

            if stdout:
                output_for_llm.append(f"STDOUT:\n{stdout.strip()}")
                output_panels.append(Panel(Syntax(stdout, "bash", theme="monokai"), title=f"{EMOJI_OUTPUT} STDOUT", border_style="green"))
            if stderr:
                output_for_llm.append(f"STDERR:\n{stderr.strip()}")
                output_panels.append(Panel(Text(stderr, justify="left"), title=f"{EMOJI_ERROR} STDERR", border_style="red"))

            if return_code != 0:
                output_for_llm.insert(0, f"Command failed with exit code {return_code}")

            for panel in output_panels:
                console.print(panel)

            full_output_for_llm = "\n".join(output_for_llm)
            messages.append({"role": "user", "content": f"Command '{command_to_run}' executed (exit code: {return_code}). Output:\n{full_output_for_llm}"})
        else:
            console.print("[red]Invalid choice. Exiting.[/red]")
            break