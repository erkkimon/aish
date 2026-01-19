"""
Built-in tools for AISH agent.

This module provides core tools that the agent can use:
- bash_exec: Execute shell commands
- file_read: Read file contents
- file_edit: Edit files with search/replace (shows diff)
- web_fetch: Fetch and convert web pages to markdown
- web_search: Search the web using DuckDuckGo
"""

import os
import sys
import subprocess
import difflib
from typing import Any, Optional
from pydantic import BaseModel, Field


class ToolCall(BaseModel):
    """Represents a call to a built-in tool."""
    tool_name: str = Field(description="The name of the tool to call: 'bash_exec', 'file_read', 'file_edit', 'web_fetch', or 'web_search'")
    arguments: dict[str, Any] = Field(default_factory=dict, description="Arguments to pass to the tool")


class ToolResult(BaseModel):
    """Result from a tool execution."""
    success: bool
    output: str
    error: Optional[str] = None
    # For file_edit: contains the diff and pending changes
    diff: Optional[str] = None
    pending_edit: Optional[dict] = None  # {file_path, new_content}


# List of interactive programs that need direct terminal access
INTERACTIVE_PROGRAMS = [
    'vim', 'vi', 'nvim', 'nano', 'pico', 'emacs', 'micro',  # editors
    'less', 'more', 'most',  # pagers
    'htop', 'top', 'btop', 'atop', 'glances',  # monitors
    'mc', 'ranger', 'nnn', 'lf',  # file managers
    'tmux', 'screen',  # terminal multiplexers
    'ssh', 'telnet',  # remote access
    'man', 'info',  # documentation
    'python', 'python3', 'ipython', 'node', 'irb', 'ghci',  # REPLs
]


def is_interactive_command(command: str) -> bool:
    """Check if command starts with an interactive program that needs direct terminal access."""
    cmd_parts = command.strip().split()
    if not cmd_parts:
        return False

    first_cmd = cmd_parts[0]

    # Check first command and commands after &&
    for part in command.split('&&'):
        part = part.strip().split()[0] if part.strip().split() else ''
        if part in INTERACTIVE_PROGRAMS:
            return True

    return first_cmd in INTERACTIVE_PROGRAMS


def bash_exec(command: str) -> ToolResult:
    """
    Execute a bash command and return the result.

    Args:
        command: The bash command to execute

    Returns:
        ToolResult with stdout/stderr and success status
    """
    try:
        shell = os.environ.get("SHELL", "/bin/bash")

        # Interactive commands need direct terminal access
        if is_interactive_command(command):
            returncode = os.system(command)
            return ToolResult(
                success=returncode == 0,
                output="(interactive program completed)",
                error=None if returncode == 0 else f"Exit code: {returncode >> 8}"
            )

        result = subprocess.run(
            command,
            shell=True,
            check=False,
            capture_output=True,
            text=True,
            executable=shell
        )

        output_parts = []
        if result.stdout:
            output_parts.append(result.stdout.strip())
        if result.stderr:
            output_parts.append(f"STDERR: {result.stderr.strip()}")

        return ToolResult(
            success=result.returncode == 0,
            output="\n".join(output_parts) if output_parts else "(no output)",
            error=None if result.returncode == 0 else f"Exit code: {result.returncode}"
        )

    except Exception as e:
        return ToolResult(
            success=False,
            output="",
            error=f"Execution error: {e}"
        )


def file_read(file_path: str) -> ToolResult:
    """
    Read the contents of a file.

    Args:
        file_path: Path to the file to read

    Returns:
        ToolResult with file contents
    """
    try:
        # Expand user home directory
        file_path = os.path.expanduser(file_path)

        if not os.path.exists(file_path):
            return ToolResult(
                success=False,
                output="",
                error=f"File not found: {file_path}"
            )

        if not os.path.isfile(file_path):
            return ToolResult(
                success=False,
                output="",
                error=f"Not a file: {file_path}"
            )

        with open(file_path, 'r', encoding='utf-8', errors='replace') as f:
            content = f.read()

        # Truncate if too long
        if len(content) > 50000:
            content = content[:50000] + "\n\n... (content truncated, file too large)"

        return ToolResult(
            success=True,
            output=content,
            error=None
        )

    except PermissionError:
        return ToolResult(
            success=False,
            output="",
            error=f"Permission denied: {file_path}"
        )
    except Exception as e:
        return ToolResult(
            success=False,
            output="",
            error=f"Error reading file: {e}"
        )


