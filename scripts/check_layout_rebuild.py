import argparse
import base64
import json
import socket
import subprocess
import tempfile
import time
from pathlib import Path

import requests
from websocket import create_connection

ROOT = Path(__file__).resolve().parents[1]
BASE = "http://localhost:8000/simulation.html"
CHROME = r"C:\Program Files\Google\Chrome\Application\chrome.exe"
VIEW_NAMES = ["3d", "top", "front", "side", "section"]
SIBLING_GROUPS = {
    "main_row": ["scene_container", "workflow_panel"],
    "graphs_row": ["graph_1", "graph_2", "graph_3"],
    "controls_groups": ["control_1", "control_2", "control_3"],
}

parser = argparse.ArgumentParser()
parser.add_argument("--label", default="rebuild")
args = parser.parse_args()

all_console_errors = []

sock = socket.socket()
sock.bind(("127.0.0.1", 0))
PORT = sock.getsockname()[1]
sock.close()

profile = tempfile.mkdtemp(prefix="nacelle-rebuild-check-")
chrome = subprocess.Popen(
    [
        CHROME,
        "--headless=new",
        "--remote-debugging-port=" + str(PORT),
        "--user-data-dir=" + profile,
        "--no-first-run",
        "--no-default-browser-check",
        "--disable-background-networking",
        "--disable-extensions",
        "--enable-webgl",
        "--enable-unsafe-swiftshader",
        "--window-size=1440,900",
        "about:blank",
    ],
    stdout=subprocess.DEVNULL,
    stderr=subprocess.DEVNULL,
)

for _ in range(100):
    try:
        requests.get("http://127.0.0.1:" + str(PORT) + "/json/version", timeout=0.2)
        break
    except Exception:
        time.sleep(0.1)
else:
    chrome.terminate()
    raise RuntimeError("Chrome remote debugging did not start")

targets = requests.get("http://127.0.0.1:" + str(PORT) + "/json/list").json()
target = next((item for item in targets if item.get("type") == "page"), None)
if target is None:
    chrome.terminate()
    raise RuntimeError("No page target available")

ws = create_connection(target["webSocketDebuggerUrl"], timeout=60)
sequence = 0
events = []


def send(method, params=None):
    global sequence
    sequence += 1
    current = sequence
    message = {"id": current, "method": method}
    if params is not None:
        message["params"] = params
    ws.send(json.dumps(message))
    while True:
        data = json.loads(ws.recv())
        if data.get("id") == current:
            if "error" in data:
                raise RuntimeError(method + ": " + json.dumps(data["error"]))
            return data.get("result", {})
        events.append(data)


def evaluate(expression):
    result = send(
        "Runtime.evaluate",
        {"expression": expression, "returnByValue": True, "awaitPromise": True},
    )
    if "exceptionDetails" in result:
        raise RuntimeError(json.dumps(result["exceptionDetails"]))
    return result.get("result", {}).get("value")


def drain_errors():
    found = []
    for event in events:
        method = event.get("method")
        params = event.get("params", {})
        if method == "Runtime.exceptionThrown":
            found.append(params.get("exceptionDetails", {}).get("text", "exception"))
        elif method == "Runtime.consoleAPICalled" and params.get("type") == "error":
            found.append(" ".join(str(arg.get("value", arg.get("description", ""))) for arg in params.get("args", [])))
        elif method == "Log.entryAdded" and params.get("entry", {}).get("level") == "error":
            found.append(params["entry"].get("text", "log error"))
    all_console_errors.extend(found)
    events.clear()
    return found


def navigate(width, height):
    send("Page.enable")
    send("Runtime.enable")
    send("Log.enable")
    send(
        "Emulation.setDeviceMetricsOverride",
        {
            "width": width,
            "height": height,
            "deviceScaleFactor": 1,
            "mobile": width < 768,
            "screenWidth": width,
            "screenHeight": height,
        },
    )
    send("Page.navigate", {"url": BASE})
    for _ in range(100):
        if evaluate("document.readyState") == "complete":
            break
        time.sleep(0.1)
    time.sleep(2.5)
    return drain_errors()


