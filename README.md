# aish - AI Shell Helper

`aish` is a Python-based CLI tool that generates bash scripts for user-defined tasks. It uses a custom, lightweight ReAct-style agent loop to reason and use tools, powered by a local LLM served via vLLM.

## 1. Prerequisites

- **OS**: Arch Linux (or any Linux distribution with Python and Ollama).
- **Python**: Python 3.12.
- **Ollama**: Ensure Ollama is installed and running.
- **LLM Model**: You must have the `huihui_ai/devstral-abliterated:latest` model pulled in Ollama.
  ```bash
  ollama pull huihui_ai/devstral-abliterated:latest
  ```

## 2. Setup

1.  **Create and activate a virtual environment:**
    ```bash
    python3.12 -m venv aish_env
    source aish_env/bin/activate
    ```

2.  **Install dependencies:**
    ```bash
    pip install -r requirements.txt
    ```

## 3. Usage

The `aish` tool requires a local inference server to be running. A helper script `manage_server.sh` is provided to control it.

1.  **Start the Inference Server:**
    Open a new terminal (or use a terminal multiplexer like `tmux`) and run:
    ```bash
    ./manage_server.sh start
    ```
    This will start the server in the background. You can check its status with `./manage_server.sh status`.

2.  **Run `aish`:**
    Execute the main script with a task description. The agent will generate a `task.sh` file in the current directory.
    ```bash
    python aish.py --task "your task description here"
    ```
    For example:
    ```bash
    python aish.py --task "List all files in the current directory, count them, and print the count."
    ```

3.  **Stop the Inference Server:**
    When you are finished, stop the server to free up VRAM.
    ```bash
    ./manage_server.sh stop
    ```

## 4. Alias (Optional)

For easier use, you can add an alias to your `~/.bashrc` or `~/.zshrc`:

```bash
alias aish='python /home/erkkimon/Git/aish-2/aish.py'
```

After adding the alias and reloading your shell, you can run it like this:
```bash
aish --task "your task description"
```
