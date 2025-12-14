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
# Look for config.yaml in user's config directory or script directory
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
USER_CONFIG_DIR = os.path.expanduser("~/.aish")
USER_CONFIG_PATH = os.path.join(USER_CONFIG_DIR, "config.yaml")

# Use user config if it exists, otherwise use script directory
if os.path.exists(USER_CONFIG_PATH):
    CONFIG_PATH = USER_CONFIG_PATH
else:
    CONFIG_PATH = os.path.join(SCRIPT_DIR, "config.yaml")

# Check for AISH_DIR environment variable for the script location
AISH_DIR = os.environ.get("AISH_DIR", SCRIPT_DIR)

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
    context = {
        "current_directory": os.getcwd(),
        "current_datetime": datetime.now().isoformat(),
        "operating_system": sys.platform,
        "shell": os.environ.get("SHELL", "unknown"),
    }
    
    # Add bash session history if available
    bash_session_log = os.environ.get("BASH_SESSION_CARBON_COPY")
    if bash_session_log and os.path.exists(bash_session_log):
        try:
            with open(bash_session_log, 'r') as f:
                # Get last 50 lines
                lines = f.readlines()
                last_50_lines = lines[-50:] if len(lines) > 50 else lines
                context["bash_session_history"] = {
                    "source_file": bash_session_log,
                    "last_50_lines": [line.rstrip() for line in last_50_lines],
                    "explanation": "These are the last 50 lines of bash output from user's current session"
                }
        except (IOError, OSError) as e:
            context["bash_session_history"] = {
                "error": f"Could not read bash session log: {e}",
                "source_file": bash_session_log
            }
    
    return context

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
        # Append /chat/completions to the endpoint URL if not already present
        endpoint_url = CONFIG.get("endpoint_url")
        if not endpoint_url.endswith("/chat/completions"):
            if endpoint_url.endswith("/v1"):
                endpoint_url = f"{endpoint_url}/chat/completions"
            elif endpoint_url.endswith("/v1/"):
                endpoint_url = f"{endpoint_url}chat/completions"
            else:
                endpoint_url = f"{endpoint_url.rstrip('/')}/v1/chat/completions"
        
        response = requests.post(endpoint_url, headers=headers, data=json.dumps(data))
        response.raise_for_status()
        return response.json()
    except requests.exceptions.RequestException as e:
        print(f"{C_RED}{EMOJI_ERROR} Error calling LLM: {e}{C_END}", file=sys.stderr)
        return None