LAYOUT_AUDIT = r"""
(function () {
  function box(element) {
    if (!element) return null;
    const rect = element.getBoundingClientRect();
    return {left: rect.left, top: rect.top, right: rect.right, bottom: rect.bottom, width: rect.width, height: rect.height};
  }
  function add(target, key, name, parent, parentKey, parentName) {
    target.push({key: key, name: name, bbox: box(elementOf(key)), parentKey: parentKey, parentName: parentName, parentBbox: box(parent)});
  }
  function elementOf(key) {
    const map = {
      scene_container: document.querySelector("#simulation-scene"),
      workflow_panel: document.querySelector("#workflow-panel"),
      readouts_strip: document.querySelector("#readouts-strip"),
      graphs_row: document.querySelector("#graphs-row"),
      controls_groups: document.querySelector("#controls-groups"),
      footer: document.querySelector("#site-footer")
    };
    return map[key] || null;
  }
  const containers = [];
  const mainRow = document.querySelector("#main-row");
  const mainContent = document.querySelector("#main-content");
  const graphsRow = document.querySelector("#graphs-row");
  const controlsGroups = document.querySelector("#controls-groups");
  const body = document.body;
  add(containers, "scene_container", "Scene container", mainRow, "main_row", "Main row");
  add(containers, "workflow_panel", "Workflow panel", mainRow, "main_row", "Main row");
  add(containers, "readouts_strip", "Readouts strip", mainContent, "main_content", "Main content");
  const graphCards = Array.from(document.querySelectorAll("#graphs-row > .graph-card"));
  graphCards.forEach(function (card, index) {
    const title = card.querySelector("h3") ? card.querySelector("h3").textContent : "Graph " + (index + 1);
    containers.push({key: "graph_" + (index + 1), name: "Graph: " + title, bbox: box(card), parentKey: "graphs_row", parentName: "Graphs row", parentBbox: box(graphsRow)});
  });
  const controlGroups = Array.from(document.querySelectorAll("#controls-groups > .control-group"));
  controlGroups.forEach(function (group, index) {
    const title = group.querySelector("h3") ? group.querySelector("h3").textContent : "Control group " + (index + 1);
    containers.push({key: "control_" + (index + 1), name: "Control group: " + title, bbox: box(group), parentKey: "controls_groups", parentName: "Controls groups", parentBbox: box(controlsGroups)});
  });
  containers.push({key: "footer", name: "Footer", bbox: box(document.querySelector("#site-footer")), parentKey: "body", parentName: "Body", parentBbox: box(body)});
  const scene = document.querySelector("#simulation-scene");
  const svg = document.querySelector("#section-svg");
  const canvas = document.querySelector("#scene-container canvas");
  const visibleLabels = Array.from(document.querySelectorAll(".section-label")).filter(function (label) {
    return getComputedStyle(label).display !== "none";
  });
  const sliders = Array.from(document.querySelectorAll(".slider-control")).map(function (slider, index) {
    const label = slider.querySelector(".slider-label");
    const value = slider.querySelector(".slider-value");
    const input = slider.querySelector("input[type=range]");
    const ticks = slider.querySelector(".slider-ticks");
    return {
      index: index,
      labelText: label ? label.textContent.trim() : null,
      labelDisplay: label ? getComputedStyle(label.parentElement).display : null,
      labelBox: box(label),
      valueBox: box(value),
      inputBox: box(input),
      ticksBox: box(ticks),
      minText: ticks && ticks.firstElementChild ? ticks.firstElementChild.textContent.trim() : null,
      maxText: ticks && ticks.lastElementChild ? ticks.lastElementChild.textContent.trim() : null
    };
  });
  return {
    containers: containers,
    readoutsBbox: box(document.querySelector("#readouts-strip")),
    graphsBbox: box(document.querySelector("#graphs-row")),
    controlsBbox: box(document.querySelector("#controls-section")),
    sceneBbox: box(scene),
    svgBbox: box(svg),
    canvasBbox: box(canvas),
    scenePosition: scene ? getComputedStyle(scene).position : null,
    svgPosition: svg ? getComputedStyle(svg).position : null,
    canvasPosition: canvas ? getComputedStyle(canvas).position : null,
    visibleSectionLabels: visibleLabels.length,
    labelBoxes: visibleLabels.map(function (label) { return {name: label.getAttribute("data-label"), bbox: box(label)}; }),
    sliders: sliders
  };
})()
"""

VIEW_AUDIT = r"""
(function () {
  function box(element) {
    if (!element) return null;
    const rect = element.getBoundingClientRect();
    return {left: rect.left, top: rect.top, right: rect.right, bottom: rect.bottom, width: rect.width, height: rect.height};
  }
  const scene = document.querySelector("#simulation-scene");
  const svg = document.querySelector("#section-svg");
  const canvas = document.querySelector("#scene-container canvas");
  return {
    view: scene ? scene.getAttribute("data-view") : null,
    sceneBbox: box(scene),
    svgBbox: box(svg),
    canvasBbox: box(canvas),
    svgVisibility: svg ? getComputedStyle(svg).visibility : null,
    canvasVisibility: canvas ? getComputedStyle(canvas.parentElement).visibility : null
  };
})()
"""


