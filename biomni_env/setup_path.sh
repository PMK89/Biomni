#!/bin/bash
# Added by biomni setup
# Remove any old paths first to avoid duplicates
PATH=$(echo $PATH | tr ':' '\n' | grep -v "biomni_tools/bin" | tr '\n' ':' | sed 's/:$//')
export PATH="/home/pmk/Biomni/biomni_env/biomni_tools/bin:$PATH"
