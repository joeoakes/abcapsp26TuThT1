#!/usr/bin/env bash
set -euo pipefail

SESSION="maze_brain2"

# If session already exists, just attach
if tmux has-session -t "$SESSION" 2>/dev/null; then
  echo "tmux session '$SESSION' already running. Attaching..."
  exec tmux attach -t "$SESSION"
fi

tmux new-session -d -s "$SESSION" -n brain

# Pane 1: uvicorn (maze_brain2)
tmux send-keys -t "$SESSION:brain" \
  "cd ~/abcapsp26TuThT1/maze_brain2 && source .venv/bin/activate && uvicorn maze_brain:app --host 0.0.0.0 --port 8001 --log-level info" C-m

# Pane 2: ollama serve
tmux split-window -h -t "$SESSION:brain"
tmux send-keys -t "$SESSION:brain.1" "ollama serve" C-m

tmux select-layout -t "$SESSION:brain" even-horizontal

echo "Started:"
echo " - uvicorn on :8001"
echo " - ollama serve"
echo ""
echo "Attach with: tmux attach -t $SESSION"
echo "Stop with:   tmux kill-session -t $SESSION"
exec tmux attach -t "$SESSION"