def inside(inner, outer):
    if not inner or not outer:
        return False
    return (
        inner["left"] >= outer["left"] - 1
        and inner["top"] >= outer["top"] - 1
        and inner["right"] <= outer["right"] + 1
        and inner["bottom"] <= outer["bottom"] + 1
    )


def intersects(first, second):
    return min(first["right"], second["right"]) - max(first["left"], second["left"]) > 1 and min(first["bottom"], second["bottom"]) - max(first["top"], second["top"]) > 1


def audit(width, height):
    page_errors = navigate(width, height)
    data = evaluate(LAYOUT_AUDIT)

    container_results = []
    for item in data["containers"]:
        result = dict(item)
        result["insideParent"] = inside(item["bbox"], item["parentBbox"])
        container_results.append(result)

    sibling_results = []
    for group_name, keys in SIBLING_GROUPS.items():
        members = [item for item in container_results if item["key"] in keys]
        for i in range(len(members)):
            for j in range(i + 1, len(members)):
                sibling_results.append(
                    {
                        "group": group_name,
                        "first": members[i]["name"],
                        "second": members[j]["name"],
                        "intersects": intersects(members[i]["bbox"], members[j]["bbox"]),
                    }
                )

    view_results = []
    for view in VIEW_NAMES:
        evaluate('document.querySelector(\'.view-button[data-view="' + view + '"]\').click()')
        time.sleep(0.3)
        view_data = evaluate(VIEW_AUDIT)
        view_data["svgInsideScene"] = inside(view_data["svgBbox"], view_data["sceneBbox"])
        view_data["canvasInsideScene"] = inside(view_data["canvasBbox"], view_data["sceneBbox"])
        view_results.append(view_data)

    expected_aspect = 16 / 9 if width == 1440 else 4 / 3
    scene = data["sceneBbox"]
    scene_aspect = round(scene["width"] / scene["height"], 4) if scene and scene["height"] else None

    slider_issues = []
    for slider in data["sliders"]:
        label = slider["labelBox"]
        value = slider["valueBox"]
        input_box = slider["inputBox"]
        ticks = slider["ticksBox"]
        if not label or not value or value["left"] - label["right"] < 7.5:
            slider_issues.append({"slider": slider["index"], "issue": "label-value-gap"})
        if slider["labelText"] and not slider["labelText"].endswith(":"):
            slider_issues.append({"slider": slider["index"], "issue": "label-format"})
        if slider["labelDisplay"] != "flex":
            slider_issues.append({"slider": slider["index"], "issue": "label-display"})
        if not slider["minText"] or not slider["maxText"]:
            slider_issues.append({"slider": slider["index"], "issue": "min-max"})
        if not input_box or not ticks or input_box["width"] < scene["width"] * 0.05:
            slider_issues.append({"slider": slider["index"], "issue": "slider-size"})

    label_issues = []
    for label in data["labelBoxes"]:
        if not inside(label["bbox"], data["sceneBbox"]):
            label_issues.append(label["name"])

    positions = {
        "scene": data["scenePosition"],
        "svg": data["svgPosition"],
        "canvas": data["canvasPosition"],
    }
    report = {
        "viewport": {"width": width, "height": height},
        "containers": container_results,
        "containersAllInsideParent": all(item["insideParent"] for item in container_results),
        "siblingPairs": sibling_results,
        "siblingIntersections": [item for item in sibling_results if item["intersects"]],
        "views": view_results,
        "svgInsideSceneAllViews": all(item["svgInsideScene"] for item in view_results),
        "canvasInsideSceneAllViews": all(item["canvasInsideScene"] for item in view_results),
        "sceneAspectRatio": scene_aspect,
        "expectedAspectRatio": round(expected_aspect, 4),
        "aspectRatioCorrect": scene_aspect is not None and abs(scene_aspect - expected_aspect) < 0.02,
        "positions": positions,
        "positionsRelative": all(value == "relative" for value in positions.values()),
        "readoutsAboveGraphs": bool(data["readoutsBbox"]["bottom"] <= data["graphsBbox"]["top"] + 1),
        "controlsBelowGraphs": bool(data["controlsBbox"]["top"] >= data["graphsBbox"]["bottom"] - 1),
        "visibleSectionLabels": data["visibleSectionLabels"],
        "labelsInsideScene": not label_issues,
        "labelIssues": label_issues,
        "sliderIssues": slider_issues,
        "consoleErrors": drain_errors() + page_errors,
    }
    report["pass"] = (
        report["containersAllInsideParent"]
        and not report["siblingIntersections"]
        and report["svgInsideSceneAllViews"]
        and report["canvasInsideSceneAllViews"]
        and report["aspectRatioCorrect"]
        and report["positionsRelative"]
        and report["readoutsAboveGraphs"]
        and report["controlsBelowGraphs"]
        and report["visibleSectionLabels"] <= 4
        and report["labelsInsideScene"]
        and not report["sliderIssues"]
        and not report["consoleErrors"]
    )
    return report


