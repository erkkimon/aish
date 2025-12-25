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
from pydantic import BaseModel, Field
from typing import Optional
import instructor
from openai import OpenAI

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

# --- Pydantic Models for Structured Output ---

class AgentResponse(BaseModel):
    """Structured response from the AI agent."""

    explanation: str = Field(
        description="Clear explanation of what you're doing or your response to the user"
    )

    command: Optional[str] = Field(
        default=None,
        description="The next bash command to execute. Set to null when the task is complete or when asking a question."
    )

    is_question: bool = Field(
        default=False,
        description="True if you're asking the user a question that requires their input"
    )

    question_options: Optional[list[str]] = Field(
        default=None,
        description="List of options for the user to choose from. Only set if is_question is True and you're providing specific choices."
    )

    is_complete: bool = Field(
        default=False,
        description="True if the user's original request has been fully resolved and no more commands are needed"
    )

    memory_update: Optional[str] = Field(
        default=None,
        description="Memory update in markdown format (with 'Add to memory:', 'Update memory:', or 'Delete from memory:' followed by section and content). Only set when task is complete and there's relevant information to preserve."
    )

# --- Core Functions ---

def get_memory_path():
    """Returns the path to the memory file."""
    return os.path.join(USER_CONFIG_DIR, "memory.md")

def load_memory():
    """Loads the memory content if it exists."""
    memory_path = get_memory_path()
    if os.path.exists(memory_path):
        try:
            with open(memory_path, 'r') as f:
                return f.read()
        except (IOError, OSError) as e:
            print(f"Warning: Could not read memory file {memory_path}: {e}", file=sys.stderr)
    return None

def parse_memory_diff(diff_text):
    """
    Parses a memory diff instruction from the assistant.
    Returns: (action, section, content) where action is 'add', 'update', or 'delete'
    """
    lines = diff_text.strip().split('\n')
    if not lines:
        return None, None, None
    
    # Look for action instruction
    action_line = lines[0].lower()
    if 'add to memory' in action_line:
        action = 'add'
    elif 'update memory' in action_line:
        action = 'update'
    elif 'delete from memory' in action_line:
        action = 'delete'
    else:
        return None, None, None
    
    # Extract section (second line, typically starts with ## or ###)
    section = None
    content = None
    
    if len(lines) >= 2:
        section_line = lines[1].strip()
        if section_line.startswith('##'):
            section = section_line
    
    # Rest is content (skip empty lines at start)
    if len(lines) >= 3:
        content_lines = lines[2:]
        # Skip leading empty lines
        while content_lines and not content_lines[0].strip():
            content_lines.pop(0)
        content = '\n'.join(content_lines).strip()
    
    return action, section, content

def parse_multiple_memory_diffs(response_text):
    """
    Parses multiple memory diff instructions from the assistant response.
    Returns: list of (action, section, content) tuples
    """
    diffs = []
    
    # Find all markdown code blocks
    code_blocks = re.findall(r"```(?:markdown|md)?\n(.*?)```", response_text, re.DOTALL)
    
    for block in code_blocks:
        action, section, content = parse_memory_diff(block)
        if action:
            diffs.append((action, section, content))
    
    return diffs

def apply_memory_diff(action, section, content):
    """
    Applies a memory diff to the memory file.
    Returns: (success, message, new_content)
    """
    memory_path = get_memory_path()
    current_content = load_memory() or ""
    
    if action == 'add':
        if section and content:
            # Add new section
            new_content = current_content + f"\n{section}\n{content}\n"
        else:
            # Add to end
            new_content = current_content + f"\n{content}\n" if content else current_content
    
    elif action == 'update':
        if not section:
            return False, "Update requires a section to identify what to update", current_content
        
        # Find and replace section
        import re
        section_pattern = re.compile(rf'({re.escape(section)}.*?)(?=##|\Z)', re.DOTALL)
        
        if section_pattern.search(current_content):
            if content:
                new_content = section_pattern.sub(f'{section}\n{content}\n', current_content)
            else:
                # Just the section header with no content
                new_content = section_pattern.sub(f'{section}\n', current_content)
        else:
            # Section doesn't exist, add it
            new_content = current_content + f"\n{section}\n{content}\n" if content else current_content + f"\n{section}\n"
    
    elif action == 'delete':
        if not section:
            return False, "Delete requires a section to identify what to delete", current_content
        
        # Find and remove section
        import re
        section_pattern = re.compile(rf'{re.escape(section)}.*?(?=##|\Z)', re.DOTALL)
        new_content = section_pattern.sub('', current_content).strip() + '\n'
    
    else:
        return False, f"Unknown action: {action}", current_content
    
    # Ensure config directory exists
    os.makedirs(USER_CONFIG_DIR, exist_ok=True)
    
    try:
        with open(memory_path, 'w') as f:
            f.write(new_content)
        return True, f"Memory {action}ed successfully", new_content
    except (IOError, OSError) as e:
        return False, f"Failed to update memory: {e}", current_content