def file_edit(file_path: str, old_text: str, new_text: str) -> ToolResult:
    """
    Edit a file by replacing old_text with new_text.
    Returns a diff for user approval before applying.

    Args:
        file_path: Path to the file to edit
        old_text: Text to find and replace (must match exactly)
        new_text: Text to replace with

    Returns:
        ToolResult with diff preview. The edit is NOT applied automatically.
        The pending_edit field contains the new content to be written if approved.
    """
    try:
        # Expand user home directory
        file_path = os.path.expanduser(file_path)

        # Read current content (or empty for new file)
        if os.path.exists(file_path):
            with open(file_path, 'r', encoding='utf-8', errors='replace') as f:
                current_content = f.read()
        else:
            # Creating new file
            current_content = ""

        # Check if old_text exists in file
        if old_text and old_text not in current_content:
            return ToolResult(
                success=False,
                output="",
                error=f"Text to replace not found in file. Make sure old_text matches exactly (including whitespace)."
            )

        # Count occurrences
        if old_text:
            occurrences = current_content.count(old_text)
            if occurrences > 1:
                return ToolResult(
                    success=False,
                    output="",
                    error=f"Found {occurrences} occurrences of old_text. Please provide more context to make the match unique."
                )

        # Generate new content
        if old_text:
            new_content = current_content.replace(old_text, new_text, 1)
        else:
            # If old_text is empty, append to file (or create new)
            new_content = current_content + new_text

        # Generate unified diff
        current_lines = current_content.splitlines(keepends=True)
        new_lines = new_content.splitlines(keepends=True)

        diff = list(difflib.unified_diff(
            current_lines,
            new_lines,
            fromfile=f"a/{os.path.basename(file_path)}",
            tofile=f"b/{os.path.basename(file_path)}",
            lineterm=""
        ))

        diff_text = "\n".join(diff)

        if not diff_text:
            return ToolResult(
                success=True,
                output="No changes - old_text and new_text are identical.",
                error=None
            )

        return ToolResult(
            success=True,
            output=f"Diff preview for {file_path}:\n\n{diff_text}",
            error=None,
            diff=diff_text,
            pending_edit={"file_path": file_path, "new_content": new_content}
        )

    except PermissionError:
        return ToolResult(
            success=False,
            output="",
            error=f"Permission denied: {file_path}"
        )
    except Exception as e:
        return ToolResult(
            success=False,
            output="",
            error=f"Error preparing edit: {e}"
        )


def apply_file_edit(pending_edit: dict) -> ToolResult:
    """
    Apply a pending file edit (after user approval).

    Args:
        pending_edit: Dict with file_path and new_content

    Returns:
        ToolResult indicating success or failure
    """
    try:
        file_path = pending_edit.get("file_path")
        new_content = pending_edit.get("new_content")

        if not file_path or new_content is None:
            return ToolResult(
                success=False,
                output="",
                error="Invalid pending edit data"
            )

        # Ensure directory exists
        dir_path = os.path.dirname(file_path)
        if dir_path:
            os.makedirs(dir_path, exist_ok=True)

        with open(file_path, 'w', encoding='utf-8') as f:
            f.write(new_content)

        return ToolResult(
            success=True,
            output=f"Successfully updated {file_path}",
            error=None
        )

    except PermissionError:
        return ToolResult(
            success=False,
            output="",
            error=f"Permission denied: {pending_edit.get('file_path', 'unknown')}"
        )
    except Exception as e:
        return ToolResult(
            success=False,
            output="",
            error=f"Error applying edit: {e}"
        )


