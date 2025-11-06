# aish - AI Shell Assistant

`aish` is a simple, interactive AI assistant that runs in your shell. It uses a local large language model (LLM) to help you accomplish tasks by proposing and executing shell commands for you.

## 1. Setup

**Prerequisites:**
- Python 3.10+
- A running OpenAI-compatible LLM endpoint (like vLLM, Ollama, etc.)

**Installation:**

1.  **Clone the repository:**
    ```bash
    git clone <repository_url>
    cd aish
    ```

2.  **Create and activate a virtual environment:**
    ```bash
    python3 -m venv venv312
    source venv312/bin/activate
    ```

3.  **Install the required packages:**
    ```bash
    pip install -r requirements.txt
    ```

## 2. Configuration

`aish` is configured via a `config.json` file. The first time you run the script, it will automatically create a default one for you.

**Default `config.json`:**
```json
{
  "_comment": "Configuration for the aish agent. The api_key is optional and only needed for certain services.",
  "model": "Devstral-Small-2505-abliterated.i1-Q2_K_S",
  "endpoint_url": "http://localhost:11435/v1/chat/completions",
  "api_key": "not-needed"
}
```

-   `model`: The name of the model to use at your endpoint.
-   `endpoint_url`: The URL for the chat completions API.
-   `api_key`: Optional. If your service requires an API key, replace `"not-needed"` with your key. Otherwise, leave it as is.

## 3. Usage

To run the agent, execute the `aish.py` script with your command as arguments.

**Example:**
```bash
./aish.py find out if goose has been installed on this system
```

The agent will then propose a plan and a command. You can approve, deny, or comment on its proposal:
-   `y` or `Enter`: Execute the command.
-   `n`: Stop the agent.
-   `c`: Provide a comment to revise the agent's plan.

### Shell Alias (Recommended)

For easier access, add the following alias to your shell's configuration file (`~/.zshrc`, `~/.bashrc`, etc.). Make sure to replace `/path/to/aish` with the actual absolute path to this project's directory.

```bash
# aish - AI Shell Assistant
alias aish='/path/to/aish/aish.py'
```

After adding the alias and restarting your shell, you can simply run:
```bash
aish list all running docker containers
```
