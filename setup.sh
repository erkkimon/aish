#!/bin/bash

# AISH Installation Script
# This script sets up the aish command and configures bash integration

set -e

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

# Function to print colored output
print_success() {
    echo -e "${GREEN}✓${NC} $1"
}

print_error() {
    echo -e "${RED}✗${NC} $1"
}

print_info() {
    echo -e "${YELLOW}ℹ${NC} $1"
}

# Get the directory where this script is located
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
AISH_PROJECT_DIR="$SCRIPT_DIR"

print_info "AISH project directory: $AISH_PROJECT_DIR"

# Find Python interpreter
PYTHON_PATH=""
if [ -f "$AISH_PROJECT_DIR/venv/bin/python" ]; then
    PYTHON_PATH="$AISH_PROJECT_DIR/venv/bin/python"
    print_success "Found Python virtual environment"
elif command -v python3 &> /dev/null; then
    PYTHON_PATH="$(command -v python3)"
    print_info "Using system Python 3: $PYTHON_PATH"
elif command -v python &> /dev/null; then
    PYTHON_PATH="$(command -v python)"
    print_info "Using system Python: $PYTHON_PATH"
else
    print_error "No Python interpreter found. Please install Python 3."
    exit 1
fi

# Check if aish.py exists
if [ ! -f "$AISH_PROJECT_DIR/aish.py" ]; then
    print_error "aish.py not found in $AISH_PROJECT_DIR"
    exit 1
fi
print_success "Found aish.py"

# Create virtual environment if it doesn't exist
VENV_PATH="$AISH_PROJECT_DIR/venv"
if [ ! -d "$VENV_PATH" ]; then
    print_info "Creating virtual environment..."
    "$PYTHON_PATH" -m venv venv
    print_success "Created virtual environment"
    
    # Activate virtual environment and install requirements
    print_info "Installing requirements..."
    source "$VENV_PATH/bin/activate"
    pip install -r requirements.txt
    print_success "Installed requirements"
    
    # Update PYTHON_PATH to use the virtual environment
    PYTHON_PATH="$VENV_PATH/bin/python"
else
    print_info "Virtual environment already exists"
fi

# Create user config directory if it doesn't exist
USER_CONFIG_DIR="$HOME/.aish"
if [ ! -d "$USER_CONFIG_DIR" ]; then
    mkdir -p "$USER_CONFIG_DIR"
    print_success "Created user config directory: $USER_CONFIG_DIR"
fi