def web_fetch(url: str, proxy: Optional[str] = None) -> ToolResult:
    """
    Fetch a web page and convert it to markdown.

    Args:
        url: The URL to fetch
        proxy: Optional SOCKS5 proxy URL (e.g., "socks5://localhost:1080")

    Returns:
        ToolResult with the page content as markdown
    """
    try:
        import requests
        import html2text

        # Configure proxy if provided
        proxies = None
        if proxy:
            proxies = {
                'http': proxy,
                'https': proxy
            }

        # Fetch the page
        headers = {
            'User-Agent': 'Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'
        }

        response = requests.get(url, headers=headers, proxies=proxies, timeout=30)
        response.raise_for_status()

        # Convert HTML to markdown
        h = html2text.HTML2Text()
        h.ignore_links = False
        h.ignore_images = True
        h.ignore_emphasis = False
        h.body_width = 0  # Don't wrap lines

        markdown_content = h.handle(response.text)

        # Truncate if too long (keep first 10000 chars)
        if len(markdown_content) > 10000:
            markdown_content = markdown_content[:10000] + "\n\n... (content truncated)"

        return ToolResult(
            success=True,
            output=markdown_content,
            error=None
        )

    except requests.exceptions.RequestException as e:
        return ToolResult(
            success=False,
            output="",
            error=f"Failed to fetch URL: {e}"
        )
    except Exception as e:
        return ToolResult(
            success=False,
            output="",
            error=f"Error processing page: {e}"
        )


def _duckduckgo_search(query: str, max_results: int = 5, proxy: Optional[str] = None) -> ToolResult:
    """
    Search the web using DuckDuckGo.

    Args:
        query: The search query
        max_results: Maximum number of results to return (default: 5)
        proxy: Optional SOCKS5 proxy URL (e.g., "socks5://localhost:1080")

    Returns:
        ToolResult with search results formatted as markdown
    """
    try:
        from duckduckgo_search import DDGS

        # Configure DDGS with proxy if provided
        ddgs_kwargs = {}
        if proxy:
            ddgs_kwargs['proxy'] = proxy

        with DDGS(**ddgs_kwargs) as ddgs:
            results = list(ddgs.text(query, max_results=max_results))

        if not results:
            return ToolResult(
                success=True,
                output="No results found for the query.",
                error=None
            )

        # Format results as markdown
        formatted_results = [f"## Search Results for: {query}\n"]

        for i, result in enumerate(results, 1):
            title = result.get('title', 'No title')
            url = result.get('href', result.get('link', 'No URL'))
            body = result.get('body', result.get('snippet', 'No description'))

            formatted_results.append(f"### {i}. {title}")
            formatted_results.append(f"**URL:** {url}")
            formatted_results.append(f"{body}\n")

        return ToolResult(
            success=True,
            output="\n".join(formatted_results),
            error=None
        )

    except Exception as e:
        return ToolResult(
            success=False,
            output="",
            error=f"DuckDuckGo search failed: {e}"
        )


def _searxng_search(query: str, max_results: int = 5, config: dict = None) -> ToolResult:
    """
    Search the web using a SearxNG instance.

    SearxNG is a privacy-respecting metasearch engine.
    Requires a self-hosted or accessible SearxNG instance with JSON format enabled.

    Args:
        query: The search query
        max_results: Maximum number of results to return (default: 5)
        config: Configuration dict containing searxng_url and optional proxy

    Returns:
        ToolResult with search results formatted as markdown
    """
    try:
        import requests

        config = config or {}
        searxng_url = config.get('searxng_url', '').rstrip('/')

        if not searxng_url:
            return ToolResult(
                success=False,
                output="",
                error="SearxNG URL not configured. Set 'searxng_url' in config.yaml"
            )

        # Configure proxy if provided
        proxy = config.get('web_proxy') or None
        proxies = None
        if proxy:
            proxies = {'http': proxy, 'https': proxy}

        # Make the search request
        params = {
            'q': query,
            'format': 'json',
            'pageno': 1
        }

        headers = {
            'User-Agent': 'AISH/1.0 (AI Shell Assistant)',
            'Accept': 'application/json'
        }

        response = requests.get(
            f"{searxng_url}/search",
            params=params,
            headers=headers,
            proxies=proxies,
            timeout=30
        )

        if response.status_code == 403:
            return ToolResult(
                success=False,
                output="",
                error="SearxNG returned 403 Forbidden. Make sure JSON format is enabled in your SearxNG settings.yml"
            )

        response.raise_for_status()
        data = response.json()

        results = data.get('results', [])[:max_results]

        if not results:
            return ToolResult(
                success=True,
                output="No results found for the query.",
                error=None
            )

        # Format results as markdown
        formatted_results = [f"## Search Results for: {query}\n"]

        for i, result in enumerate(results, 1):
            title = result.get('title', 'No title')
            url = result.get('url', 'No URL')
            content = result.get('content', 'No description')
            engine = result.get('engine', 'unknown')

            formatted_results.append(f"### {i}. {title}")
            formatted_results.append(f"**URL:** {url}")
            formatted_results.append(f"**Source:** {engine}")
            formatted_results.append(f"{content}\n")

        return ToolResult(
            success=True,
            output="\n".join(formatted_results),
            error=None
        )

    except requests.exceptions.ConnectionError:
        return ToolResult(
            success=False,
            output="",
            error=f"Cannot connect to SearxNG at {config.get('searxng_url', 'unknown')}. Is it running?"
        )
    except requests.exceptions.RequestException as e:
        return ToolResult(
            success=False,
            output="",
            error=f"SearxNG request failed: {e}"
        )
    except Exception as e:
        return ToolResult(
            success=False,
            output="",
            error=f"SearxNG search failed: {e}"
        )


