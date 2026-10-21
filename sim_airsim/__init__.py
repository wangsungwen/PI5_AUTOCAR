"""AirSim simulation bridge for RPI5_AutoCAR.

The real car code (autocar.autopilot.Autopilot) only needs two objects:
  camera.capture_bgr()            -> numpy BGR frame
  motor.set_enabled(...) / motor.drive_tank(left, right)
This package provides AirSim-backed versions of both, so the same Autopilot,
PID and YOLO26 models run unchanged inside the simulator.
"""
