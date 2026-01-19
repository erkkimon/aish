#!/usr/bin/env python3
import sys
import os
import json
import re
import asyncio
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

# Built-in tools
from tools import ToolCall, ToolResult, execute_tool, get_tools_description, TOOLS, apply_file_edit

# MCP support (optional module)
from mcp_manager import mcp_manager, MCPToolCall

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

    tool_call: Optional[ToolCall] = Field(
        default=None,
        description="Call a tool to perform an action. Set tool_name ('bash_exec', 'web_search', 'web_fetch') and arguments dict. Must be set for any actionable request."
    )

    mcp_tool_call: Optional[MCPToolCall] = Field(
        default=None,
        description="Call an MCP tool (if available). Set tool_name and arguments. Cannot be used together with 'tool_call'."
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
        description="True ONLY after actionable requests have been executed. If user asks to 'open/run/create/edit' something, this must be false until tool is called. Never true for unexecuted action requests."
    )

    memory_update: Optional[str] = Field(
        default=None,
        description="Memory update for system STATE changes (not history). Use 'Add to memory:', 'Update memory:', or 'Delete from memory:' followed by section and content. Only for durable facts: installed software, configurations, user preferences. Never log events or actions taken."
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
    Asks the assistant to consider if system STATE has changed.
    """
    return """

    Task completed. Consider if any **system STATE** has changed that should be remembered.

    **Only update memory if:**
    - New software was installed/configured (store: what it is, where, how configured)
    - User preference was revealed (store: the preference itself)
    - System configuration changed (store: the new state)

    **NEVER store:**
    - What actions you took ("installed X", "ran Y")
    - What the user asked for
    - Timestamps or dates
    - Temporary information

    **Good example:** "## Web Server\\n- nginx serves /var/www/html on port 80"
    **Bad example:** "## Session Log\\n- Installed nginx for user"

    If system state changed, use the memory update format. If nothing changed, just provide your summary.
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
            "explanation": "System state: current facts about configurations, preferences, and environment (not action history)"
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

    # Build headers - add Kimi-specific headers only when using Kimi API
    headers = {}
    if "kimi.com" in base_url:
        # Kimi checks for recognized coding agents via headers
        headers = {
            "User-Agent": "claude-code/1.0.0",
            "anthropic-version": "2023-06-01",
            "x-client-name": "claude-code"
        }

    # Create OpenAI client
    client = OpenAI(
        base_url=base_url,
        api_key=api_key,
        default_headers=headers if headers else None
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


# --- Context Management ---

def estimate_tokens(text: str) -> int:
    """
    Estimate the number of tokens in a text string.
    Uses a simple heuristic: ~4 characters per token on average.
    This is a rough approximation that works reasonably well for most text.
    """
    return len(text) // 4


def count_messages_tokens(messages: list) -> int:
    """
    Count the total estimated tokens in a list of messages.
    Includes role overhead (~4 tokens per message for role/formatting).
    """
    total = 0
    for msg in messages:
        content = msg.get("content", "")
        # Add content tokens + overhead for role and formatting
        total += estimate_tokens(content) + 4
    return total


class CondensationSummary(BaseModel):
    """Model for context condensation summary."""
    summary: str = Field(
        description="A comprehensive summary of the conversation so far, including: what the user requested, what actions were taken, what tools were used and their results, any important decisions or outcomes. Be thorough but concise."
    )


def call_llm_for_condensation(messages: list) -> Optional[str]:
    """
    Call LLM to create a condensed summary of messages.
    Uses a simpler prompt without the full agent context.
    """
    try:
        client = get_instructor_client()

        condensation_prompt = """You are a context summarizer. Your task is to create a comprehensive summary of the conversation history provided.

Include in your summary:
1. What the user originally requested
2. What actions/tools were executed and their results
3. Any important decisions, errors, or outcomes
4. The current state of the task (completed, in progress, etc.)
5. Any relevant context needed to continue the conversation

Be thorough but concise. The summary will be used to continue the conversation with limited context."""

        # Build the messages to summarize
        summary_messages = [
            {"role": "system", "content": condensation_prompt},
            {"role": "user", "content": f"Please summarize this conversation history:\n\n{json.dumps(messages, indent=2)}"}
        ]

        response = client.chat.completions.create(
            model=CONFIG.get("model"),
            response_model=CondensationSummary,
            messages=summary_messages,
            temperature=0.3,  # Lower temperature for more consistent summaries
            max_retries=2,
        )
        return response.summary
    except Exception as e:
        print(f"{C_YELLOW}Warning: Context condensation failed: {e}{C_END}", file=sys.stderr)
        return None


def condense_context(messages: list, console) -> list:
    """
    Condense the context when it exceeds the maximum length.

    Strategy:
    1. Keep the system prompt (first message) intact
    2. Split remaining messages into older half and newer half
    3. Summarize the older half
    4. Return: [system_prompt, condensation_summary, newer_half_messages]

    Args:
        messages: The full message list
        console: Rich console for status output

    Returns:
        Condensed message list
    """
    if len(messages) <= 3:
        # Not enough messages to condense
        return messages

    # Keep system prompt separate
    system_prompt = messages[0]
    conversation_messages = messages[1:]

    # Find the midpoint
    midpoint = len(conversation_messages) // 2

    # Ensure we have at least some messages in each half
    if midpoint < 1:
        midpoint = 1

    older_half = conversation_messages[:midpoint]
    newer_half = conversation_messages[midpoint:]

    # Create summary of older half
    with console.status("[bold cyan]Condensing context (summarizing older messages)..."):
        summary = call_llm_for_condensation(older_half)

    if not summary:
        # If condensation failed, try a simpler approach: just keep recent messages
        console.print("[yellow]⚠ Context condensation failed, keeping recent messages only[/yellow]")
        # Keep system prompt + last half of messages
        return [system_prompt] + newer_half

    # Build condensed message list
    condensation_message = {
        "role": "user",
        "content": f"[CONTEXT SUMMARY - Earlier conversation was condensed to save space]\n\n{summary}\n\n[END OF CONTEXT SUMMARY - Continuing conversation below]"
    }

    condensed_messages = [system_prompt, condensation_message] + newer_half

    # Log the condensation
    old_tokens = count_messages_tokens(messages)
    new_tokens = count_messages_tokens(condensed_messages)
    console.print(f"[dim]📦 Context condensed: {old_tokens} → {new_tokens} tokens ({len(messages)} → {len(condensed_messages)} messages)[/dim]")

    return condensed_messages


def check_and_condense_context(messages: list, max_tokens: int, console) -> list:
    """
    Check if context exceeds max tokens and condense if needed.

    Args:
        messages: Current message list
        max_tokens: Maximum allowed tokens
        console: Rich console for output

    Returns:
        Original or condensed message list
    """
    current_tokens = count_messages_tokens(messages)

    if current_tokens >= max_tokens:
        console.print(f"[yellow]⚠ Context limit reached ({current_tokens}/{max_tokens} tokens), condensing...[/yellow]")
        return condense_context(messages, console)

    return messages


def get_system_prompt():
    """Defines the agent's instructions and persona."""
    memory_path = get_memory_path()
    memory_info = f"""

    ## Memory Management:
    You have a persistent memory file at {memory_path}. This memory stores **SYSTEM STATE** - durable facts about the current environment.

    ### What memory IS for (STATE):
    - System configuration: "nginx installed, serves /var/www/html on port 80"
    - User preferences: "prefers vim, uses 4-space indentation"
    - Project info: "uses Python 3.11 with poetry, tests in pytest"
    - Custom setups: "backup script at ~/scripts/backup.sh"

    ### What memory is NOT for (HISTORY):
    - NEVER log actions: "installed nginx", "ran backup"
    - NEVER log events: "user asked about X", "created file Y"
    - NEVER include timestamps or dates
    - NEVER describe what you did - only what IS

    ### Key principle:
    Memory answers "What is true about this system?" NOT "What happened?"
    When state changes, UPDATE the fact (don't append a new event).

    ### How to Update Memory:

    **Use file_edit** to update memory. This shows a diff for user approval before changes are applied.

    Example - Add new preference:
    ```json
    {{"tool_call": {{"tool_name": "file_edit", "arguments": {{
        "file_path": "{memory_path}",
        "old_text": "## User Preferences\\n",
        "new_text": "## User Preferences\\n- prefers vim over nano\\n"
    }}}}}}
    ```

    Example - Update existing entry:
    ```json
    {{"tool_call": {{"tool_name": "file_edit", "arguments": {{
        "file_path": "{memory_path}",
        "old_text": "- uses Python 3.10",
        "new_text": "- uses Python 3.12"
    }}}}}}
    ```

    First use `file_read` to see current memory content, then use `file_edit` to make changes.
    Keep memory compact. Delete outdated information when state changes.
    """ if load_memory() is not None else f"""

    ## Memory Management:
    A memory file at {memory_path} stores **SYSTEM STATE** - durable facts about the environment.

    **Use file_edit** to update memory - this shows a diff for user approval before changes are applied.
    First use `file_read` to check current content, then use `file_edit` to add/update facts.

    Example:
    ```json
    {{"tool_call": {{"tool_name": "file_edit", "arguments": {{
        "file_path": "{memory_path}",
        "old_text": "",
        "new_text": "## User Preferences\\n- prefers vim\\n"
    }}}}}}
    ```

    Store: configurations, preferences, installed tools, project conventions.
    Never store: action logs, timestamps, "what I did" entries.
    """
    
    # Get tools description based on config
    web_search_enabled = CONFIG.get('web_search_enabled', True)
    tools_section = get_tools_description(web_search_enabled=web_search_enabled)

    # Get MCP section only if tools are available
    mcp_section = mcp_manager.get_system_prompt_section()
    has_mcp = mcp_manager.has_tools()

    # MCP field description if available
    mcp_field_desc = ""
    if has_mcp:
        mcp_field_desc = "\n    - **mcp_tool_call**: Call an MCP tool (if available). Set tool_name and arguments dict."

    # Web search note if disabled
    web_search_note = ""
    if not web_search_enabled:
        web_search_note = """
    **Note:** Web search is currently disabled. If you encounter a problem that seems to require
    internet access (e.g., looking up documentation, finding current information), suggest to the
    user that enabling web search might help. They can enable it in ~/.aish/config.yaml by setting
    web_search_enabled: true
    """

    return f"""
    You are a helpful AI assistant running in a shell environment. Your goal is to assist the boss by using tools to accomplish their tasks.

    You must respond using structured output with these fields:
    - **explanation**: Your clear explanation of what you're doing or thinking
    - **tool_call**: Call a tool (bash_exec, web_search, web_fetch). Set tool_name and arguments dict.{mcp_field_desc}
    - **is_question**: Set to true if you're asking the user a question
    - **question_options**: List of options if providing choices (can be null)
    - **is_complete**: Set to true when the original request is fully resolved
    - **memory_update**: Memory update in markdown format when task is complete (can be null)

    {tools_section}

    ## Your Workflow:
    1.  **Analyze:** Understand the boss's request and the context provided.
    2.  **Plan & Execute:** Formulate a plan and use the appropriate tool.
        - Set `explanation` to describe what you're doing and why
        - Set `tool_call` with the tool name and arguments
        - Keep `is_complete` as false while work remains
    3.  **Ask Questions:** If you need clarification:
        - Set `is_question` to true
        - Set `tool_call` to null
        - Optionally provide `question_options` as a list of choices
    4.  **Complete:** When the boss's request is fully resolved:
        - Set `is_complete` to true
        - Set `tool_call` to null
        - Provide a final summary in `explanation`
        - Optionally set `memory_update` with relevant information to preserve

    ## Important Rules:
    -   **ACTION BIAS:** If the user requests an action (open, run, create, delete, edit, search, etc.), you MUST provide a `tool_call`. NEVER just describe what you "would do" - actually call the tool.
    -   **NEVER set is_complete=true for actionable requests** until the tool has been executed. If user says "open X with vim", call bash_exec with "vim X", don't just summarize.
    -   **Direct Language:** Address the boss directly using "you" and "your" instead of "the user" or "the boss's".
    -   **Efficiency:** For bash_exec, use shell constructs like `for` loops, pipes, and command chains (`&&`) when safe.
    -   **Clarity:** Propose only one tool call at a time. Explain your reasoning clearly.
    -   **Safety:** If an operation is complex or potentially destructive, break it down into smaller, safer steps.
    -   If a tool call fails, analyze the error and try to correct it.
    -   When using bash_exec with interactive commands, prefer adding non-interactive flags such as --noconfirm, --yes, or --accept.
    {web_search_note}
    {mcp_section}
    {memory_info}
    """

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

# --- Tool Emojis ---
EMOJI_MCP = "🔌"
EMOJI_SEARCH = "🔍"
EMOJI_WEB = "🌐"
EMOJI_FILE = "📁"
EMOJI_EDIT = "✏️"
EMOJI_DIFF = "📝"


def get_tool_emoji(tool_name: str) -> str:
    """Get the appropriate emoji for a tool."""
    if tool_name == 'bash_exec':
        return EMOJI_COMMAND
    elif tool_name == 'web_search':
        return EMOJI_SEARCH
    elif tool_name == 'web_fetch':
        return EMOJI_WEB
    elif tool_name == 'file_read':
        return EMOJI_FILE
    elif tool_name == 'file_edit':
        return EMOJI_EDIT
    return EMOJI_COMMAND


def get_tool_display_name(tool_name: str) -> str:
    """Get a display-friendly name for a tool."""
    names = {
        'bash_exec': 'Bash Command',
        'web_search': 'Web Search',
        'web_fetch': 'Fetch Web Page',
        'file_read': 'Read File',
        'file_edit': 'Edit File'
    }
    return names.get(tool_name, tool_name)


# --- Main Execution ---

async def main():
    console = Console()

    if len(sys.argv) < 2:
        console.print("Usage: [bold blue]./aish.py <your command>")
        sys.exit(1)

    # Initialize MCP servers if configured
    if mcp_manager.is_available():
        with console.status("[bold cyan]Connecting to MCP servers..."):
            await mcp_manager.connect_all(console)

    # Get config settings
    web_search_enabled = CONFIG.get('web_search_enabled', True)
    web_search_auto_accept = CONFIG.get('web_search_auto_accept', False)
    max_context_length = CONFIG.get('max_context_length', 8192)

    try:
        user_command = " ".join(sys.argv[1:])
        initial_context = get_initial_context()

        # Add available tools to context
        available_tools = list(TOOLS.keys())
        if not web_search_enabled:
            available_tools = [t for t in available_tools if t not in ('web_search', 'web_fetch')]
        initial_context["available_tools"] = available_tools

        # Add MCP tools info to context if available
        if mcp_manager.has_tools():
            initial_context["mcp_tools_available"] = list(mcp_manager.all_tools.keys())

        context_str = json.dumps(initial_context, indent=2)

        system_prompt = get_system_prompt()
        user_initial_msg = f"""
        Here is the initial context:\n{context_str}\n\nMy command is: "{user_command}"\nPlease analyze and use the appropriate tool.
        """

        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_initial_msg},
        ]

        while True:
            # Check context length and condense if needed
            messages = check_and_condense_context(messages, max_context_length, console)

            with console.status("[bold green]Agent is thinking..."):
                agent_response = call_llm(messages)

            if not agent_response:
                console.print(Panel("Agent did not return a response.", title="Error", border_style="red"))
                break

            # Add the structured response to messages as JSON for context
            messages.append({"role": "assistant", "content": agent_response.model_dump_json()})

            # Extract fields from structured response
            explanation = agent_response.explanation
            tool_call = agent_response.tool_call
            mcp_tool_call = agent_response.mcp_tool_call
            is_complete = agent_response.is_complete
            is_question = agent_response.is_question
            question_options = agent_response.question_options
            memory_update = agent_response.memory_update

            # Handle task completion (no tool call AND no MCP tool call)
            if is_complete or (not tool_call and not mcp_tool_call):
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

            # Handle MCP tool calls
            if mcp_tool_call:
                tool_name = mcp_tool_call.tool_name
                tool_args = mcp_tool_call.arguments

                # Display MCP tool call
                console.print(Panel(Text(explanation, justify="left"), title=f"{EMOJI_AGENT} Plan", border_style="blue"))
                tool_call_str = f"{tool_name}({json.dumps(tool_args, indent=2)})"
                console.print(Panel(Syntax(tool_call_str, "json", theme="monokai", line_numbers=False), title=f"{EMOJI_MCP} MCP Tool Call", border_style="cyan"))

                # --- User Prompt for MCP tool ---
                try:
                    choice_prompt = f"[bold yellow]Execute MCP tool? (Y/n/c):[/bold yellow] "
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
                    # Execute MCP tool
                    with console.status(f"[bold cyan]Calling MCP tool '{tool_name}'..."):
                        result = await mcp_manager.call_tool(tool_name, tool_args)

                    if "error" in result:
                        console.print(Panel(Text(result["error"], justify="left"), title=f"{EMOJI_ERROR} MCP Tool Error", border_style="red"))
                        messages.append({"role": "user", "content": f"MCP tool '{tool_name}' failed. Error: {result['error']}"})
                    else:
                        tool_result = result.get("result", "")
                        # Truncate very long results for display
                        display_result = tool_result[:2000] + "..." if len(tool_result) > 2000 else tool_result
                        console.print(Panel(Text(display_result, justify="left"), title=f"{EMOJI_OUTPUT} MCP Tool Result", border_style="green"))
                        messages.append({"role": "user", "content": f"MCP tool '{tool_name}' executed successfully. Result:\n{tool_result}"})
                else:
                    console.print("[red]Invalid choice. Exiting.[/red]")
                    break

                continue

            # Handle built-in tool calls
            if tool_call:
                tool_name = tool_call.tool_name
                tool_args = tool_call.arguments
                tool_emoji = get_tool_emoji(tool_name)
                tool_display = get_tool_display_name(tool_name)

                # Check if web search/fetch is disabled
                if tool_name in ('web_search', 'web_fetch') and not web_search_enabled:
                    console.print(Panel(
                        f"Web search is disabled. Enable it in ~/.aish/config.yaml by setting web_search_enabled: true",
                        title="⚠️ Web Search Disabled",
                        border_style="yellow"
                    ))
                    messages.append({"role": "user", "content": f"Tool '{tool_name}' is disabled. Web search is not enabled in configuration."})
                    continue

                # Display tool call
                console.print(Panel(Text(explanation, justify="left"), title=f"{EMOJI_AGENT} Plan", border_style="blue"))

                # Format tool call for display
                if tool_name == 'bash_exec':
                    command = tool_args.get('command', '')
                    console.print(Panel(Syntax(command, "bash", theme="monokai", line_numbers=False), title=f"{tool_emoji} {tool_display}", border_style="blue"))
                else:
                    tool_call_str = f"{tool_name}({json.dumps(tool_args, indent=2)})"
                    console.print(Panel(Syntax(tool_call_str, "json", theme="monokai", line_numbers=False), title=f"{tool_emoji} {tool_display}", border_style="cyan"))

                # Determine if we should auto-accept
                auto_accept = False
                if tool_name in ('web_search', 'web_fetch') and web_search_auto_accept:
                    auto_accept = True

                # --- User Prompt ---
                if auto_accept:
                    choice = 'y'
                    console.print(f"[dim](auto-accepted)[/dim]")
                else:
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
                    # Execute tool
                    with console.status(f"[bold cyan]Executing {tool_display}..."):
                        result = execute_tool(tool_name, tool_args, CONFIG)

                    if not result.success:
                        error_msg = result.error or "Unknown error"
                        console.print(Panel(Text(error_msg, justify="left"), title=f"{EMOJI_ERROR} Tool Error", border_style="red"))
                        messages.append({"role": "user", "content": f"Tool '{tool_name}' failed. Error: {error_msg}"})
                    elif tool_name == 'file_edit' and result.pending_edit:
                        # Special handling for file_edit: show diff and ask for approval
                        file_path = result.pending_edit.get('file_path', 'unknown')
                        console.print(Panel(
                            Syntax(result.diff, "diff", theme="monokai", line_numbers=False),
                            title=f"{EMOJI_DIFF} Diff: {file_path}",
                            border_style="yellow"
                        ))

                        # Ask for approval to apply changes
                        try:
                            apply_prompt = f"[bold yellow]Apply these changes? (Y/n):[/bold yellow] "
                            apply_choice = console.input(apply_prompt).lower().strip()
                        except (EOFError, KeyboardInterrupt):
                            apply_choice = 'n'

                        if apply_choice in ('y', 'yes', ''):
                            # Apply the edit
                            apply_result = apply_file_edit(result.pending_edit)
                            if apply_result.success:
                                console.print(f"[green]✓ {apply_result.output}[/green]")
                                messages.append({"role": "user", "content": f"File edit applied successfully to {file_path}."})
                            else:
                                console.print(Panel(Text(apply_result.error or "Unknown error", justify="left"), title=f"{EMOJI_ERROR} Apply Error", border_style="red"))
                                messages.append({"role": "user", "content": f"Failed to apply file edit: {apply_result.error}"})
                        else:
                            console.print("[yellow]File edit cancelled.[/yellow]")
                            messages.append({"role": "user", "content": f"User cancelled the file edit to {file_path}."})
                    else:
                        output = result.output
                        # Truncate very long results for display
                        display_output = output[:2000] + "..." if len(output) > 2000 else output
                        console.print(Panel(Text(display_output, justify="left"), title=f"{EMOJI_OUTPUT} Result", border_style="green"))
                        messages.append({"role": "user", "content": f"Tool '{tool_name}' executed successfully. Result:\n{output}"})
                else:
                    console.print("[red]Invalid choice. Exiting.[/red]")
                    break

                continue

    finally:
        # Clean up MCP servers
        if mcp_manager.servers:
            with console.status("[bold cyan]Disconnecting MCP servers..."):
                await mcp_manager.cleanup()


if __name__ == "__main__":
    asyncio.run(main())