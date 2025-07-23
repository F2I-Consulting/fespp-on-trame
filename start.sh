#!/bin/bash
# Start Xvfb virtual display
Xvfb :99 -screen 0 1920x1080x24 -ac +extension GLX +render -noreset &
export DISPLAY=:99

# Wait for Xvfb (Apache needs it ready)
sleep 2

# Debug output
echo "Starting Trame application with GPU acceleration"
echo "EGL Status:"
glxinfo -B | grep -i "device\|renderer"

# Run the original trame entrypoint
exec /opt/trame/entrypoint.sh "$@"