def _perplexica_search(query: str, max_results: int = 5, config: dict = None) -> ToolResult:
    """
    Search the web using a Perplexica instance.

    Perplexica is an AI-powered search engine that provides answers with sources.
    Requires a self-hosted Perplexica instance.

    Args:
        query: The search query
        max_results: Maximum number of sources to return (default: 5)
        config: Configuration dict containing perplexica settings

    Returns:
        ToolResult with AI-generated answer and sources formatted as markdown
    """
    try:
        import requests

        config = config or {}
        perplexica_url = config.get('perplexica_url', '').rstrip('/')

        if not perplexica_url:
            return ToolResult(
                success=False,
                output="",
                error="Perplexica URL not configured. Set 'perplexica_url' in config.yaml"
            )

        # Configure proxy if provided
        proxy = config.get('web_proxy') or None
        proxies = None
        if proxy:
            proxies = {'http': proxy, 'https': proxy}

        headers = {
            'Content-Type': 'application/json',
            'Accept': 'application/json'
        }

        # First, get available providers if not configured
        chat_provider = config.get('perplexica_chat_provider', '')
        chat_model = config.get('perplexica_chat_model', '')
        embedding_provider = config.get('perplexica_embedding_provider', '')
        embedding_model = config.get('perplexica_embedding_model', '')

        # If providers not configured, try to get defaults from the API
        if not chat_provider or not chat_model:
            try:
                providers_resp = requests.get(
                    f"{perplexica_url}/api/providers",
                    headers=headers,
                    proxies=proxies,
                    timeout=10
                )
                if providers_resp.status_code == 200:
                    providers = providers_resp.json()
                    # Use first available provider/model as default
                    if providers and len(providers) > 0:
                        first_provider = providers[0]
                        if not chat_provider:
                            chat_provider = first_provider.get('id', '')
                        if not chat_model and first_provider.get('chatModels'):
                            chat_model = first_provider['chatModels'][0].get('key', '')
                        if not embedding_provider:
                            embedding_provider = first_provider.get('id', '')
                        if not embedding_model and first_provider.get('embeddingModels'):
                            embedding_model = first_provider['embeddingModels'][0].get('key', '')
            except Exception:
                pass  # Use empty values, let Perplexica use its defaults

        # Build the search request
        optimization_mode = config.get('perplexica_mode', 'balanced')

        request_body = {
            'query': query,
            'sources': ['web'],
            'optimizationMode': optimization_mode,
            'stream': False
        }

        # Add model configuration if available
        if chat_provider and chat_model:
            request_body['chatModel'] = {
                'providerId': chat_provider,
                'key': chat_model
            }

        if embedding_provider and embedding_model:
            request_body['embeddingModel'] = {
                'providerId': embedding_provider,
                'key': embedding_model
            }

        response = requests.post(
            f"{perplexica_url}/api/search",
            json=request_body,
            headers=headers,
            proxies=proxies,
            timeout=60  # Longer timeout for AI processing
        )

        if response.status_code == 400:
            error_data = response.json() if response.text else {}
            error_msg = error_data.get('message', 'Bad request')
            return ToolResult(
                success=False,
                output="",
                error=f"Perplexica error: {error_msg}. You may need to configure chat/embedding models in config.yaml"
            )

        response.raise_for_status()
        data = response.json()

        # Extract the AI-generated answer and sources
        message = data.get('message', '')
        sources = data.get('sources', [])[:max_results]

        if not message and not sources:
            return ToolResult(
                success=True,
                output="No results found for the query.",
                error=None
            )

        # Format as markdown
        formatted_results = [f"## AI-Powered Search Results for: {query}\n"]

        if message:
            formatted_results.append("### Answer")
            formatted_results.append(f"{message}\n")

        if sources:
            formatted_results.append("### Sources")
            for i, source in enumerate(sources, 1):
                metadata = source.get('metadata', {})
                title = metadata.get('title', 'No title')
                url = metadata.get('url', 'No URL')
                content = source.get('content', '')[:200]  # Truncate long content

                formatted_results.append(f"**{i}. [{title}]({url})**")
                if content:
                    formatted_results.append(f"   {content}...")
                formatted_results.append("")

        return ToolResult(
            success=True,
            output="\n".join(formatted_results),
            error=None
        )

    except requests.exceptions.ConnectionError:
        return ToolResult(
            success=False,
            output="",
            error=f"Cannot connect to Perplexica at {config.get('perplexica_url', 'unknown')}. Is it running?"
        )
    except requests.exceptions.RequestException as e:
        return ToolResult(
            success=False,
            output="",
            error=f"Perplexica request failed: {e}"
        )
    except Exception as e:
        return ToolResult(
            success=False,
            output="",
            error=f"Perplexica search failed: {e}"
        )


