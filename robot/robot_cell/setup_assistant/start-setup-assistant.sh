#!/bin/bash
set -e

# 1. Start virtual framebuffer
Xvfb :1 -screen 0 1600x900x24 -ac +extension GLX +render &
XVFB_PID=$!

# 2. Wait until the display is actually ready
echo "Waiting for Xvfb..."
until xdpyinfo -display :1 >/dev/null 2>&1; do sleep 0.2; done
echo "Xvfb ready."

# 3. Start VNC server on the virtual display (no password, port 5900)
x11vnc -display :1 -nopw -listen 0.0.0.0 -forever -shared -bg -o /tmp/x11vnc.log
echo "x11vnc started."

# 4. Start noVNC websocket proxy — browse to http://localhost:8080/vnc.html
websockify --web /usr/share/novnc 8080 localhost:5900 &
echo "noVNC listening on :8080"

# 5. Source ROS environment and launch MoveIt Setup Assistant
source /opt/ros/noetic/setup.bash
if [ -f /root/catkin_ws/devel/setup.bash ]; then
    source /root/catkin_ws/devel/setup.bash
fi

export DISPLAY=:1
export LIBGL_ALWAYS_SOFTWARE=1
export QT_X11_NO_MITSHM=1

echo "Launching MoveIt Setup Assistant..."
exec roslaunch --wait moveit_setup_assistant setup_assistant.launch