def suggest_memory_update():
    """
    Injects a memory update suggestion into the conversation when a task is completed.
    This asks the assistant to consider what information should be preserved.
    """
    return """
    
    The task has been completed. Before finishing, please review what happened and consider if there's any information that should be added to, updated in, or removed from memory.
    
    Think about:
    - New preferences or behavioral guidelines discovered
    - Important environment information learned (extract actual values, not placeholders)
    - Changes to workflows or processes
    - Any information that would help you better assist the boss in future sessions
    
    CRITICAL: Extract actual discovered values, not patterns or placeholders. For example:
    - BAD: "Kernel version pattern: Linux [hostname] [version]"
    - GOOD: "Kernel version: Linux sanitee 6.1.78-1-lts x86_64"
    
    If there is relevant information to preserve, provide it in the memory update format. If nothing needs to be added or changed, simply provide your final summary.
    
    Remember to use the format:
    ```markdown
    Add to memory:
    ## Section Name
    - Specific information with actual values
    
    Update memory:
    ## Section Name
    - Updated information with actual values
    
    Delete from memory:
    ## Section Name
    ```
    """

def apply_memory_diff_with_retry(action, section, content, max_retries=10):
    """
    Applies a memory diff with retry logic in case of failures.
    Returns: (success, message, new_content)
    """
    for attempt in range(max_retries):
        success, message, new_content = apply_memory_diff(action, section, content)
        if success:
            return True, message, new_content
        
        if attempt < max_retries - 1:
            # Wait a bit before retrying (optional, could add exponential backoff)
            import time
            time.sleep(0.1 * (attempt + 1))  # Simple linear backoff
    
    return False, f"Failed after {max_retries} attempts: {message}", content

def edit_memory(new_content):
    """
    Legacy function: Edits the memory file with new content (full replacement).
    Returns: (success, message)
    """
    memory_path = get_memory_path()
    
    # Ensure config directory exists
    os.makedirs(USER_CONFIG_DIR, exist_ok=True)
    
    try:
        with open(memory_path, 'w') as f:
            f.write(new_content)
        return True, f"Memory updated successfully at {memory_path}"
    except (IOError, OSError) as e:
        return False, f"Failed to update memory: {e}"

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
                    "explanation": "These are the last 50 lines of bash output from your current session"
                }
        except (IOError, OSError) as e:
            context["bash_session_history"] = {
                "error": f"Could not read bash session log: {e}",
                "source_file": bash_session_log
            }
    
    # Add memory content if available
    memory_content = load_memory()
    if memory_content:
        context["memory"] = {
            "source_file": get_memory_path(),
            "content": memory_content,
            "explanation": "This is the persistent memory containing information about preferences, environment, and useful context"
        }
    
    return context

def get_instructor_client():
    """Creates and returns an Instructor-wrapped OpenAI client."""
    # Prepare the base URL - strip /chat/completions if present, keep /v1
    endpoint_url = CONFIG.get("endpoint_url", "")

    # Normalize the URL to just the base (with /v1)
    if endpoint_url.endswith("/chat/completions"):
        base_url = endpoint_url.replace("/chat/completions", "")
    elif endpoint_url.endswith("/v1"):
        base_url = endpoint_url
    elif endpoint_url.endswith("/v1/"):
        base_url = endpoint_url.rstrip("/")
    else:
        base_url = f"{endpoint_url.rstrip('/')}/v1"

    # Get API key
    api_key = CONFIG.get("api_key", "not-needed")
    if not api_key or api_key == "not-needed":
        api_key = "not-needed"  # OpenAI client requires some value

    # Create OpenAI client
    client = OpenAI(
        base_url=base_url,
        api_key=api_key
    )

    # Wrap with Instructor using MD_JSON mode (most compatible with local models)
    # MD_JSON wraps JSON in markdown blocks, works with models that don't support function calling
    return instructor.from_openai(client, mode=instructor.Mode.MD_JSON)

def call_llm(messages, response_model=AgentResponse, max_retries=2):
    """Calls the LLM API with the given messages and returns a structured response."""
    try:
        client = get_instructor_client()
        response = client.chat.completions.create(
            model=CONFIG.get("model"),
            response_model=response_model,
            messages=messages,
            temperature=0.7,
            max_retries=max_retries,
        )
        return response
    except Exception as e:
        error_msg = str(e)
        # Check if it's a function calling / structured output error
        if "function" in error_msg.lower() or "tool" in error_msg.lower() or "500" in error_msg:
            print(f"{C_RED}{EMOJI_ERROR} Error: Your LLM endpoint may not support structured output.{C_END}", file=sys.stderr)
            print(f"{C_YELLOW}💡 Try using a larger model or different endpoint that supports JSON mode.{C_END}", file=sys.stderr)
        else:
            print(f"{C_RED}{EMOJI_ERROR} Error calling LLM: {e}{C_END}", file=sys.stderr)
        return None

