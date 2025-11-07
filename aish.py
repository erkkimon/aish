#!/usr/bin/env python3
import sys
import os
import json
import re
import requests
import subprocess
from datetime import datetime
import yaml

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
    """Executes a shell command and returns its raw output."""
    try:
        shell = os.environ.get("SHELL", "/bin/bash")
        result = subprocess.run(command, shell=True, check=False, capture_output=True, text=True, executable=shell)
        return result.stdout, result.stderr, result.returncode
    except Exception as e:
        return None, f"Execution error: {e}", 1

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

    # --- UI Initialization ---
    print(f"┌ {EMOJI_AGENT} aish")
    loop_active = True
    final_summary = ""

    while loop_active:
        # --- Agent Thinking ---
        print("⣾  Agent is thinking...", end='\r')
        llm_response = call_llm(messages)
        sys.stdout.write('\x1b[2K\r') # Clear line

        if not llm_response:
            final_summary = "Agent did not return a response."
            break

        assistant_response = llm_response.get("choices", [{}])[0].get("message", {}).get("content", "")
        messages.append({"role": "assistant", "content": assistant_response})
        
        explanation, command_to_run = parse_llm_response(assistant_response)

        if not command_to_run:
            final_summary = explanation
            loop_active = False
            continue

        # --- Plan and Command ---
        print("│")
        print(f"◇  {C_BOLD}Plan{C_END}")
        for line in explanation.splitlines():
            print(f"│  {line}")
        print("│")
        print(f"◆  {C_BOLD}Command{C_END}")
        print(f"│  {C_BG_SUBTLE} {command_to_run} {C_END}")
        print("│")

        # --- User Prompt ---
        try:
            choice_prompt = f"├─ {C_YELLOW}Execute? [Y/n/c(omment)]: {C_END}"
            choice = input(choice_prompt).lower().strip()
        except EOFError:
            choice = 'n'

        if choice == 'n':
            final_summary = "Execution stopped by user."
            loop_active = False
            continue
        elif choice == 'c':
            print("│")
            try:
                comment_prompt = f"│  {C_YELLOW}{EMOJI_COMMENT} Comment: {C_END}"
                comment = input(comment_prompt)
                if not comment.strip():
                    print(f"│  {C_RED}{EMOJI_ERROR} Comment cannot be empty. Please try again.{C_END}")
                    continue
                messages.append({"role": "user", "content": f"User comment: {comment}"})
                print("│")
                continue
            except EOFError:
                final_summary = "Execution stopped by user."
                loop_active = False
                continue
        elif choice == 'y' or choice == '':
            print("│")
            print(f"├─ {EMOJI_EXECUTE} Execution")
            print(f"│  Running: {command_to_run}")
            
            stdout, stderr, return_code = execute_command(command_to_run)
            
            output_for_llm = []
            
            print(f"│  {C_BG_SUBTLE}")
            if stdout:
                print(f"│  📄 {C_BOLD}STDOUT{C_END}")
                for line in stdout.strip().splitlines():
                    print(f"│  {line}")
                output_for_llm.append(f"STDOUT:\n{stdout.strip()}")

            if stderr:
                print(f"│  ❌ {C_BOLD}STDERR{C_END}")
                for line in stderr.strip().splitlines():
                    print(f"│  {line}")
                output_for_llm.append(f"STDERR:\n{stderr.strip()}")
            
            if return_code != 0:
                output_for_llm.insert(0, f"Command failed with exit code {return_code}")

            print(f"│  {C_END}")
            print("│")

            full_output_for_llm = "\n".join(output_for_llm)
            messages.append({"role": "user", "content": f"Command '{command_to_run}' executed (exit code: {return_code}). Output:\n{full_output_for_llm}"})
        else:
            final_summary = "Invalid choice. Exiting."
            loop_active = False

    # --- Final Summary ---
    print("│")
    print(f"├─ {EMOJI_SUMMARY} Summary")
    for line in final_summary.splitlines():
        print(f"│  {line}")
    print("│")
    print("└─ Task complete.")