def web_search(query: str, max_results: int = 5, proxy: Optional[str] = None, config: dict = None) -> ToolResult:
    """
    Search the web using the configured search backend.

    Supports multiple backends:
    - duckduckgo (default): No setup required, works out of the box
    - searxng: Privacy-respecting metasearch engine (self-hosted)
    - perplexica: AI-powered search engine (self-hosted)

    Args:
        query: The search query
        max_results: Maximum number of results to return (default: 5)
        proxy: Optional SOCKS5 proxy URL (for backwards compatibility)
        config: Configuration dict with search backend settings

    Returns:
        ToolResult with search results formatted as markdown
    """
    config = config or {}

    # Get search backend from config
    backend = config.get('search_backend', 'duckduckgo').lower()

    # Get proxy from config if not provided directly
    if not proxy:
        proxy = config.get('web_proxy') or None
        if proxy == '':
            proxy = None

    if backend == 'searxng':
        return _searxng_search(query, max_results, config)
    elif backend == 'perplexica':
        return _perplexica_search(query, max_results, config)
    else:
        # Default to DuckDuckGo
        return _duckduckgo_search(query, max_results, proxy)


# Tool registry for easy lookup
TOOLS = {
    'bash_exec': {
        'function': bash_exec,
        'description': 'Execute a bash command in the shell',
        'parameters': {
            'command': 'The bash command to execute (required)'
        }
    },
    'file_read': {
        'function': file_read,
        'description': 'Read the contents of a file',
        'parameters': {
            'file_path': 'Path to the file to read (required)'
        }
    },
    'file_edit': {
        'function': file_edit,
        'description': 'Edit a file by replacing text. Shows a diff for approval before applying.',
        'parameters': {
            'file_path': 'Path to the file to edit (required)',
            'old_text': 'Exact text to find and replace (required, must be unique in file)',
            'new_text': 'Text to replace with (required)'
        }
    },
    'web_fetch': {
        'function': web_fetch,
        'description': 'Fetch a web page and convert it to readable markdown',
        'parameters': {
            'url': 'The URL to fetch (required)'
        }
    },
    'web_search': {
        'function': web_search,
        'description': 'Search the web and return results. Uses configured backend (DuckDuckGo, SearxNG, or Perplexica)',
        'parameters': {
            'query': 'The search query (required)',
            'max_results': 'Maximum number of results (default: 5)'
        }
    }
}


