#!/bin/bash
# AISH Shell Extension with Dynamic Paths
# This script provides both the @aish function and shell session logging
# Compatible with both Bash and ZSH

# Check if AISH_DIR is set, otherwise use default
if [ -z "$AISH_DIR" ]; then
    export AISH_DIR="$HOME/Git/aish"
fi

# Define the @aish function using AISH_DIR
@aish() {
    "$AISH_DIR/venv/bin/python" "$AISH_DIR/aish.py" "$@"
}

# Export function for bash (zsh handles this differently)
if [ -n "$BASH_VERSION" ]; then
    export -f @aish
fi

# Shell session logging - only for interactive sessions
if [[ $- == *i* ]] && [[ -z $SCRIPT_RUNNING ]]; then
  export SCRIPT_RUNNING=1

  # Create log directory
  LOGDIR=$HOME/.aish/logs
  mkdir -p "$LOGDIR"
  export BASH_SESSION_CARBON_COPY=$LOGDIR/session_$(date +%Y%m%d_%H%M%S)_$$.log
  find "$LOGDIR" -name 'session_*.log' -mtime +7 -delete 2>/dev/null

  # turn off terminal noise (bash only)
  if [ -n "$BASH_VERSION" ]; then
    printf '\e]777;off\a\e]3008;off\a\e[?1000l\e[?1002l\e[?1006l\e[?2004l\e[?1l\e>'
    stty -echoctl 2>/dev/null
  fi

  # -----  LIVE TEE  -----
  # script -> stdout;  we duplicate that stream with tee so you can
  # "tail -f $BASH_SESSION_CARBON_COPY" in another pane *while* you work.
  
  # Use appropriate shell for script command
  if [ -n "$BASH_VERSION" ]; then
    SHELL_CMD="bash --login"
  elif [ -n "$ZSH_VERSION" ]; then
    SHELL_CMD="zsh --login"
  else
    SHELL_CMD="$SHELL --login"
  fi
  
  script -q -c "$SHELL_CMD" /dev/null |
    tee "$BASH_SESSION_CARBON_COPY"

  # (optional) compress escapes after session ends
  # sed -i -E 's/\x1B(\[[0-9;]*[a-zA-Z]|\][0-9;:]*(\x07|\x1B\\)|\(.\x1B\\|\x1B\\|[@A-Z\\]|\([A-Z])//g' "$BASH_SESSION_CARBON_COPY"

  exit
fi
