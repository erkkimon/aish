#!/bin/bash
# AISH Bash Extension with Dynamic Paths
# This script provides both the @aish function and bash session logging

# Check if AISH_DIR is set, otherwise use default
if [ -z "$AISH_DIR" ]; then
    export AISH_DIR="$HOME/Git/aish"
fi

# Define the @aish function using AISH_DIR
@aish() {
    "$AISH_DIR/venv/bin/python" "$AISH_DIR/aish.py" "$@"
}
export -f @aish

# ~/.bashrc  –  real-time carbon-copy (live while session runs)
if [[ $- == *i* ]] && [[ -z $SCRIPT_RUNNING ]]; then
  export SCRIPT_RUNNING=1

  LOGDIR=$HOME/.aish/logs
  mkdir -p "$LOGDIR"
  export BASH_SESSION_CARBON_COPY=$LOGDIR/session_$(date +%Y%m%d_%H%M%S)_$$.log
  find "$LOGDIR" -name 'session_*.log' -mtime +7 -delete 2>/dev/null

  # turn off terminal noise
  printf '\e]777;off\a\e]3008;off\a\e[?1000l\e[?1002l\e[?1006l\e[?2004l\e[?1l\e>'
  stty -echoctl 2>/dev/null

  # -----  LIVE TEE  -----
  # script -> stdout;  we duplicate that stream with tee so you can
  # "tail -f $BASH_SESSION_CARBON_COPY" in another pane *while* you work.
  script -q -c "bash --login" /dev/null |
    tee "$BASH_SESSION_CARBON_COPY"

  # (optional) compress escapes after session ends
  # sed -i -E 's/\x1B(\[[0-9;]*[a-zA-Z]|\][0-9;:]*(\x07|\x1B\\)|\(.\x1B\\|\x1B\\|[@A-Z\\]|\([A-Z])//g' "$BASH_SESSION_CARBON_COPY"

  exit
fi
