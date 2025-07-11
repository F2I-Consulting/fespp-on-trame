#!/bin/bash
# Start Xvfb virtual display
Xvfb :99 -screen 0 1920x1080x24 -ac +extension GLX +render -noreset &
export DISPLAY=:99

# Wait for Xvfb (Apache needs it ready)
sleep 2

# Debug output
echo "Starting Trame application with GPU acceleration"
echo "=> Apache with Xvfb support <="
echo "EGL Configuration:"
echo "PV_USE_VTKGPI=${PV_USE_VTKGPI}"
echo "VTK_OPENGL_HAS_EGL=${VTK_OPENGL_HAS_EGL}"
echo "VTK_USE_X=${VTK_USE_X}"
echo "EGL Status:"
glxinfo -B | grep -i "device\|renderer"

# Run the original trame entrypoint
exec /opt/trame/entrypoint.sh "$@"