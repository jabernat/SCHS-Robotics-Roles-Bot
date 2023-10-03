#!/usr/bin/env bash
# Starts the SCHS-Robotics-Roles-Bot that logs into Discord and answers commands
# until closed.




# Install missing libraries.
echo 'Installing Dependencies:'
python3 -m pip install --requirement 'requirements.txt' \
    | grep 'Requirement already satisfied: '




# Perform static analysis type-checking if available.
if [ -x "$(command -v mypy)" ]; then
    # Mypy is installed.
    echo 'Type Checking:'

    # Analyze Python script for data-flow/data-type mistakes using Mypy:
    # https://github.com/python/mypy

    mypy 'roles_bot.py' --config-file 'mypy.ini' --cache-dir '.mypy_cache'
    # Note: Problems do not stop execution.

    echo
fi




echo 'Executing:'
python3 'roles_bot.py' "$@"
