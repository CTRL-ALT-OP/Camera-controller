import nebulatk as ntk
from controller import Camera
from vcapture import vcapture
from time import sleep, time
from PIL import Image
import multiprocessing
import cv2
import json
import os
import re
import shutil
import contextlib
from camera_streams import stream_url_for_camera


def close():
    if _cap := globals().get("cap"):
        with contextlib.suppress(Exception):
            _cap.release()

    if _ptz_cam := globals().get("ptz_cam"):
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
    APP_DIR = os.path.dirname(os.path.abspath(__file__))
    IMAGES_DIR = os.path.join(APP_DIR, "Images")
    PRESETS_JSON_PATH = os.path.join(APP_DIR, "presets.json")
    DEFAULT_PRESET_NAMES = [
        "Band",
        "Speaker R",
        "Speaker",
        "Speaker L",
        "Stage no Lyrics",
        "Worship Leader",
        "Wide Shot Left",
        "Wide Shot Center",
        "Wide Shot Right",
    ]

    defaults_file = os.path.join(
        APP_DIR, "defaults_dark.py"
    )
    window = ntk.Window(
        width=300, height=600, closing_command=close, defaults_file=defaults_file
    ).place(y=30)

    PAN_SPEED = 7
    TILT_SPEED = 7

    def _cameras_json_path():
        return os.path.join(APP_DIR, "cameras.json")

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
            stream_url = cam.get("stream_url")
            if isinstance(ip, str) and ip.strip():
                normalized_cam = {"ip": ip.strip(), "type": str(cam_type)}
                if isinstance(stream_url, str) and stream_url.strip():
                    normalized_cam["stream_url"] = stream_url.strip()
                normalized.append(normalized_cam)
        return normalized

    def _camera_key(cam_cfg):
        ip = str(cam_cfg.get("ip", "")).strip()
        camera_type = str(cam_cfg.get("type", "ptzoptics")).strip()
        return f"{ip}|{camera_type}"

    def _camera_folder_name(camera_key):
        sanitized = re.sub(r"[^A-Za-z0-9._-]", "_", camera_key)
        return sanitized or "camera"

    def _build_default_slots():
        return {
            str(index + 1): {"name": DEFAULT_PRESET_NAMES[index], "image_path": ""}
            for index in range(9)
        }

    def _normalize_slots(raw_slots):
        normalized = _build_default_slots()
        if isinstance(raw_slots, dict):
            for index in range(1, 10):
                raw_slot = raw_slots.get(str(index), {})
                if not isinstance(raw_slot, dict):
                    continue
                raw_name = raw_slot.get("name")
                raw_image = raw_slot.get("image_path")
                if isinstance(raw_name, str) and raw_name.strip():
                    normalized[str(index)]["name"] = raw_name.strip()
                if isinstance(raw_image, str):
                    normalized[str(index)]["image_path"] = raw_image.strip()
        return normalized

    def _load_presets_store():
        default_store = {"version": 1, "cameras": {}}
        if not os.path.exists(PRESETS_JSON_PATH):
            return default_store
        try:
            with open(PRESETS_JSON_PATH, "r", encoding="utf-8") as f:
                data = json.load(f)
        except Exception:
            return default_store
        if not isinstance(data, dict):
            return default_store
        cameras_data = data.get("cameras")
        if not isinstance(cameras_data, dict):
            cameras_data = {}
        normalized_cameras = {}
        for key, payload in cameras_data.items():
            if not isinstance(key, str) or not key:
                continue
            slots = payload.get("presets") if isinstance(payload, dict) else {}
            normalized_cameras[key] = {"presets": _normalize_slots(slots)}
        return {"version": 1, "cameras": normalized_cameras}

    def _save_presets_store(store):
        with contextlib.suppress(Exception):
            with open(PRESETS_JSON_PATH, "w", encoding="utf-8") as f:
                json.dump(store, f, indent=2)

    def _ensure_camera_presets(store, camera_key):
        cameras_data = store.setdefault("cameras", {})
        camera_data = cameras_data.setdefault(camera_key, {})
        camera_data["presets"] = _normalize_slots(camera_data.get("presets", {}))
        return camera_data["presets"]

    def _camera_cfg_for_index(index):
        if isinstance(index, int) and 0 <= index < len(cameras):
            return cameras[index]
        return {"ip": "192.168.0.126", "type": "ptzoptics"}

    def _active_camera_cfg():
        return _camera_cfg_for_index(_active_index)

    def _stored_to_abs_path(stored_path):
        if not isinstance(stored_path, str) or not stored_path.strip():
            return ""
        value = stored_path.strip()
        if os.path.isabs(value):
            return value
        return os.path.join(APP_DIR, value)

    def _save_current_frame_for_preset(slot_index):
        frame = cap.current_frame
        if frame is None:
            return
        active_camera_key = _camera_key(_active_camera_cfg())
        folder = os.path.join(IMAGES_DIR, _camera_folder_name(active_camera_key))
        with contextlib.suppress(Exception):
            os.makedirs(folder, exist_ok=True)
        target_path = os.path.join(folder, f"{slot_index}.jpg")
        try:
            Image.fromarray(frame, "RGB").save(target_path, format="JPEG")
        except Exception:
            return
        presets = _ensure_camera_presets(preset_store, active_camera_key)
        presets[str(slot_index)]["image_path"] = os.path.relpath(target_path, APP_DIR)
        _save_presets_store(preset_store)

    def _migrate_legacy_images(store):
        if not cameras:
            return
        first_camera_key = _camera_key(cameras[0])
        first_presets = _ensure_camera_presets(store, first_camera_key)
        target_folder = os.path.join(IMAGES_DIR, _camera_folder_name(first_camera_key))
        with contextlib.suppress(Exception):
            os.makedirs(target_folder, exist_ok=True)
        migrated = False
        for slot_index in range(1, 10):
            legacy_path = os.path.join(IMAGES_DIR, f"{slot_index}.jpg")
            if not os.path.exists(legacy_path):
                continue
            target_path = os.path.join(target_folder, f"{slot_index}.jpg")
            try:
                shutil.copy2(legacy_path, target_path)
                first_presets[str(slot_index)]["image_path"] = os.path.relpath(
                    target_path, APP_DIR
                )
                migrated = True
            except Exception:
                continue
        if migrated:
            _save_presets_store(store)

    cameras = _load_cameras()

    # Initialize default camera (first from cameras.json if available, otherwise keep legacy default)
    if cameras:
        _active_index = 0
        ptz_cam = Camera(ip=cameras[0]["ip"], camera_type=cameras[0]["type"])
        _active_rtsp_url = stream_url_for_camera(cameras[0])
    else:
        _active_index = None
        ptz_cam = Camera(ip="192.168.0.126")
        _active_rtsp_url = stream_url_for_camera(
            {"ip": "192.168.0.126", "type": "ptzoptics"}
        )

    presets_file_exists = os.path.exists(PRESETS_JSON_PATH)
    preset_store = _load_presets_store()
    if not presets_file_exists:
        _migrate_legacy_images(preset_store)
    _ensure_camera_presets(preset_store, _camera_key(_active_camera_cfg()))
    _save_presets_store(preset_store)
    preset_buttons = [None] * 9
    rename_prompt_widgets = {}

    def _refresh_preset_button(slot_index):
        if not 1 <= slot_index <= 9:
            return
        button = preset_buttons[slot_index - 1]
        if button is None:
            return
        camera_key = _camera_key(_active_camera_cfg())
        presets = _ensure_camera_presets(preset_store, camera_key)
        slot = presets[str(slot_index)]
        button.text = slot["name"]
        image_path = _stored_to_abs_path(slot.get("image_path", ""))
        if image_path and os.path.exists(image_path):
            try:
                base_image = ntk.image_manager.Image(image_path, _object=button)
                button.image = base_image
                button.hover_image = ntk.image_manager.Image(base_image).darken(18)
                button.active_image = ntk.image_manager.Image(base_image).darken(36)
                button.active_hover_image = ntk.image_manager.Image(base_image).darken(48)
            except Exception:
                button.image = image_path
                button.hover_image = None
                button.active_image = None
                button.active_hover_image = None
        else:
            button.image = None
            button.hover_image = None
            button.active_image = None
            button.active_hover_image = None
        button.update()

    def _refresh_preset_buttons():
        camera_key = _camera_key(_active_camera_cfg())
        _ensure_camera_presets(preset_store, camera_key)
        _save_presets_store(preset_store)
        for slot_index in range(1, 10):
            _refresh_preset_button(slot_index)

    def _close_rename_prompt():
        for key in ("frame", "title", "entry", "save_btn", "cancel_btn"):
            widget = rename_prompt_widgets.pop(key, None)
            if widget is not None:
                with contextlib.suppress(Exception):
                    widget.destroy()

    def _show_rename_prompt(slot_index):
        _close_rename_prompt()
        camera_key = _camera_key(_active_camera_cfg())
        presets = _ensure_camera_presets(preset_store, camera_key)
        current_name = presets[str(slot_index)]["name"]

        panel = ntk.Frame(window, width=280, height=100, style="settings_panel").place(10, 345)
        title = ntk.Label(
            window,
            text=f"Rename Preset {slot_index}",
            width=260,
            height=20,
            style="label_transparent",
        ).place(20, 350)
        entry = ntk.Entry(
            window,
            width=260,
            height=30,
            text=current_name,
            justify="left",
            style="settings_entry",
        ).place(20, 372)

        def save_name():
            new_name = entry.get().strip()
            if new_name:
                presets[str(slot_index)]["name"] = new_name
                _save_presets_store(preset_store)
                _refresh_preset_button(slot_index)
            _close_rename_prompt()

        save_btn = ntk.Button(
            window,
            text="Save",
            width=120,
            height=25,
            style="button_accent",
            command=save_name,
        ).place(20, 410)
        cancel_btn = ntk.Button(
            window,
            text="Cancel",
            width=120,
            height=25,
            style="button_neutral",
            command=_close_rename_prompt,
        ).place(160, 410)

        rename_prompt_widgets.update(
            {
                "frame": panel,
                "title": title,
                "entry": entry,
                "save_btn": save_btn,
                "cancel_btn": cancel_btn,
            }
        )

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

        # Start new feed URL (RTSP by default, synthetic stream for testcamera)
        _active_rtsp_url = stream_url_for_camera(cam_cfg)
        cap = vcapture(_active_rtsp_url)
        cap.start()

        _active_index = index
        _close_rename_prompt()
        _refresh_preset_buttons()

    # Camera selector buttons at top of window
    for i in range(4):
        ntk.Button(
            window,
            text=f"Camera {i+1}",
            height=25,
            width=75,
            style="button_neutral",
            command=lambda i=i: switch_camera(i),
        ).place(75 * i, 0)

    left_btn = ntk.Button(
        window,
        text="←",
        height=50,
        width=50,
        style="button_neutral",
        command=lambda: ptz_cam.pan_left(PAN_SPEED, TILT_SPEED),
        command_off=lambda: ptz_cam.pan_stop(),
    ).place(75, 100)
    right_btn = ntk.Button(
        window,
        text="→",
        height=50,
        width=50,
        style="button_neutral",
        command=lambda: ptz_cam.pan_right(PAN_SPEED, TILT_SPEED),
        command_off=lambda: ptz_cam.pan_stop(),
    ).place(175, 100)

    left_btn = ntk.Button(
        window,
        text="←",
        height=50,
        width=50,
        style="button_neutral",
        command=lambda: ptz_cam.pan_left(PAN_SPEED * 2, TILT_SPEED * 2),
        command_off=lambda: ptz_cam.pan_stop(),
    ).place(25, 100)
    right_btn = ntk.Button(
        window,
        text="→",
        height=50,
        width=50,
        style="button_neutral",
        command=lambda: ptz_cam.pan_right(PAN_SPEED * 2, TILT_SPEED * 2),
        command_off=lambda: ptz_cam.pan_stop(),
    ).place(225, 100)

    up_btn = ntk.Button(
        window,
        text="↑",
        height=50,
        width=50,
        style="button_neutral",
        command=lambda: ptz_cam.pan_up(PAN_SPEED, TILT_SPEED),
        command_off=lambda: ptz_cam.pan_stop(),
    ).place(125, 50)
    down_btn = ntk.Button(
        window,
        text="↓",
        height=50,
        width=50,
        style="button_neutral",
        command=lambda: ptz_cam.pan_down(PAN_SPEED, TILT_SPEED),
        command_off=lambda: ptz_cam.pan_stop(),
    ).place(125, 150)

    up_left_btn = ntk.Button(
        window,
        text="↖",
        height=50,
        width=50,
        style="button_neutral",
        command=lambda: ptz_cam.pan_up_left(PAN_SPEED, TILT_SPEED),
        command_off=lambda: ptz_cam.pan_stop(),
    ).place(75, 50)
    up_right_btn = ntk.Button(
        window,
        text="↗",
        height=50,
        width=50,
        style="button_neutral",
        command=lambda: ptz_cam.pan_up_right(PAN_SPEED, TILT_SPEED),
        command_off=lambda: ptz_cam.pan_stop(),
    ).place(175, 50)

    down_left_btn = ntk.Button(
        window,
        text="↙",
        height=50,
        width=50,
        style="button_neutral",
        command=lambda: ptz_cam.pan_down_left(PAN_SPEED, TILT_SPEED),
        command_off=lambda: ptz_cam.pan_stop(),
    ).place(75, 150)
    down_right_btn = ntk.Button(
        window,
        text="↘",
        height=50,
        width=50,
        style="button_neutral",
        command=lambda: ptz_cam.pan_down_right(PAN_SPEED, TILT_SPEED),
        command_off=lambda: ptz_cam.pan_stop(),
    ).place(175, 150)

    zoom_in_btn = ntk.Button(
        window,
        text="+",
        height=50,
        width=50,
        style="button_neutral",
        command=lambda: ptz_cam.zoom("tele"),
        command_off=lambda: ptz_cam.zoom_stop(),
    ).place(25, 210)
    zoom_out_btn = ntk.Button(
        window,
        text="-",
        height=50,
        width=50,
        style="button_neutral",
        command=lambda: ptz_cam.zoom("wide"),
        command_off=lambda: ptz_cam.zoom_stop(),
    ).place(75, 210)
    zoom_lbl = ntk.Label(
        window, text="Zoom", height=15, width=50, style="label_transparent"
    ).place(50, 260)

    focus_in_btn = ntk.Button(
        window,
        text="+",
        height=50,
        width=50,
        style="button_neutral",
        command=lambda: ptz_cam.focus("far"),
        command_off=lambda: ptz_cam.focus_stop(),
    ).place(175, 210)
    focus_out_btn = ntk.Button(
        window,
        text="-",
        height=50,
        width=50,
        style="button_neutral",
        command=lambda: ptz_cam.focus("near"),
        command_off=lambda: ptz_cam.focus_stop(),
    ).place(225, 210)
    focus_lbl = ntk.Label(
        window, text="Focus", height=15, width=50, style="label_transparent"
    ).place(200, 260)

    # Preset buttons

    set_btn = ntk.Button(
        window, text="Set", mode="toggle", height=25, width=40, style="button_accent"
    ).place(0, 275)

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
        style="button_accent",
        command=toggle_focus,
    ).place(225, 275)
    if int(ptz_cam.inquire(ptz_cam.commands["inq"]["focus_mode"])[0]) == 2:
        ntk.standard_methods.toggle_object_toggle(af_btn)

    def set_recall(index):
        if set_btn.state:
            ptz_cam.preset_set(index)
            _save_current_frame_for_preset(index)
            _refresh_preset_button(index)
            ntk.standard_methods.toggle_object_toggle(set_btn)
            _show_rename_prompt(index)
        else:
            ptz_cam.preset_recall(index)

    preset_base_fill = "#6e6e6e"
    preset_hover_fill = ntk.colors_manager.Color(preset_base_fill).darken(18).color
    preset_active_fill = ntk.colors_manager.Color(preset_base_fill).darken(36).color
    preset_active_hover_fill = ntk.colors_manager.Color(preset_base_fill).darken(48).color

    for i in range(9):
        y = 250 + 50 * ((i + 3) // 3)
        x_offset = 2 if (i + 1) % 3 == 0 else (i + 1) % 3 - 1
        x = 100 * x_offset
        button_kwargs = {
            "text_color": "default",
            "font": "default",
            "height": 50,
            "width": 100,
            "fill": preset_base_fill,
            "hover_fill": preset_hover_fill,
            "active_fill": preset_active_fill,
            "active_hover_fill": preset_active_hover_fill,
            "command": lambda i=i: set_recall(i + 1),
        }
        preset_button = ntk.Button(
            window,
            text=DEFAULT_PRESET_NAMES[i],
            **button_kwargs,
        ).place(x, y)
        preset_buttons[i] = preset_button

    _refresh_preset_buttons()

    frame_container = ntk.Frame(window, width=300, height=150, style="surface").place(
        0, 450
    )

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
                img = ntk.image_manager.Image(image=im)
                img.resize(width=300, height=150)
                frame_container.image = img
                frame_container.update()

            frame_time3 = time()
        except KeyboardInterrupt:
            close()
