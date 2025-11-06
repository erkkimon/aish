#!/usr/bin/env python3
import sys
import os
import json
import re
import requests
import subprocess
from datetime import datetime

# --- Configuration Loader ---
CONFIG_PATH = "config.json"
DEFAULT_CONFIG = {
    "_comment": "Configuration for the aish agent. The api_key is optional and only needed for certain services.",
    "model": "Devstral-Small-2505-abliterated.i1-Q2_K_S",
    "endpoint_url": "http://localhost:11435/v1/chat/completions",
    "api_key": "not-needed"
}

def load_config():
    """Loads configuration from config.json, creating it if it doesn't exist."""
    if not os.path.exists(CONFIG_PATH):
        print(f"Configuration file not found. Creating default {CONFIG_PATH}")
        with open(CONFIG_PATH, 'w') as f:
            json.dump(DEFAULT_CONFIG, f, indent=2)
        return DEFAULT_CONFIG
    try:
        with open(CONFIG_PATH, 'r') as f:
            return json.load(f)
    except (json.JSONDecodeError, IOError) as e:
        print(f"Error reading {CONFIG_PATH}: {e}. Using default settings.", file=sys.stderr)
        return DEFAULT_CONFIG

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
    -   Propose only one command at a time.
    -   Explain your reasoning clearly.
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
    """Executes a shell command and returns its output."""
    try:
        shell = os.environ.get("SHELL", "/bin/bash")
        print(f"{C_GREEN}{EMOJI_EXECUTE}{C_BOLD} Executing command:{C_END} {command}")
        result = subprocess.run(command, shell=True, check=False, capture_output=True, text=True, executable=shell)
        
        output_lines = []
        if result.stdout:
            output_lines.append(f"{C_GREEN}STDOUT:{C_END}\n{result.stdout.strip()}")
        if result.stderr:
            output_lines.append(f"{C_RED}STDERR:{C_END}\n{result.stderr.strip()}")
        
        if result.returncode != 0:
            error_msg = f"{C_RED}{EMOJI_ERROR} Command failed with exit code {result.returncode}{C_END}"
            output_lines.insert(0, error_msg)

        return "\n".join(output_lines), result.returncode

    except Exception as e:
        return f"{C_RED}{EMOJI_ERROR} Execution error: {e}{C_END}", 1

# --- Main Execution ---

if __name__ == "__main__":
    if len(sys.argv) < 2:
        print(f"Usage: {C_BLUE}{C_BOLD}./aish.py <your command>{C_END}", file=sys.stderr)
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
        print(f"\n{C_BLUE}--- {EMOJI_AGENT} Agent is thinking... ---{C_END}")
        llm_response = call_llm(messages)
        if not llm_response:
            break

        assistant_response = llm_response.get("choices", [{}])[0].get("message", {}).get("content", "")
        messages.append({"role": "assistant", "content": assistant_response})
        
        explanation, command_to_run = parse_llm_response(assistant_response)

        if not command_to_run:
            print(f"\n{C_BLUE}--- {EMOJI_SUMMARY} Agent Summary ---{C_END}")
            print(explanation)
            break

        print(f"\n{C_BLUE}--- {EMOJI_AGENT} Agent's Plan ---{C_END}")
        print(explanation)
        print(f"\n{C_GREEN}{EMOJI_COMMAND}{C_BOLD} Proposed Command:{C_END} {command_to_run}")

        try:
            choice_prompt = f"{C_YELLOW}Execute command? [Y/n/c]: {C_END}"
            choice = input(choice_prompt).lower().strip()
        except EOFError:
            choice = 'n'

        if choice == 'n':
            print(f"{C_YELLOW}{EMOJI_STOP} Execution stopped by user.{C_END}")
            break
        elif choice == 'c':
            try:
                comment_prompt = f"{C_YELLOW}{EMOJI_COMMENT} Please provide your comment: {C_END}"
                comment = input(comment_prompt)
                if not comment.strip():
                    print(f"{C_RED}{EMOJI_ERROR} Comment cannot be empty. Please try again.{C_END}")
                    continue
                messages.append({"role": "user", "content": f"User comment: {comment}"})
                continue
            except EOFError:
                print(f"{C_YELLOW}{EMOJI_STOP} Execution stopped by user.{C_END}")
                break
        elif choice == 'y' or choice == '':
            output_text, return_code = execute_command(command_to_run)
            
            if output_text:
                print(f"\n{C_BLUE}--- {EMOJI_OUTPUT} Command Output ---{C_END}")
                print(output_text)
            
            messages.append({"role": "user", "content": f"Command '{command_to_run}' executed (exit code: {return_code}). Output:\n{output_text}"})
        else:
            print(f"{C_RED}{EMOJI_ERROR} Invalid choice. Exiting.{C_END}")
            break