def execute_tool(tool_name: str, arguments: dict, config: dict = None) -> ToolResult:
    """
    Execute a tool by name with the given arguments.

    Args:
        tool_name: Name of the tool to execute
        arguments: Arguments to pass to the tool
        config: Optional configuration dict (for proxy settings, etc.)

    Returns:
        ToolResult from the tool execution
    """
    if tool_name not in TOOLS:
        return ToolResult(
            success=False,
            output="",
            error=f"Unknown tool: {tool_name}. Available tools: {', '.join(TOOLS.keys())}"
        )

    tool_func = TOOLS[tool_name]['function']
    config = config or {}

    # Get proxy from config if available
    proxy = config.get('web_proxy') or None
    if proxy == '':
        proxy = None

    try:
        if tool_name == 'bash_exec':
            command = arguments.get('command')
            if not command:
                return ToolResult(success=False, output="", error="'command' argument is required")
            return tool_func(command)

        elif tool_name == 'file_read':
            file_path = arguments.get('file_path')
            if not file_path:
                return ToolResult(success=False, output="", error="'file_path' argument is required")
            return file_read(file_path)

        elif tool_name == 'file_edit':
            file_path = arguments.get('file_path')
            old_text = arguments.get('old_text', '')
            new_text = arguments.get('new_text', '')
            if not file_path:
                return ToolResult(success=False, output="", error="'file_path' argument is required")
            return file_edit(file_path, old_text, new_text)

        elif tool_name == 'web_fetch':
            url = arguments.get('url')
            if not url:
                return ToolResult(success=False, output="", error="'url' argument is required")
            return tool_func(url, proxy=proxy)

        elif tool_name == 'web_search':
            query = arguments.get('query')
            if not query:
                return ToolResult(success=False, output="", error="'query' argument is required")
            max_results = arguments.get('max_results', 5)
            return tool_func(query, max_results=max_results, config=config)

        else:
            return ToolResult(success=False, output="", error=f"Tool '{tool_name}' not implemented")

    except Exception as e:
        return ToolResult(success=False, output="", error=f"Tool execution error: {e}")


def get_tools_description(web_search_enabled: bool = True) -> str:
    """
    Generate a description of available tools for the system prompt.

    Args:
        web_search_enabled: Whether web search is enabled

    Returns:
        Formatted string describing available tools
    """
    lines = ["## Available Tools\n"]
    lines.append("Use the `tool_call` field to invoke these tools:\n")

    for name, info in TOOLS.items():
        # Skip web_search and web_fetch if web search is disabled
        if not web_search_enabled and name in ('web_search', 'web_fetch'):
            continue

        lines.append(f"### {name}")
        lines.append(f"{info['description']}\n")
        lines.append("**Parameters:**")
        for param, desc in info['parameters'].items():
            lines.append(f"  - `{param}`: {desc}")
        lines.append("")

    lines.append("**Example tool calls:**")
    lines.append("")
    lines.append("Execute a command:")
    lines.append("```json")
    lines.append('{"tool_call": {"tool_name": "bash_exec", "arguments": {"command": "ls -la"}}}')
    lines.append("```")
    lines.append("")
    lines.append("Read a file:")
    lines.append("```json")
    lines.append('{"tool_call": {"tool_name": "file_read", "arguments": {"file_path": "/etc/hosts"}}}')
    lines.append("```")
    lines.append("")
    lines.append("Edit a file (search and replace):")
    lines.append("```json")
    lines.append('{')
    lines.append('  "tool_call": {')
    lines.append('    "tool_name": "file_edit",')
    lines.append('    "arguments": {')
    lines.append('      "file_path": "config.py",')
    lines.append('      "old_text": "DEBUG = False",')
    lines.append('      "new_text": "DEBUG = True"')
    lines.append('    }')
    lines.append('  }')
    lines.append('}')
    lines.append("```")
    lines.append("")
    lines.append("**Important for file_edit:**")
    lines.append("- old_text must match exactly (including whitespace/indentation)")
    lines.append("- old_text must be unique in the file (provide more context if not)")
    lines.append("- User will see a diff and must approve before changes are applied")
    lines.append("")

    return "\n".join(lines)
