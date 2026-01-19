"""
MCP (Model Context Protocol) server manager for AISH.

This module handles all MCP-related functionality:
- Loading MCP server configuration from ~/.aish/mcp.json
- Connecting to MCP servers (stdio and SSE transports)
- Discovering and calling MCP tools
- Generating tool descriptions for the LLM system prompt
"""

import os
import sys
import json
import re
from typing import Any, Optional
from pydantic import BaseModel, Field

# MCP imports - these are optional, only loaded if mcp package is available
try:
    from mcp import ClientSession, StdioServerParameters
    from mcp.client.stdio import stdio_client
    from mcp.client.sse import sse_client
    MCP_AVAILABLE = True
except ImportError:
    MCP_AVAILABLE = False


# Configuration path
USER_CONFIG_DIR = os.path.expanduser("~/.aish")
MCP_CONFIG_PATH = os.path.join(USER_CONFIG_DIR, "mcp.json")


class MCPToolCall(BaseModel):
    """Represents a call to an MCP tool."""
    tool_name: str = Field(description="The name of the MCP tool to call")
    arguments: dict[str, Any] = Field(default_factory=dict, description="Arguments to pass to the tool as key-value pairs")


class MCPManager:
    """Manages MCP server connections and tool discovery."""

    def __init__(self):
        self.servers = {}  # name -> {session, read, write, tools, transport_type}
        self.all_tools = {}  # tool_name -> {server_name, tool_info}
        self._cleanup_registered = False

    def is_available(self):
        """Check if MCP functionality is available."""
        return MCP_AVAILABLE and os.path.exists(MCP_CONFIG_PATH)

    def has_tools(self):
        """Check if any MCP tools are available."""
        return bool(self.all_tools)

    def load_config(self):
        """Load MCP server configuration from mcp.json."""
        if not os.path.exists(MCP_CONFIG_PATH):
            return {}

        try:
            with open(MCP_CONFIG_PATH, 'r') as f:
                config = json.load(f)
            return config.get("servers", {})
        except (json.JSONDecodeError, IOError) as e:
            print(f"Warning: Could not load MCP config from {MCP_CONFIG_PATH}: {e}", file=sys.stderr)
            return {}

    def _expand_env_vars(self, value):
        """Expand environment variables in string values."""
        if isinstance(value, str):
            # Replace ${VAR} with environment variable value
            pattern = r'\$\{([^}]+)\}'
            def replacer(match):
                var_name = match.group(1)
                return os.environ.get(var_name, match.group(0))
            return re.sub(pattern, replacer, value)
        elif isinstance(value, dict):
            return {k: self._expand_env_vars(v) for k, v in value.items()}
        elif isinstance(value, list):
            return [self._expand_env_vars(item) for item in value]
        return value

    async def connect_stdio_server(self, name, config):
        """Connect to an MCP server via stdio transport."""
        command = config.get("command")
        args = config.get("args", [])
        env = config.get("env", {})

        if not command:
            raise ValueError(f"Server {name}: 'command' is required for stdio transport")

        # Expand environment variables in args and env
        args = self._expand_env_vars(args)
        env = self._expand_env_vars(env)

        # Merge with current environment
        server_env = os.environ.copy()
        server_env.update(env)

        server_params = StdioServerParameters(
            command=command,
            args=args,
            env=server_env
        )

        # Create the stdio client context
        read, write = await stdio_client(server_params).__aenter__()
        session = ClientSession(read, write)
        await session.__aenter__()

        # Initialize the session
        await session.initialize()

        return {
            "session": session,
            "read": read,
            "write": write,
            "transport_type": "stdio",
            "context_managers": [(read, write), session]
        }

    async def connect_sse_server(self, name, config):
        """Connect to an MCP server via SSE transport."""
        url = config.get("url")
        headers = config.get("headers", {})

        if not url:
            raise ValueError(f"Server {name}: 'url' is required for SSE transport")

        # Expand environment variables
        url = self._expand_env_vars(url)
        headers = self._expand_env_vars(headers)

        # Create the SSE client context
        read, write = await sse_client(url, headers=headers).__aenter__()
        session = ClientSession(read, write)
        await session.__aenter__()

        # Initialize the session
        await session.initialize()

        return {
            "session": session,
            "read": read,
            "write": write,
            "transport_type": "sse",
            "context_managers": [(read, write), session]
        }

    async def connect_all(self, console=None):
        """Connect to all configured MCP servers."""
        if not MCP_AVAILABLE:
            if console:
                console.print("[yellow]Warning: MCP package not installed. Run: pip install mcp[/yellow]")
            return

        server_configs = self.load_config()

        if not server_configs:
            return

        for name, config in server_configs.items():
            # Skip comment fields
            if name.startswith("_"):
                continue

            transport = config.get("transport", "stdio")

            try:
                if transport == "stdio":
                    server_info = await self.connect_stdio_server(name, config)
                elif transport == "sse":
                    server_info = await self.connect_sse_server(name, config)
                else:
                    if console:
                        console.print(f"[yellow]Warning: Unknown transport '{transport}' for server '{name}'[/yellow]")
                    continue

                self.servers[name] = server_info

                # Discover tools from this server
                await self._discover_tools(name, server_info["session"])

                if console:
                    tool_count = len([t for t, info in self.all_tools.items() if info["server"] == name])
                    console.print(f"[green]✓ Connected to MCP server '{name}' ({tool_count} tools)[/green]")

            except Exception as e:
                if console:
                    console.print(f"[red]✗ Failed to connect to MCP server '{name}': {e}[/red]")

    async def _discover_tools(self, server_name, session):
        """Discover available tools from an MCP server."""
        try:
            tools_response = await session.list_tools()

            for tool in tools_response.tools:
                tool_name = tool.name
                # Handle name collisions by prefixing with server name
                if tool_name in self.all_tools:
                    tool_name = f"{server_name}_{tool_name}"

                self.all_tools[tool_name] = {
                    "server": server_name,
                    "original_name": tool.name,
                    "description": tool.description or "",
                    "input_schema": tool.inputSchema if hasattr(tool, 'inputSchema') else {}
                }
        except Exception as e:
            print(f"Warning: Could not discover tools from server '{server_name}': {e}", file=sys.stderr)

    async def call_tool(self, tool_name, arguments):
        """Call an MCP tool and return the result."""
        if tool_name not in self.all_tools:
            return {"error": f"Unknown tool: {tool_name}"}

        tool_info = self.all_tools[tool_name]
        server_name = tool_info["server"]
        original_name = tool_info["original_name"]

        if server_name not in self.servers:
            return {"error": f"Server '{server_name}' not connected"}

        session = self.servers[server_name]["session"]

        try:
            result = await session.call_tool(original_name, arguments)

            # Extract text content from result
            if hasattr(result, 'content') and result.content:
                text_parts = []
                for content in result.content:
                    if hasattr(content, 'text'):
                        text_parts.append(content.text)
                    elif hasattr(content, 'data'):
                        text_parts.append(f"[Binary data: {len(content.data)} bytes]")
                return {"result": "\n".join(text_parts)}

            return {"result": str(result)}
        except Exception as e:
            return {"error": f"Tool call failed: {e}"}

    def get_tools_description(self):
        """Generate a description of all available MCP tools for the system prompt."""
        if not self.all_tools:
            return ""

        lines = ["\n## Available MCP Tools:\n"]
        lines.append("You can call these tools using the `mcp_tool_call` field in your response.\n")

        # Group tools by server
        by_server = {}
        for tool_name, info in self.all_tools.items():
            server = info["server"]
            if server not in by_server:
                by_server[server] = []
            by_server[server].append((tool_name, info))

        for server_name, tools in by_server.items():
            lines.append(f"\n### Server: {server_name}\n")
            for tool_name, info in tools:
                desc = info["description"]
                schema = info.get("input_schema", {})

                lines.append(f"- **{tool_name}**: {desc}")

                # Add parameter info if available
                if schema and "properties" in schema:
                    params = []
                    required = schema.get("required", [])
                    for param_name, param_info in schema["properties"].items():
                        param_type = param_info.get("type", "any")
                        param_desc = param_info.get("description", "")
                        req_marker = "*" if param_name in required else ""
                        params.append(f"    - `{param_name}{req_marker}` ({param_type}): {param_desc}")
                    if params:
                        lines.append("\n" + "\n".join(params))
                lines.append("")

        return "\n".join(lines)

    def get_system_prompt_section(self):
        """Get the MCP section for the system prompt. Returns empty string if no tools available."""
        if not self.all_tools:
            return ""

        tools_info = self.get_tools_description()

        return f"""
    ## MCP Tools:
    You have access to MCP (Model Context Protocol) tools in addition to bash commands.
    To use an MCP tool, set `mcp_tool_call` with `tool_name` and `arguments` (a dict of key-value pairs).
    When using an MCP tool, set `command` to null.

    **Example MCP tool call:**
    ```json
    {{
        "explanation": "Reading the contents of config.json",
        "command": null,
        "mcp_tool_call": {{
            "tool_name": "read_file",
            "arguments": {{"path": "/home/user/config.json"}}
        }},
        "is_complete": false
    }}
    ```

    **When to use MCP tools vs bash commands:**
    - Use MCP tools when they provide the specific functionality you need (e.g., database queries, API calls, file operations with specific servers)
    - Use bash commands for general shell operations, running programs, and system administration
    - MCP tools may provide richer, structured data compared to parsing command output

    {tools_info}
    """

    async def cleanup(self):
        """Clean up all MCP server connections."""
        for name, server_info in self.servers.items():
            try:
                # Close in reverse order
                for cm in reversed(server_info.get("context_managers", [])):
                    if hasattr(cm, '__aexit__'):
                        await cm.__aexit__(None, None, None)
            except Exception as e:
                print(f"Warning: Error cleaning up server '{name}': {e}", file=sys.stderr)

        self.servers.clear()
        self.all_tools.clear()


# Global MCP manager instance
mcp_manager = MCPManager()
