import nebulatk as ntk
from controller import Camera
from vcapture import vcapture
from time import sleep, time
from PIL import Image
import multiprocessing
import cv2
import json
import os
import contextlib


def close():
    _cap = globals().get("cap")
    if _cap:
        with contextlib.suppress(Exception):
            _cap.release()

    _ptz_cam = globals().get("ptz_cam")
    if _ptz_cam:
        with contextlib.suppress(Exception):
            _ptz_cam.close()
    cv2.destroyAllWindows()
    quit()


import atexit
import win32api
import win32con


# (close, logoff, shutdown)
def console_ctrl_handler(event):
    if event in (
        win32con.CTRL_CLOSE_EVENT,
        win32con.CTRL_LOGOFF_EVENT,
        win32con.CTRL_SHUTDOWN_EVENT,
    ):
        atexit._run_exitfuncs()
        return True
    return False


# Register the save function to be called on normal program exit
atexit.register(close)

win32api.SetConsoleCtrlHandler(console_ctrl_handler, True)

if __name__ == "__main__":
    window = ntk.Window(width=300, height=600, closing_command=close).place()

    PAN_SPEED = 7
    TILT_SPEED = 7

    def _cameras_json_path():
        return os.path.join(os.path.dirname(os.path.abspath(__file__)), "cameras.json")

    def _ensure_cameras_json_exists():
        """
        Ensure `cameras.json` exists. If missing, create it with the current default camera
        so the app behaves the same out-of-the-box.

        Format:
          { "cameras": [ { "ip": "...", "type": "ptzoptics" }, ... ] }
        """
        path = _cameras_json_path()
        if os.path.exists(path):
            return
        default = {"cameras": [{"ip": "192.168.0.126", "type": "ptzoptics"}]}
        with contextlib.suppress(Exception):
            with open(path, "w", encoding="utf-8") as f:
                json.dump(default, f, indent=2)

    def _load_cameras():
        _ensure_cameras_json_exists()
        path = _cameras_json_path()
        try:
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
        except Exception:
            return []

        cameras = data.get("cameras", data if isinstance(data, list) else [])
        if not isinstance(cameras, list):
            return []
        normalized = []
        for cam in cameras:
            if not isinstance(cam, dict):
                continue
            ip = cam.get("ip")
            cam_type = cam.get("type") or cam.get("camera_type") or "ptzoptics"
            if isinstance(ip, str) and ip.strip():
                normalized.append({"ip": ip.strip(), "type": str(cam_type)})
        return normalized

    def _rtsp_url_for_ip(ip: str) -> str:
        # Existing behavior uses the SD stream "/2"
        return f"rtsp://{ip}:554/2"

    cameras = _load_cameras()

    # Initialize default camera (first from cameras.json if available, otherwise keep legacy default)
    if cameras:
        _active_index = 0
        ptz_cam = Camera(ip=cameras[0]["ip"], camera_type=cameras[0]["type"])
        _active_rtsp_url = _rtsp_url_for_ip(cameras[0]["ip"])
    else:
        _active_index = None
        ptz_cam = Camera(ip="192.168.0.126")
        _active_rtsp_url = _rtsp_url_for_ip("192.168.0.126")

    def switch_camera(index: int):
        """
        Switch to camera N (0-based).
        If the camera doesn't exist in cameras.json, do nothing.
        Ensures the RTSP feed is stopped and restarted, and ptz_cam is replaced.
        """
        global cameras, ptz_cam, cap, _active_index, _active_rtsp_url

        if not isinstance(index, int) or index < 0:
            return
        if index >= len(cameras):
            return  # default: do nothing
        if _active_index == index:
            return

        cam_cfg = cameras[index]
        new_ip = cam_cfg["ip"]
        new_type = cam_cfg["type"]

        # Stop old RTSP feed first (so the while-loop stops using it promptly)
        if cap:
            with contextlib.suppress(Exception):
                cap.release()

        # Close old camera socket
        if ptz_cam:
            with contextlib.suppress(Exception):
                ptz_cam.close()

        # Swap PTZ camera object
        ptz_cam = Camera(ip=new_ip, camera_type=new_type)

        # Start new RTSP feed
        _active_rtsp_url = _rtsp_url_for_ip(new_ip)
        cap = vcapture(_active_rtsp_url)
        cap.start()

        _active_index = index

    # Camera selector buttons at top of window
    for i in range(4):
        ntk.Button(
            window,
            text=f"Camera {i+1}",
            height=25,
            width=75,
            command=lambda i=i: switch_camera(i),
        ).place(75 * i, 0)

    left_btn = ntk.Button(
        window,
        text="←",
        height=50,
        width=50,
        command=lambda: ptz_cam.pan_left(PAN_SPEED, TILT_SPEED),
        command_off=lambda: ptz_cam.pan_stop(),
    ).place(75, 100)
    right_btn = ntk.Button(
        window,
        text="→",
        height=50,
        width=50,
        command=lambda: ptz_cam.pan_right(PAN_SPEED, TILT_SPEED),
        command_off=lambda: ptz_cam.pan_stop(),
    ).place(175, 100)

    left_btn = ntk.Button(
        window,
        text="←",
        height=50,
        width=50,
        command=lambda: ptz_cam.pan_left(PAN_SPEED * 2, TILT_SPEED * 2),
        command_off=lambda: ptz_cam.pan_stop(),
    ).place(25, 100)
    right_btn = ntk.Button(
        window,
        text="→",
        height=50,
        width=50,
        command=lambda: ptz_cam.pan_right(PAN_SPEED * 2, TILT_SPEED * 2),
        command_off=lambda: ptz_cam.pan_stop(),
    ).place(225, 100)

    up_btn = ntk.Button(
        window,
        text="↑",
        height=50,
        width=50,
        command=lambda: ptz_cam.pan_up(PAN_SPEED, TILT_SPEED),
        command_off=lambda: ptz_cam.pan_stop(),
    ).place(125, 50)
    down_btn = ntk.Button(
        window,
        text="↓",
        height=50,
        width=50,
        command=lambda: ptz_cam.pan_down(PAN_SPEED, TILT_SPEED),
        command_off=lambda: ptz_cam.pan_stop(),
    ).place(125, 150)

    up_left_btn = ntk.Button(
        window,
        text="↖",
        height=50,
        width=50,
        command=lambda: ptz_cam.pan_up_left(PAN_SPEED, TILT_SPEED),
        command_off=lambda: ptz_cam.pan_stop(),
    ).place(75, 50)
    up_right_btn = ntk.Button(
        window,
        text="↗",
        height=50,
        width=50,
        command=lambda: ptz_cam.pan_up_right(PAN_SPEED, TILT_SPEED),
        command_off=lambda: ptz_cam.pan_stop(),
    ).place(175, 50)

    down_left_btn = ntk.Button(
        window,
        text="↙",
        height=50,
        width=50,
        command=lambda: ptz_cam.pan_down_left(PAN_SPEED, TILT_SPEED),
        command_off=lambda: ptz_cam.pan_stop(),
    ).place(75, 150)
    down_right_btn = ntk.Button(
        window,
        text="↘",
        height=50,
        width=50,
        command=lambda: ptz_cam.pan_down_right(PAN_SPEED, TILT_SPEED),
        command_off=lambda: ptz_cam.pan_stop(),
    ).place(175, 150)

    zoom_in_btn = ntk.Button(
        window,
        text="+",
        height=50,
        width=50,
        command=lambda: ptz_cam.zoom("tele"),
        command_off=lambda: ptz_cam.zoom_stop(),
    ).place(25, 210)
    zoom_out_btn = ntk.Button(
        window,
        text="-",
        height=50,
        width=50,
        command=lambda: ptz_cam.zoom("wide"),
        command_off=lambda: ptz_cam.zoom_stop(),
    ).place(75, 210)
    zoom_lbl = ntk.Label(window, text="Zoom", height=15,width=50).place(50,260)

    focus_in_btn = ntk.Button(
        window,
        text="+",
        height=50,
        width=50,
        command=lambda: ptz_cam.focus("far"),
        command_off=lambda: ptz_cam.focus_stop(),
    ).place(175, 210)
    focus_out_btn = ntk.Button(
        window,
        text="-",
        height=50,
        width=50,
        command=lambda: ptz_cam.focus("near"),
        command_off=lambda: ptz_cam.focus_stop(),
    ).place(225, 210)
    focus_lbl = ntk.Label(window, text="Focus", height=15,width=50).place(200,260)

    names = [
        "Piano",
        "Stage Lyrics",
        "Speaker",
        "Announcements",
        "Stage no Lyrics",
        "Worship Leader",
        "Wide Shot Left",
        "Wide Shot Center",
        "Wide Shot Right",
    ]
    img = "Images/"
    # Preset buttons

    set_btn = ntk.Button(window, text="Set", mode="toggle", height=25, width=40).place(
        0, 275
    )

    def toggle_focus():
        if not af_btn.state:
            ptz_cam.focus_mode("manual")
        else:
            ptz_cam.focus_mode("auto")

    af_btn = ntk.Button(
        window,
        text="Autofocus",
        mode="toggle",
        height=25,
        width=75,
        command=toggle_focus,
    ).place(225, 275)
    if int(ptz_cam.inquire(ptz_cam.commands["inq"]["focus_mode"])[0]) == 2:
        ntk.standard_methods.toggle_object_toggle(af_btn)

    def set_recall(index):
        if set_btn.state:
            ptz_cam.preset_set(index)
        else:
            ptz_cam.preset_recall(index)

    for i in range(9):
        y = 250 + 50 * ((i + 3) // 3)
        x_offset = 2 if (i + 1) % 3 == 0 else (i + 1) % 3 - 1
        x = 100 * x_offset
        ntk.Button(
            window,
            text=f"{names[i]}",
            image=f"{img}{i+1}.jpg",
            text_color="white",
            font=("Arial", 9),
            height=50,
            width=100,
            command=lambda i=i: set_recall(i + 1),
        ).place(x, y)

    frame_container = ntk.Frame(window, width=300, height=150).place(0, 450)

    count = 0
    cap = vcapture(_active_rtsp_url)  # hd rtsp stream 1, sd 2
    cap.start()
    img = ntk.image_manager.Image(_object=frame_container, image=None)

    while cap.running:
        try:
            frame_time1 = time()
            frame = cap.current_frame
            frame_time2 = time()
            # sleep(1/30)
            sleep(1 / 30)
            if frame is not None:
                # cv2.imshow('frame',frame)
                im = Image.fromarray(frame, "RGB")
                # print(im.size)
                img = ntk.image_manager.Image(_object=frame_container, image=im)
                img.resize(width=300, height=150)
                new_frame_container = ntk.Frame(
                    window, width=300, height=150, image=img
                ).place(0, 450)
                frame_container.destroy()
                frame_container = new_frame_container

            frame_time3 = time()
        except KeyboardInterrupt:
            close()
