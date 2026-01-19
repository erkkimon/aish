# AISH ­&ndash; inline AI agent for devops

AISH is the world's first context-aware inline devops sh agent. It is local-first but works also with any commercial OpenAI compatible LLM. Delegate shell tasks to aish who lives in the terminal. You can do in-line chatting with aish. Just mention `@aish` and send a request and `@aish` will complete it for you.

![aish demo](assets/aish_demo.gif)

*This demo was created using Devstral-2505 24B Q4 running on [vllama](https://github.com/erkkimon/vllama) which is world's fastest drop-in replacement for ollama.*

## 🚀 Features

- **In-line Chatting**: Tag `@aish` anywhere in your terminal session for instant assistance, and it works on any bash terminal including SSH
- **Context Awareness**: aish sees your bash session without initiating agentic sessions and can reference previous commands and outputs
- **Interactive Command Execution**: Approve, deny, or comment on proposed commands before execution
- **Built-in Tools**: Bash execution, file editing with diff preview, web search (DuckDuckGo), and web page fetching out of the box
- **File Editing**: Edit any file with search/replace - always shows a diff for approval before applying changes
- **Web Search**: Search the web using DuckDuckGo - no API key required, works instantly
- **Memory System**: Persistent memory that learns your preferences and environment details across sessions
- **Smart Model Selection**: Automatic model discovery from your LLM endpoint during setup
- **Rich Terminal UI**: Beautiful, colorized output with panels and syntax highlighting
- **Local-First Design**: Works with local LLM runners (Ollama, vLLama) or commercial OpenAI compatible APIs
- **SOCKS5 Proxy Support**: Configure a proxy for web requests if needed
- **MCP Server Support**: Extend aish with Model Context Protocol servers for database access, file operations, and more
- **Bash Session Logging**: Optional real-time session recording for review and sharing
- **Question Detection**: Automatically detects when aish asks questions and provides interactive responses

## 📦 Installation

**Prerequisites:**
- Python 3.12+
- A running OpenAI-compatible LLM endpoint. `aish` is designed with a local-first approach, compatible with local LLM runners like [vLLaMA](https://github.com/erkkimon/vllama) and [Ollama](https://github.com/ollama/ollama). It also works with OpenAI and any other OpenAI-compatible API.

**Quick Install:**
```bash
git clone https://github.com/erkkimon/aish ~/Software/aish
cd ~/Software/aish
bash setup.sh
```

The setup script will:
1. Create a Python virtual environment automatically
2. Install all required dependencies
3. Set up the `@aish` command in your `~/.bashrc`
4. Discover available models from your endpoint and let you choose interactively
5. Configure web search settings (auto-accept and optional SOCKS5 proxy)
6. Create a user configuration file at `~/.aish/config.yaml`

After installation, restart your terminal or run `source ~/.bashrc` to start using `@aish`.

## 🎯 Usage

### Basic Usage
To run the agent, use the `@aish` alias with your command as arguments:

```bash
@aish show me all Python files in this directory
```

### Context-Aware In-line Chatting

aish is context-aware and can see your recent terminal history. This enables powerful in-line conversations:

**Example 1: Analyzing file permissions**
```bash
$ ls -la
total 24
drwxr-xr-x  5 user user 4096 Dec 14 10:23 .
drwxr-xr-x 18 user user 4096 Dec 14 09:15 ..
-rw-r--r--  1 user user  220 Dec 14 10:20 config.yaml
-rwxr-xr-x  1 user user  450 Dec 14 10:15 setup.sh
-rw-r--r--  1 user user 1200 Dec 14 10:10 README.md

$ @aish do those file permissions look okay?
🤖 Plan: I'll check the file permissions from your ls output and analyze if they look correct.
🛠️ Command: echo "Analyzing permissions..."
Execute? (Y/n/c):
```

**Example 2: Working with command output**
```bash
$ find . -name "*.log" -size +10M
./logs/app.log
./logs/debug.log

$ @aish compress those large log files
🤖 Plan: I'll compress the large log files you found to save disk space.
🛠️ Command: gzip ./logs/app.log ./logs/debug.log
Execute? (Y/n/c): y
✓ Command executed successfully
```

**Example 3: Debugging after errors**
```bash
$ python script.py
Traceback (most recent call last):
  File "script.py", line 15, in <module>
    process_data()
  File "script.py", line 8, in process_data
    result = 10 / 0
ZeroDivisionError: division by zero

$ @aish fix that error
🤖 Plan: I can see the ZeroDivisionError in your script. Let me examine the file and fix the division by zero issue.
🛠️ Command: sed -i 's/10 \/ 0/10 \/ 1/g' script.py
Execute? (Y/n/c): c
💬 Comment: Actually, check what the correct divisor should be
🤖 Plan: You're right, let me first examine the script to understand the context...
```

### Interactive Controls

When aish proposes a command, you can:
-   `y` or `Enter`: Execute the command
-   `n`: Stop the agent
-   `c`: Provide a comment to revise the agent's plan

### Memory Management

aish has persistent memory that stores **system state** - durable facts about your environment:

```bash
$ @aish remember that I prefer vim over nano
🧠 Memory Update: Added preference
✓ Memory updated successfully

$ @aish open that config file
🛠️ Command: vim config.yaml   # aish remembers your preference!
```

The memory stores current facts, not history:
- **User preferences**: "prefers vim, uses 4-space indentation"
- **System configuration**: "nginx installed, serves /var/www/html"
- **Project conventions**: "uses Python 3.11 with poetry"
- **Custom setups**: "backup script at ~/scripts/backup.sh"

### Interactive Programs

aish properly handles interactive terminal programs. When you ask to open files in vim, less, htop, etc., they run with full terminal access:

```bash
$ @aish open the log file in vim
🛠️ Command: vim /var/log/app.log
Execute? (Y/n/c): y
# vim opens normally with full interactivity
```

Supported interactive programs: vim, nano, less, htop, man, ssh, tmux, and more.

## ⚙️ Configuration

`aish` is configured via a `config.yaml` file. The setup script automatically creates one for you at `~/.aish/config.yaml`.

**Configuration options:**
-   `model`: The name of the model to use at your endpoint
-   `endpoint_url`: The URL for the chat completions API
-   `api_key`: Optional API key if your service requires authentication
-   `max_context_length`: Maximum context length in tokens before automatic condensation

During setup, aish will:
1. Connect to your endpoint URL
2. Fetch available models automatically
3. Present an interactive menu to select your preferred model
4. Configure everything automatically

### Supported Providers

- **Local LLMs**: Ollama, vLLaMA, LocalAI, and other OpenAI-compatible servers
- **Commercial APIs**: OpenAI, Kimi Code API, and other OpenAI-compatible providers

For **Kimi Code API**, use:
- Endpoint: `https://api.kimi.com/coding/v1`
- Model: `kimi-for-coding`
- API key from your Kimi membership page

### Context Management

aish automatically manages conversation context to prevent exceeding your model's context window. When the context reaches the configured maximum, it intelligently condenses older messages while preserving important information.

**How it works:**
1. When context reaches 100% of `max_context_length`, condensation begins
2. The oldest half of the conversation is summarized by the LLM
3. The summary replaces the old messages, keeping recent context intact
4. The conversation continues with the summary + recent messages

**Configuration:**

```yaml
# Maximum context length in tokens (set based on your model's context window)
# Common values: 4096, 8192, 16384, 32768, 65536, 131072
max_context_length: 8192
```

**Tips:**
- Set this to ~80% of your model's actual context window to leave room for responses
- Larger values allow longer conversations before condensation
- Condensation preserves: original request, tool results, decisions, and outcomes

## 🔍 Web Search & Built-in Tools

aish comes with built-in tools that work out of the box:

### Available Tools

| Tool | Description | Example |
|------|-------------|---------|
| `bash_exec` | Execute shell commands | `@aish list all Python files` |
| `file_read` | Read file contents | `@aish show me the config file` |
| `file_edit` | Edit files with diff preview | `@aish change DEBUG to True in config.py` |
| `web_search` | Search the web via DuckDuckGo | `@aish search for Python async best practices` |
| `web_fetch` | Fetch and read a web page | `@aish read the contents of example.com` |

### File Editing with Diff Preview

When aish edits files, it uses a safe search-and-replace approach that always shows you a diff before applying changes:

```bash
$ @aish change the port from 8080 to 3000 in server.py
🤖 Plan: I'll update the port number in your server configuration.
✏️ Edit File: file_edit({"file_path": "server.py", "old_text": "port = 8080", "new_text": "port = 3000"})
Execute? (Y/n/c): y
📝 Diff: server.py
╭────────────────────────────────────────────────────────────╮
│ --- a/server.py                                            │
│ +++ b/server.py                                            │
│ @@ -1,3 +1,3 @@                                            │
│ -port = 8080                                               │
│ +port = 3000                                               │
│  host = "localhost"                                        │
╰────────────────────────────────────────────────────────────╯
Apply these changes? (Y/n): y
✓ Successfully updated server.py
```

This approach:
- Shows exactly what will change before modifying any file
- Requires explicit approval for all file modifications
- Works for any file including configuration, code, and memory

### Web Search

aish supports multiple search backends. By default, it uses DuckDuckGo which requires **no API key** and works instantly.

```bash
$ @aish what's the latest news about Rust programming language
🤖 Plan: I'll search the web for recent Rust news.
🔍 Web Search: web_search({"query": "Rust programming language news 2025", "max_results": 5})
Execute? (Y/n/c): y
📄 Result: ## Search Results for: Rust programming language news 2025
### 1. Rust 2025 Roadmap Announced...
```

### Search Backends

| Backend | Description | Setup Required |
|---------|-------------|----------------|
| **DuckDuckGo** | Default search, no setup needed | None |
| **SearxNG** | Privacy-respecting metasearch engine | Self-hosted instance |
| **Perplexica** | AI-powered search with answers | Self-hosted instance |

### Configuration Options

In `~/.aish/config.yaml`:

```yaml
# Enable/disable web search (default: true)
web_search_enabled: true

# Auto-accept web search requests without prompting (default: false)
web_search_auto_accept: false

# Search backend: "duckduckgo" (default), "searxng", or "perplexica"
search_backend: "duckduckgo"

# SOCKS5 proxy for web requests (optional)
web_proxy: ""
```

### SearxNG Configuration

[SearxNG](https://github.com/searxng/searxng) is a privacy-respecting metasearch engine that aggregates results from multiple search engines.

```yaml
search_backend: "searxng"
searxng_url: "http://localhost:8888"
```

**Note:** Your SearxNG instance must have JSON format enabled. Add this to your SearxNG `settings.yml`:

```yaml
search:
  formats:
    - html
    - json
```

### Perplexica Configuration

[Perplexica](https://github.com/ItzCrazyKns/Perplexica) is an AI-powered search engine that provides intelligent answers with sources.

```yaml
search_backend: "perplexica"
perplexica_url: "http://localhost:3000"
perplexica_mode: "balanced"  # speed, balanced, or quality
```

Perplexica auto-detects available AI models. For manual configuration:

```yaml
perplexica_chat_provider: ""        # Provider ID from /api/providers
perplexica_chat_model: ""           # Model key (e.g., "gpt-4o-mini")
perplexica_embedding_provider: ""   # Embedding provider ID
perplexica_embedding_model: ""      # Embedding model key
```

### Other Options

- **web_search_enabled**: Set to `false` to disable web access entirely
- **web_search_auto_accept**: Set to `true` to skip confirmation prompts for web searches
- **web_proxy**: Configure a SOCKS5 proxy if you need one for internet access

## 🔌 MCP Server Support

aish supports the [Model Context Protocol (MCP)](https://modelcontextprotocol.io/), allowing you to extend its capabilities with external tools like database access, web search, GitHub integration, and more.

### Configuration

Create `~/.aish/mcp.json` to configure MCP servers. An example template is provided:

```bash
cp ~/Software/aish/mcp.json.example ~/.aish/mcp.json
```

### Example Configuration

```json
{
  "servers": {
    "filesystem": {
      "transport": "stdio",
      "command": "npx",
      "args": ["-y", "@modelcontextprotocol/server-filesystem", "/home/user/projects"]
    },
    "github": {
      "transport": "stdio",
      "command": "npx",
      "args": ["-y", "@modelcontextprotocol/server-github"],
      "env": {
        "GITHUB_TOKEN": "${GITHUB_TOKEN}"
      }
    },
    "remote-api": {
      "transport": "sse",
      "url": "https://mcp.example.com/sse",
      "headers": {
        "Authorization": "Bearer ${MCP_API_TOKEN}"
      }
    }
  }
}
```

### Supported Transports

- **stdio**: Spawns MCP server as a subprocess (most common for local tools)
- **sse**: Connects to remote MCP servers via Server-Sent Events

### Using MCP Tools

When MCP servers are configured, aish automatically discovers available tools and presents them to the LLM. The agent can then use these tools alongside bash commands:

```bash
$ @aish search for issues mentioning authentication in our repo
🤖 Plan: I'll use the GitHub MCP server to search for issues.
🔌 MCP Tool Call: search_issues({"query": "authentication", "repo": "user/repo"})
Execute MCP tool? (Y/n/c): y
📄 MCP Tool Result: Found 3 issues...
```

### Popular MCP Servers

- **@modelcontextprotocol/server-filesystem** - File system operations
- **@modelcontextprotocol/server-github** - GitHub API integration
- **@modelcontextprotocol/server-postgres** - PostgreSQL database access
- **@anthropic/mcp-server-brave-search** - Web search via Brave
- **@anthropic/mcp-server-puppeteer** - Browser automation
- **@anthropic/mcp-server-sqlite** - SQLite database access

See `mcp.json.example` for more server configurations.

## 📝 Bash Session Logging (Optional)

AISH includes optional bash session logging that creates a real-time carbon copy of your terminal session. This enables aish to be truly context-aware.

**To enable bash session logging:**

1. Add this line to your `~/.bashrc`:
   ```bash
   source ~/Software/aish/bashrc_extension_aish.sh
   ```

2. Restart your terminal

The logging automatically creates session files in `~/.local/share/bash_sessions/` and cleans up files older than 7 days.

**Note:** The logging functionality is completely separate from the `@aish` command and can be used independently.

## 🔄 Updating aish

To update `aish` to the latest version:
```bash
cd ~/Software/aish
bash setup.sh  # This will update paths and configuration
```

Or manually:
```bash
cd ~/Software/aish
git pull
pip install -r requirements.txt
```

## 🛠️ How It Works

- **`setup.sh`** - Automated installation script that sets up everything including model discovery
- **`aish.py`** - Main AI assistant with rich terminal UI and memory management
- **`tools.py`** - Built-in tools: bash execution, file reading/editing, web search, and web fetch
- **`mcp_manager.py`** - MCP server support for extended functionality
- **`bashrc_extension_aish.sh`** - BASH session logging for context awareness
- **`config.yaml.example`** - Template for main configuration
- **`mcp.json.example`** - Template for MCP server configuration
- **Dynamic path resolution** - Works from any installation directory

### Configuration Files

All user configuration is stored in `~/.aish/`:
- `config.yaml` - LLM endpoint, model, and web search settings
- `memory.md` - Persistent memory storage
- `mcp.json` - MCP server configuration (optional)

The system is designed to be completely portable and self-configuring.