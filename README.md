# AI for your SH

Delegate shell tasks to aish who lives in the terminal. You can do in-line chatting with aish. Just mention `@aish` and send a request and `@aish` will complete it for you.

`aish` is a simple, interactive AI assistant that runs in your shell. It uses a local large language model (LLM) to help you accomplish tasks by proposing and executing shell commands for you.

## 1. Usage

To run the agent, use the `@aish` alias with your command as arguments.

**Example of in-line chatting:**
```bash
$ ls -l
total 4
-rw-r--r-- 1 user user 123 Nov  7 14:23 my_file.txt

$ @aish what is in my_file.txt
... aish will show you the content of the file ...

$ rm my_file.txt
$
```

The agent will then propose a plan and a command. You can approve, deny, or comment on its proposal:
-   `y` or `Enter`: Execute the command.
-   `n`: Stop the agent.
-   `c`: Provide a comment to revise the agent's plan.

## 2. Setup

**Prerequisites:**
- Python 3.12+
- A running OpenAI-compatible LLM endpoint. `aish` is designed with a local-first approach, compatible with local LLM runners like [vLLaMA](https://github.com/erkkimon/vllama) and [Ollama](https://github.com/ollama/ollama). It also works with OpenAI and any other OpenAI-compatible API.

**Installation:**

1.  **Clone the repository:**
    ```bash
    git clone https://github.com/erkkimon/aish ~/Software/aish
    cd ~/Software/aish
    ```

2.  **Create and activate a virtual environment:**
    ```bash
    python3.12 -m venv venv312
    source venv312/bin/activate
    ```

3.  **Install the required packages:**
    ```bash
    pip install -r requirements.txt
    ```
4.  **Add alias to your shell's configuration file:**
    ```bash
    echo "alias @aish='~/Software/aish/venv312/bin/python ~/Software/aish/aish.py'" >> ~/.bashrc
    # or ~/.zshrc
    ```
    Then restart your shell or source the config file.

## 3. Configuration

`aish` is configured via a `config.yaml` file. The first time you run the script, it will automatically create a default one for you.

**Default `config.yaml`:**
```yaml
# Configuration for the aish agent.
model: Devstral-Small-2505-abliterated.i1-Q2_K_S
endpoint_url: http://localhost:11435/v1/chat/completions
# api_key: not-needed # Uncomment if you use a provider that requires an api key
```

-   `model`: The name of the model to use at your endpoint.
-   `endpoint_url`: The URL for the chat completions API.
-   `api_key`: Optional. If your service requires an API key, uncomment the line and replace `not-needed` with your key.

## 4. Updating aish

To update `aish` to the latest version:
```bash
cd ~/Software/aish
source venv312/bin/activate
git pull
pip install -r requirements.txt
```