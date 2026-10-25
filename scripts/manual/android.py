"""ADB driver using visible text and accessibility bounds, on IPA_Manual only."""

import json
import re
import subprocess
import time
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / ".context/manual/screenshots"
PACKAGE = "ar.com.ingenieriaalimentacion.tst"


def adb(*args, binary=False):
    result = subprocess.run(
        ["adb", "-s", "emulator-5554", *args],
        check=True,
        capture_output=True,
        timeout=30,
    )
    return result.stdout if binary else result.stdout.decode().strip()


def assert_device():
    if "IPA_Manual" not in adb("emu", "avd", "name"):
        raise RuntimeError("The capture driver only operates the IPA_Manual AVD")


def start():
    assert_device()
    adb("shell", "am", "force-stop", PACKAGE)
    adb(
        "shell",
        "am",
        "start",
        "-n",
        f"{PACKAGE}/ar.com.ingenieriaalimentacion.MainActivity",
    )
    time.sleep(1)


def offline(value):
    assert_device()
    adb(
        "shell",
        "cmd",
        "connectivity",
        "airplane-mode",
        "enable" if value else "disable",
    )
    adb("shell", "svc", "wifi", "disable" if value else "enable")
    adb("shell", "svc", "data", "disable" if value else "enable")
    time.sleep(2)


def tree():
    adb("shell", "uiautomator", "dump", "/sdcard/manual-window.xml")
    xml = adb("shell", "cat", "/sdcard/manual-window.xml")
    return ET.fromstring(xml)


def text_tree():
    return [
        (
            n.get("text") or n.get("content-desc") or n.get("hint"),
            n.get("class"),
            n.get("bounds"),
        )
        for n in tree().iter("node")
        if n.get("text")
        or n.get("content-desc")
        or n.get("class") == "android.widget.EditText"
    ]


def find(label, contains=False, first=False):
    nodes = list(tree().iter("node"))
    for node in nodes if first else reversed(nodes):
        values = [
            node.get("text", ""),
            node.get("content-desc", ""),
            node.get("hint", ""),
        ]
        if any(label in v if contains else label == v for v in values):
            return node
    raise RuntimeError(f"Visible element not found: {label!r}")


def tap(label, contains=False, first=False):
    node = find(label, contains, first)
    x1, y1, x2, y2 = map(int, re.findall(r"\d+", node.get("bounds")))
    adb("shell", "input", "tap", str((x1 + x2) // 2), str((y1 + y2) // 2))


def wait_for(label, timeout=45):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            return find(label, contains=True)
        except RuntimeError:
            time.sleep(0.3)
    raise RuntimeError(f"Timed out waiting for visible element: {label!r}")


def fill(index, value):
    nodes = [
        n for n in tree().iter("node") if n.get("class") == "android.widget.EditText"
    ]
    node = nodes[index]
    x1, y1, x2, y2 = map(int, re.findall(r"\d+", node.get("bounds")))
    adb("shell", "input", "tap", str((x1 + x2) // 2), str((y1 + y2) // 2))
    adb("shell", "input", "keyevent", "KEYCODE_MOVE_END")
    for _ in node.get("text", ""):
        adb("shell", "input", "keyevent", "KEYCODE_DEL")
    adb("shell", "input", "text", value.replace(" ", "%s"))


def back():
    adb("shell", "input", "keyevent", "4")


def swipe(up=True):
    adb(
        "shell",
        "input",
        "swipe",
        "640",
        "2200" if up else "650",
        "640",
        "650" if up else "2200",
        "350",
    )


def scroll_to(label, attempts=12):
    for _ in range(attempts):
        try:
            return find(label, contains=True)
        except RuntimeError:
            swipe()
    raise RuntimeError(f"Element not found while scrolling: {label}")


def shot(identifier, expected):
    assert_device()
    find(expected, contains=True)
    OUT.mkdir(parents=True, exist_ok=True)
    # Hide IME before calling this function; a screenshot must represent the page.
    (OUT / f"{identifier}.png").write_bytes(
        adb("exec-out", "screencap", "-p", binary=True)
    )
    values = text_tree()
    (OUT / f"{identifier}.txt").write_text("\n".join(str(x) for x in values))
    manifest = OUT / "android-captures.json"
    entries = json.loads(manifest.read_text()) if manifest.exists() else []
    entries = [e for e in entries if e["id"] != identifier]
    entries.append(
        {
            "id": identifier,
            "surface": "android",
            "file": f"{identifier}.png",
            "expected": expected,
            "capturedAt": datetime.now(timezone.utc).isoformat(),
        }
    )
    manifest.write_text(json.dumps(entries, indent=2, ensure_ascii=False))
    print(identifier)


if __name__ == "__main__":
    assert_device()
    print(json.dumps(text_tree(), ensure_ascii=False, indent=2))