def get_system_prompt():
    """Defines the agent's instructions and persona."""
    return """
    You are a helpful AI assistant running in a shell environment. Your goal is to assist the boss by executing shell commands to accomplish their tasks.

    ## Your Workflow:
    1.  **Analyze:** Understand the boss's request and the context provided.
    2.  **Plan:** Formulate a step-by-step plan.
    3.  **Propose:** Explain your plan clearly and concisely in plain text. Do NOT use markdown for the explanation. Then, propose the *next single shell command* in a fenced code block like ```bash\ncommand\n```. The explanation must always precede the code block.
    4.  **Summarize:** When you believe the boss's original request is fully resolved, do NOT propose a command. Instead, provide a concise summary of the key findings and the final outcome. Start your summary with the phrase "Final Summary:".

    ## Important Rules:
    -   **Direct Language:** Address the boss directly using "you" and "your" instead of "the user" or "the boss's". For example, say "your request requires this" not "the boss's request requires this".
    -   **Efficiency:** To be maximally efficient, use shell script constructs like `for` loops, pipes, and command chains (`&&`) to perform multiple steps in a single command when it is safe and logical to do so. This reduces the need for interaction.
    -   **Clarity:** Propose only one command block at a time. Explain your reasoning for the entire block clearly.
    -   **Safety:** If a command is complex or potentially destructive, break it down into smaller, safer steps.
    -   If a command fails, analyze the error and try to correct it.
    -   Your task is complete when you believe the boss's original request has been fully addressed.
    -   **Questions:** When you need to ask the boss a question, provide clear options and allow for custom input.
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

def is_question_and_parse_options(response_text):
    """
    Detects if the response is asking a question and parses any options.
    Returns: (is_question, options_list) where options_list is None or list of options
    """
    # Check if it's a question
    question_indicators = [
        "?", "should i", "would you like", "do you want", "which", "what", "how", "when", "where", "why",
        "please select", "please choose", "choose one", "select an option"
    ]
    
    lower_text = response_text.lower()
    is_q = any(indicator in lower_text for indicator in question_indicators)
    
    if not is_q:
        return False, None
    
    # Try to parse options (look for numbered or bulleted lists)
    options = []
    lines = response_text.split('\n')
    
    for line in lines:
        stripped = line.strip()
        # Match patterns like "1.", "1)", "-", "*", "•"
        if (stripped.startswith(('1.', '2.', '3.', '4.', '5.', '6.', '7.', '8.', '9.')) or
            stripped.startswith(('1)', '2)', '3)', '4)', '5)', '6)', '7)', '8)', '9)')) or
            stripped.startswith(('- ', '* ', '• '))):
            # Remove the bullet/number and clean up
            clean_line = stripped
            for prefix in ['1.', '2.', '3.', '4.', '5.', '6.', '7.', '8.', '9.',
                          '1)', '2)', '3)', '4)', '5)', '6)', '7)', '8)', '9)',
                          '- ', '* ', '• ']:
                if clean_line.startswith(prefix):
                    clean_line = clean_line[len(prefix):].strip()
                    break
            if clean_line:
                options.append(clean_line)
    
    # Only return options if we found at least 2
    if len(options) >= 2:
        return True, options
    
    return True, None

def ask_question_with_options(console, question_text, options):
    """
    Presents an interactive menu with options and a custom input field.
    Returns the selected option or custom text.
    """
    from rich.prompt import Prompt
    from rich.console import Group
    from rich.panel import Panel
    from rich.text import Text
    
    # Display the question
    console.print(Panel(question_text, title="❓ Question", border_style="yellow"))
    
    # Create menu items
    menu_items = options + ["[Custom response...]"]
    
    # For now, use simple numbered selection (full arrow key support would require more complex UI)
    console.print("\n[yellow]Select an option:[/yellow]")
    for i, option in enumerate(menu_items, 1):
        if i == len(menu_items):
            console.print(f"  [cyan]{i}.[/cyan] {option}")
        else:
            console.print(f"  [cyan]{i}.[/cyan] {option}")
    
    while True:
        try:
            choice = Prompt.ask("\n[yellow]Enter number or custom text[/yellow]", console=console)
            
            # Try to parse as number first
            try:
                num = int(choice.strip())
                if 1 <= num <= len(menu_items):
                    if num == len(menu_items):
                        # Custom response selected
                        custom = Prompt.ask("[yellow]Enter your response[/yellow]", console=console)
                        return custom
                    else:
                        return options[num - 1]
                else:
                    console.print("[red]Invalid selection. Please try again.[/red]")
            except ValueError:
                # Not a number, treat as custom response
                if choice.strip():
                    return choice
                else:
                    console.print("[red]Please enter a valid selection or custom text.[/red]")
                    
        except (EOFError, KeyboardInterrupt):
            return None

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

        # Check if this appears to be a simple question that doesn't need command execution
        simple_question_indicators = [
            "is this", "is that", "is the", "are these", "are those",
            "does this", "does that", "what is", "what are",
            "syntactically", "syntax", "correct", "okay", "ok"
        ]
        
        lower_explanation = explanation.lower()
        if any(indicator in lower_explanation for indicator in simple_question_indicators) and len(command_to_run.strip()) < 10:
            # Likely a simple question, just answer without running commands
            console.print(Panel(explanation, title=f"{EMOJI_SUMMARY} Answer", border_style="green"))
            break

        # Check if the assistant is asking a question with options
        is_question, options = is_question_and_parse_options(assistant_response)
        if is_question:
            if options:
                # Interactive option selection
                response = ask_question_with_options(console, explanation, options)
                if response is None:
                    console.print("\n[yellow]Question cancelled by boss.[/yellow]")
                    break
                messages.append({"role": "user", "content": f"Boss response: {response}"})
                continue
            else:
                # Open-ended question - treat as comment mode
                try:
                    console.print(Panel(explanation, title="❓ Question", border_style="yellow"))
                    comment_prompt = f"[yellow]{EMOJI_COMMENT} Your response: [/yellow]"
                    comment = console.input(comment_prompt)
                    if not comment.strip():
                        console.print("[red]Response cannot be empty.[/red]")
                        continue
                    messages.append({"role": "user", "content": f"Boss response: {comment}"})
                    continue
                except (EOFError, KeyboardInterrupt):
                    console.print("\n[yellow]Question cancelled by boss.[/yellow]")
                    break

        # --- Plan and Command Panels ---
        console.print(Panel(Text(explanation, justify="left"), title=f"{EMOJI_AGENT} Plan", border_style="blue"))
        console.print(Panel(Syntax(command_to_run, "bash", theme="monokai", line_numbers=False), title=f"{EMOJI_COMMAND} Command", border_style="blue"))

        # --- User Prompt ---
        try:
            choice_prompt = f"[bold yellow]Execute? (Y/n/c):[/bold yellow] "
            choice = console.input(choice_prompt).lower().strip()
        except (EOFError, KeyboardInterrupt):
            choice = 'n'

        if choice in ('n', 'no'):
            console.print("[yellow]Execution stopped by boss.[/yellow]")
            break
        elif choice in ('c', 'comment'):
            try:
                comment_prompt = f"[yellow]{EMOJI_COMMENT} Comment: [/yellow]"
                comment = console.input(comment_prompt)
                if not comment.strip():
                    console.print("[red]Comment cannot be empty.[/red]")
                    continue
                messages.append({"role": "user", "content": f"Boss comment: {comment}"})
                continue
            except (EOFError, KeyboardInterrupt):
                console.print("\n[yellow]Execution stopped by boss.[/yellow]")
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