# Function to fetch available models from API endpoint
fetch_models() {
    local endpoint_url="$1"
    local api_key="$2"
    
    # Construct models endpoint URL
    local models_url="${endpoint_url%/}"
    if [[ "$models_url" == *"/v1" ]]; then
        models_url="${models_url}/models"
    elif [[ "$models_url" == *"/v1/" ]]; then
        models_url="${models_url}models"
    else
        models_url="${models_url}/v1/models"
    fi
    
    # Make API call to get models
    local auth_header=""
    if [ -n "$api_key" ] && [ "$api_key" != "not-needed" ]; then
        auth_header="-H \"Authorization: Bearer $api_key\""
    fi
    
    # Use curl to fetch models, suppress errors
    local response
    response=$(curl -s -w "\n%{http_code}" $auth_header "$models_url" 2>/dev/null)
    local http_code=$(echo "$response" | tail -n1)
    local json_response=$(echo "$response" | head -n-1)
    
    if [ "$http_code" = "200" ] && [ -n "$json_response" ]; then
        # Parse JSON to extract model names using Python for reliability
        local models
        models=$(echo "$json_response" | python3 -c "
import sys
import json
try:
    data = json.load(sys.stdin)
    if 'data' in data:
        models = [model['id'] for model in data['data']]
    elif 'models' in data:
        models = [model['name'] for model in data['models']]
    elif 'object' in data and data['object'] == 'list':
        models = [item['id'] for item in data.get('data', [])]
    else:
        models = []
    for model in models:
        print(model)
except:
    pass
" 2>/dev/null)
        
        if [ -n "$models" ]; then
            echo "$models"
            return 0
        fi
    fi
    
    return 1
}

# Function to display interactive model selection menu
# This function prints the model list to stderr and the selected model to stdout
select_model_interactive() {
    local models_list="$1"
    local default_model="$2"
    
    # Convert models list to array
    IFS=$'\n' read -r -d '' -a models_array <<< "$models_list"
    
    if [ ${#models_array[@]} -eq 0 ]; then
        return 1
    fi
    
    # Display model list to stderr (so it shows to user but doesn't get captured)
    echo -e "${YELLOW}ℹ${NC} Available models (enter number to select):" >&2
    for i in "${!models_array[@]}"; do
        echo " $((i+1))) ${models_array[i]}" >&2
    done
    
    # Get user selection
    while true; do
        read -p "Select a model (1-${#models_array[@]}): " selection
        
        # Validate input
        if [[ "$selection" =~ ^[0-9]+$ ]] && [ "$selection" -ge 1 ] && [ "$selection" -le "${#models_array[@]}" ]; then
            # Return the selected model name to stdout
            echo "${models_array[$((selection-1))]}"
            return 0
        else
            echo -e "${RED}✗${NC} Invalid selection. Please enter a number between 1 and ${#models_array[@]}." >&2
        fi
    done
}

# Copy config.yaml.example to user config directory if it doesn't exist
USER_CONFIG_PATH="$USER_CONFIG_DIR/config.yaml"
if [ ! -f "$USER_CONFIG_PATH" ]; then
    if [ -f "$AISH_PROJECT_DIR/config.yaml.example" ]; then
        cp "$AISH_PROJECT_DIR/config.yaml.example" "$USER_CONFIG_PATH"
        print_success "Copied config.yaml.example to $USER_CONFIG_PATH"
        
        # Prompt user for configuration values
        print_info "Please provide configuration values (press Enter to use defaults):"
        
        # Read default values from the example file
        DEFAULT_MODEL=$(grep -E '^model:' "$USER_CONFIG_PATH" | cut -d' ' -f2- | tr -d '[:space:]')
        DEFAULT_ENDPOINT=$(grep -E '^endpoint_url:' "$USER_CONFIG_PATH" | cut -d' ' -f2- | tr -d '[:space:]')
        DEFAULT_API_KEY=$(grep -E '^api_key:' "$USER_CONFIG_PATH" | cut -d' ' -f2- | tr -d '[:space:]' | sed 's/#.*//')
        
        # Get endpoint URL from user first
        read -p "Endpoint URL [$DEFAULT_ENDPOINT]: " USER_ENDPOINT
        USER_ENDPOINT=${USER_ENDPOINT:-$DEFAULT_ENDPOINT}
        
        # Get API key from user if needed
        read -p "API key [not-needed]: " USER_API_KEY
        USER_API_KEY=${USER_API_KEY:-$DEFAULT_API_KEY}
        
        # Try to fetch available models
        print_info "Fetching available models from $USER_ENDPOINT..."
        AVAILABLE_MODELS=$(fetch_models "$USER_ENDPOINT" "$USER_API_KEY")
        
        USER_MODEL=""
        if [ -n "$AVAILABLE_MODELS" ]; then
            # Use interactive model selection
            SELECTED_MODEL=$(select_model_interactive "$AVAILABLE_MODELS" "$DEFAULT_MODEL")
            if [ -n "$SELECTED_MODEL" ]; then
                USER_MODEL="$SELECTED_MODEL"
                print_success "Selected model: $USER_MODEL"
            else
                print_info "No model selected, using default"
                USER_MODEL="$DEFAULT_MODEL"
            fi
        else
            print_error "Could not fetch models from endpoint: $USER_ENDPOINT"
            print_info "Please check:"
            print_info "  1. The endpoint URL is correct and accessible"
            print_info "  2. The API service is running"
            print_info "  3. The endpoint supports the /models API endpoint"
            print_info "  4. Any required API key is provided"
            echo ""
            read -p "Enter model name manually [$DEFAULT_MODEL]: " USER_MODEL
            USER_MODEL=${USER_MODEL:-$DEFAULT_MODEL}
            print_info "Using model: $USER_MODEL"
        fi
        
        # Create config file with user values using a more reliable method
        # Read the original example config and replace values
        
        # Create a temporary config with updated values
        cat > "$USER_CONFIG_PATH.tmp" << EOF
# Configuration for the aish agent.
model: $USER_MODEL
endpoint_url: $USER_ENDPOINT
EOF
        
        # Add API key if provided
        if [ -n "$USER_API_KEY" ] && [ "$USER_API_KEY" != "not-needed" ]; then
            echo "api_key: $USER_API_KEY" >> "$USER_CONFIG_PATH.tmp"
        else
            echo "# api_key: not-needed # Uncomment if you use a provider that requires an api key" >> "$USER_CONFIG_PATH.tmp"
        fi
        
        # Replace the original config with the updated one
        mv "$USER_CONFIG_PATH.tmp" "$USER_CONFIG_PATH"
        
        # Verify the config was updated correctly
        print_success "Configuration file created at $USER_CONFIG_PATH"
        print_info "Model configured: $USER_MODEL"
        print_info "Endpoint configured: $USER_ENDPOINT"
        
        print_success "Configuration file created at $USER_CONFIG_PATH"
    else
        print_error "config.yaml.example not found in $AISH_PROJECT_DIR"
        exit 1
    fi
else
    print_info "User config file already exists at $USER_CONFIG_PATH"
fi

# Add configuration to ~/.bashrc if not already present
BASHRC_PATH="$HOME/.bashrc"

if [ -f "$BASHRC_PATH" ]; then
    if grep -q "export AISH_DIR=" "$BASHRC_PATH"; then
        print_info "AISH configuration already included in $BASHRC_PATH"
    else
        print_info "Adding AISH configuration to $BASHRC_PATH"
        echo "" >> "$BASHRC_PATH"
        echo "# AISH Configuration" >> "$BASHRC_PATH"
        echo "export AISH_DIR=\"$AISH_PROJECT_DIR\"" >> "$BASHRC_PATH"
        echo "@aish() { \"\$AISH_DIR/venv/bin/python\" \"\$AISH_DIR/aish.py\" \"\$@\"; }" >> "$BASHRC_PATH"
        echo "export -f @aish" >> "$BASHRC_PATH"
        echo "source \${AISH_DIR}/bashr_extension_logging.sh" >> "$BASHRC_PATH"
        print_success "Added AISH configuration to $BASHRC_PATH"
    fi
else
    print_info "Creating $BASHRC_PATH"
    echo "# AISH Configuration" > "$BASHRC_PATH"
    echo "export AISH_DIR=\"$AISH_PROJECT_DIR\"" >> "$BASHRC_PATH"
    echo "@aish() {" >> "$BASHRC_PATH"
    echo "    \"\$AISH_DIR/venv/bin/python\" \"\$AISH_DIR/aish.py\" \"\$@\"" >> "$BASHRC_PATH"
    echo "}" >> "$BASHRC_PATH"
    echo "export -f @aish" >> "$BASHRC_PATH"
    print_success "Created $BASHRC_PATH with AISH configuration"
fi

# Also handle bash_profile if it exists
# BASHPROFILE_PATH="$HOME/.bash_profile"
# if [ -f "$BASHPROFILE_PATH" ]; then
#     if ! grep -q "export AISH_DIR=" "$BASHPROFILE_PATH"; then
#         print_info "Adding AISH configuration to $BASHPROFILE_PATH"
#         echo "" >> "$BASHPROFILE_PATH"
#         echo "# AISH Configuration" >> "$BASHPROFILE_PATH"
#         echo "export AISH_DIR=\"$AISH_PROJECT_DIR\"" >> "$BASHPROFILE_PATH"
#         echo "@aish() {" >> "$BASHPROFILE_PATH"
#         echo "    \"\$AISH_DIR/venv/bin/python\" \"\$AISH_DIR/aish.py\" \"\$@\"" >> "$BASHPROFILE_PATH"
#         echo "}" >> "$BASHPROFILE_PATH"
#         echo "export -f @aish" >> "$BASHPROFILE_PATH"
#         echo "source \$\{AISH_DIR\}/bashr_extension_logging.sh" >> "$BASHPROFILE_PATH"
#         echo "# trukene" >> "$BASHPROFILE_PATH"
#         print_success "Added AISH configuration to $BASHPROFILE_PATH"
#     fi
# fi

print_success "Installation completed successfully!"
print_info "Please restart your terminal or run: source $CONFIG_FILE"
print_info "Then you can use: @aish <your command>"