def capture(width, height, path):
    navigate(width, height)
    evaluate('document.querySelector(\'.view-button[data-view="3d"]\').click()')
    evaluate("window.scrollTo(0, 0)")
    time.sleep(0.4)
    png = send("Page.captureScreenshot", {"format": "png", "captureBeyondViewport": True})["data"]
    output = Path(path)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_bytes(base64.b64decode(png))
    return str(output)


def stable_run():
    navigate(1440, 900)
    evaluate(
        r"""
        (function () {
          document.getElementById("reset-button").click();
          document.querySelector('.preset-button[data-preset="stable"]').click();
          document.getElementById("start-button").click();
          return true;
        })()
        """
    )
    samples = []
    started = time.time()
    while time.time() - started < 80:
        sample = evaluate(
            r"""
            (function () {
              const state = window.simulationState;
              const error = ((state.trueWindDirection - state.heading + 540) % 360) - 180;
              return {t: state.time, e: Math.abs(error), p: state.power, status: state.status};
            })()
            """
        )
        if sample and sample.get("t") is not None:
            samples.append(sample)
            if sample["t"] >= 60:
                break
        time.sleep(0.25)

    settling = None
    for index, sample in enumerate(samples):
        if sample["t"] < 1:
            continue
        target = sample["t"] + 10.0
        end_index = next((j for j in range(index, len(samples)) if samples[j]["t"] >= target), None)
        if end_index is None:
            break
        if all(item["e"] < 5 for item in samples[index:end_index + 1]):
            settling = sample["t"]
            break

    after = [item for item in samples if settling is not None and item["t"] >= settling]
    baseline = json.loads((ROOT / "assets" / "data" / "results.json").read_text())
    median_settle = baseline["metrics"]["settling_time_s"]["value"]
    previous_final_error = 2.73
    current_settle = round(settling, 2) if settling is not None else None
    current_final_error = round(samples[-1]["e"], 2) if samples else None
    return {
        "samples": len(samples),
        "simulatedSeconds": round(samples[-1]["t"], 2) if samples else None,
        "settlingTimeS": current_settle,
        "meanAbsErrorDeg": round(sum(item["e"] for item in after) / len(after), 2) if after else None,
        "steadyPowerPct": round(sum(item["p"] for item in after) / len(after), 2) if after else None,
        "finalErrorDeg": current_final_error,
        "finalStatus": samples[-1]["status"] if samples else None,
        "comparison": {
            "resultsJsonMedianSettleS": median_settle,
            "previousRunFinalErrorDeg": previous_final_error,
            "settleDeltaS": round(current_settle - median_settle, 2) if current_settle is not None else None,
            "finalErrorDeltaDeg": round(current_final_error - previous_final_error, 2) if current_final_error is not None else None,
            "withinNormalVariation": (
                current_settle is not None
                and current_final_error is not None
                and abs(current_settle - median_settle) <= 10
                and abs(current_final_error - previous_final_error) <= 3
            ),
        },
        "consoleErrors": drain_errors(),
    }


try:
    if not requests.get(BASE, timeout=2).ok:
        raise RuntimeError("Local server is not serving " + BASE)
    report = {"label": args.label, "widths": {}}
    for width, height in [(1440, 900), (375, 812)]:
        report["widths"][str(width)] = audit(width, height)
        report["widths"][str(width)]["screenshot"] = capture(
            width,
            height,
            "screenshots/rebuild-1440.png" if width == 1440 else "screenshots/rebuild-375.png",
        )

    report["stableRun"] = stable_run()
    report["consoleErrors"] = sorted(set(all_console_errors))
    report["pass"] = (
        all(item["pass"] for item in report["widths"].values())
        and report["stableRun"]["comparison"]["withinNormalVariation"]
        and not report["consoleErrors"]
    )
    print(json.dumps(report, indent=2))
    raise SystemExit(0 if report["pass"] else 1)
finally:
    try:
        ws.close()
    except Exception:
        pass
    chrome.terminate()