def get_system_prompt():
    """Defines the agent's instructions and persona."""
    memory_info = f"""
    
    ## Memory Management:
    You have access to a persistent memory file at {get_memory_path()}. This memory contains important information about:
    - Boss preferences and behavioral expectations
    - Environment details and configurations
    - Useful context from previous sessions
    - Workflow preferences
    
    When you complete a task, you should consider if there's any information that should be added to, updated in, or removed from memory. This includes:
    - New preferences or behavioral guidelines
    - Important environment information discovered
    - Changes to workflows or processes
    - Any information that would help you better assist the boss in future sessions
    
    ### How to Update Memory:
    To update memory, provide your suggestion in this format using markdown code blocks:
    
    **For adding new information:**
    ```markdown
    Add to memory:
    ## Section Name
    - New information line 1
    - New information line 2
    ```
    
    **For updating existing information:**
    ```markdown
    Update memory:
    ## Section Name
    - Updated information (replaces the entire section content)
    ```
    
    **For deleting information:**
    ```markdown
    Delete from memory:
    ## Section Name
    ```
    
    The memory system will automatically handle the diff and apply the changes. Always wrap your memory update suggestions in markdown code blocks.
    The memory should remain concise and free of useless information. Suggest deletions when information becomes outdated or irrelevant.
    """ if load_memory() is not None else """
    
    ## Memory Management:
    A memory file will be created at {get_memory_path()} to store important information about boss preferences, environment details, and useful context.
    When completing tasks, consider what information should be preserved for future sessions.
    """
    
    return f"""
    You are a helpful AI assistant running in a shell environment. Your goal is to assist the boss by executing shell commands to accomplish their tasks.

    You must respond using structured output with these fields:
    - **explanation**: Your clear explanation of what you're doing or thinking
    - **command**: The next bash command to execute (set to null when done or asking a question)
    - **is_question**: Set to true if you're asking the user a question
    - **question_options**: List of options if providing choices (can be null)
    - **is_complete**: Set to true when the original request is fully resolved
    - **memory_update**: Memory update in markdown format when task is complete (can be null)

    ## Your Workflow:
    1.  **Analyze:** Understand the boss's request and the context provided.
    2.  **Plan & Execute:** Formulate a plan and propose the next single shell command.
        - Set `explanation` to describe what you're doing and why
        - Set `command` to the bash command to execute
        - Keep `is_complete` as false while work remains
    3.  **Ask Questions:** If you need clarification:
        - Set `is_question` to true
        - Set `command` to null
        - Optionally provide `question_options` as a list of choices
    4.  **Complete:** When the boss's request is fully resolved:
        - Set `is_complete` to true
        - Set `command` to null
        - Provide a final summary in `explanation`
        - Optionally set `memory_update` with relevant information to preserve

    ## Important Rules:
    -   **Direct Language:** Address the boss directly using "you" and "your" instead of "the user" or "the boss's".
    -   **Efficiency:** Use shell script constructs like `for` loops, pipes, and command chains (`&&`) to perform multiple steps in a single command when safe.
    -   **Clarity:** Propose only one command at a time. Explain your reasoning clearly.
    -   **Safety:** If a command is complex or potentially destructive, break it down into smaller, safer steps.
    -   If a command fails, analyze the error and try to correct it.
    -   When listing steps in your explanation, you're describing what YOU will do, not asking the user to choose. The steps are sequential actions you'll take.
    {memory_info}
    """

def execute_command(command):
    """Executes a shell command and returns its raw output."""
    try:
        shell = os.environ.get("SHELL", "/bin/bash")
        result = subprocess.run(command, shell=True, check=False, capture_output=True, text=True, executable=shell)
        return result.stdout, result.stderr, result.returncode
    except Exception as e:
        return None, f"Execution error: {e}", 1

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
            agent_response = call_llm(messages)

        if not agent_response:
            console.print(Panel("Agent did not return a response.", title="Error", border_style="red"))
            break

        # Add the structured response to messages as JSON for context
        messages.append({"role": "assistant", "content": agent_response.model_dump_json()})

        # Extract fields from structured response
        explanation = agent_response.explanation
        command_to_run = agent_response.command
        is_complete = agent_response.is_complete
        is_question = agent_response.is_question
        question_options = agent_response.question_options
        memory_update = agent_response.memory_update

        # Handle task completion
        if is_complete or not command_to_run:
            # Task is complete
            console.print(Panel(explanation, title=f"{EMOJI_SUMMARY} Summary", border_style="green"))

            # Handle memory update if provided
            if memory_update:
                action, section, content = parse_memory_diff(memory_update)

                if action:
                    console.print(Panel("Memory update suggested:", title="🧠 Memory Update", border_style="magenta"))
                    console.print(Panel(Syntax(memory_update, "markdown", theme="monokai", line_numbers=False), border_style="magenta"))

                    try:
                        choice = console.input("[bold magenta]Update memory? (Y/n):[/bold magenta] ").lower().strip()
                    except (EOFError, KeyboardInterrupt):
                        choice = 'n'

                    if choice in ('y', 'yes', ''):
                        success, message, new_content = apply_memory_diff_with_retry(action, section, content)
                        if success:
                            console.print(f"[green]✓ {message}[/green]")
                        else:
                            console.print(f"[red]✗ {message}[/red]")
                    else:
                        console.print("[yellow]Memory update cancelled.[/yellow]")

            break

        # Handle questions from the agent
        if is_question:
            if question_options:
                # Interactive option selection
                response = ask_question_with_options(console, explanation, question_options)
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