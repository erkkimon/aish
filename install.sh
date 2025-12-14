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
        
        read -p "Model [$DEFAULT_MODEL]: " USER_MODEL
        read -p "Endpoint URL [$DEFAULT_ENDPOINT]: " USER_ENDPOINT
        
        # Update config file with user values if provided
        if [ -n "$USER_MODEL" ]; then
            sed -i "s/^model:.*/model: $USER_MODEL/" "$USER_CONFIG_PATH"
        fi
        
        if [ -n "$USER_ENDPOINT" ]; then
            sed -i "s|^endpoint_url:.*|endpoint_url: $USER_ENDPOINT|" "$USER_CONFIG_PATH"
        fi
        
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
        echo "@aish() {" >> "$BASHRC_PATH"
        echo "    \"\$AISH_DIR/venv/bin/python\" \"\$AISH_DIR/aish.py\" \"\$@\"" >> "$BASHRC_PATH"
        echo "}" >> "$BASHRC_PATH"
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
