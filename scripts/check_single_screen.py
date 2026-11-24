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

parser = argparse.ArgumentParser()
parser.add_argument("--label", default="single-screen")
args = parser.parse_args()

all_console_errors = []

sock = socket.socket()
sock.bind(("127.0.0.1", 0))
PORT = sock.getsockname()[1]
sock.close()

profile = tempfile.mkdtemp(prefix="nacelle-single-screen-")
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
            details = params.get("exceptionDetails", {})
            description = details.get("exception", {}).get("description") or details.get("text", "exception")
            found.append(description)
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
            "mobile": False,
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


def box(element):
    return element


LAYOUT_AUDIT = r"""
(function () {
  function box(element) {
    if (!element) return null;
    const rect = element.getBoundingClientRect();
    return {left: rect.left, top: rect.top, right: rect.right, bottom: rect.bottom, width: rect.width, height: rect.height};
  }
  function metrics(element) {
    if (!element) return null;
    return {scrollHeight: element.scrollHeight, clientHeight: element.clientHeight, overflowY: getComputedStyle(element).overflowY};
  }
  function visible(element) {
    if (!element) return false;
    const style = getComputedStyle(element);
    return style.display !== "none" && style.visibility !== "hidden" && element.getClientRects().length > 0;
  }
  const panelSelectors = {
    top_bar: ".sim-topbar",
    left_panel: "#turbine-panel",
    alignment_panel: "#alignment-panel",
    controls_panel: "#controls-section"
  };
  const panels = Object.keys(panelSelectors).map(function (key) {
    const element = document.querySelector(panelSelectors[key]);
    return {key: key, bbox: box(element), metrics: metrics(element), visible: visible(element)};
  });
  const controlsBody = document.getElementById("controls-body");
  const smallText = [];
  const walker = document.createTreeWalker(document.body, NodeFilter.SHOW_TEXT, null);
  while (walker.nextNode()) {
    const node = walker.currentNode;
    if (!node.nodeValue || node.nodeValue.trim().length === 0) continue;
    const element = node.parentElement;
    if (!element || ["SCRIPT", "STYLE", "TITLE"].indexOf(element.tagName) !== -1) continue;
    if (!visible(element)) continue;
    const size = parseFloat(getComputedStyle(element).fontSize);
    if (!Number.isFinite(size) || size < 14) {
      smallText.push({text: node.nodeValue.trim().slice(0, 60), size: size, tag: element.tagName, className: element.className});
    }
  }
  const sliders = Array.from(document.querySelectorAll(".slider-control")).map(function (slider, index) {
    const label = slider.querySelector(".slider-label");
    const value = slider.querySelector(".slider-value");
    const output = value ? value.querySelector("output") : null;
    const unit = value ? value.querySelector(".slider-unit") : null;
    const input = slider.querySelector("input[type=range]");
    const ticks = slider.querySelector(".slider-ticks");
    return {
      index: index,
      labelText: label ? label.textContent.trim() : null,
      valueText: value ? value.textContent.trim() : null,
      unitText: unit ? unit.textContent.trim() : null,
      outputText: output ? output.textContent.trim() : null,
      separateElements: Boolean(label && value && output && unit && input && ticks && label !== value && output !== unit),
      hasMinMax: Boolean(ticks && ticks.firstElementChild && ticks.lastElementChild),
      bboxes: {label: box(label), value: box(value), output: box(output), unit: box(unit), input: box(input), ticks: box(ticks)}
    };
  });
  const ground = document.querySelector(".ground-cabinet-label");
  return {
    viewport: {innerWidth: window.innerWidth, innerHeight: window.innerHeight, scrollHeight: document.documentElement.scrollHeight, bodyScrollHeight: document.body.scrollHeight},
    panels: panels,
    controlsBody: metrics(controlsBody),
    smallText: smallText,
    sliders: sliders,
    groundCabinet: {text: ground ? ground.textContent.trim() : null, bbox: box(ground), insideScene: ground ? (function () { const a = ground.getBoundingClientRect(); const b = document.querySelector("#simulation-scene").getBoundingClientRect(); return a.left >= b.left - 1 && a.top >= b.top - 1 && a.right <= b.right + 1 && a.bottom <= b.bottom + 1; })() : false}
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
  const labels = Array.from(document.querySelectorAll(".section-label")).filter(function (label) {
    return getComputedStyle(label).display !== "none";
  });
  const viewBox = document.querySelector("#section-svg").viewBox.baseVal;
  const labelData = labels.map(function (label) {
    const b = label.getBBox();
    return {name: label.getAttribute("data-label"), bbox: box(label), svgBox: {x: b.x, y: b.y, width: b.width, height: b.height}};
  });
  return {
    view: scene ? scene.getAttribute("data-view") : null,
    sceneBbox: box(scene),
    svgBbox: box(svg),
    canvasBbox: box(canvas),
    svgVisibility: svg ? getComputedStyle(svg).visibility : null,
    canvasVisibility: canvas ? getComputedStyle(canvas.parentElement).visibility : null,
    labels: labelData
  };
})()
"""

CANVAS_AUDIT = r"""
new Promise(function (resolve) {
  requestAnimationFrame(function () {
    const canvas = document.querySelector("#scene-container canvas");
    if (!canvas) { resolve({available: false}); return; }
    const gl = canvas.getContext("webgl2") || canvas.getContext("webgl");
    if (!gl) { resolve({available: false, context: false}); return; }
    const width = gl.drawingBufferWidth;
    const height = gl.drawingBufferHeight;
    const pixels = new Uint8Array(width * height * 4);
    gl.readPixels(0, 0, width, height, gl.RGBA, gl.UNSIGNED_BYTE, pixels);
    let nonBlack = 0;
    let colored = 0;
    for (let i = 0; i < pixels.length; i += 4) {
      const r = pixels[i];
      const g = pixels[i + 1];
      const b = pixels[i + 2];
      if (r + g + b > 30) nonBlack += 1;
      if (Math.max(r, g, b) - Math.min(r, g, b) > 12) colored += 1;
    }
    const total = width * height;
    resolve({available: true, width: width, height: height, nonBlackRatio: total ? nonBlack / total : 0, coloredRatio: total ? colored / total : 0});
  });
})
"""

CHART_AUDIT = r"""
(function () {
  const ids = ["misalignment-chart", "yaw-chart", "power-chart"];
  return ids.map(function (id) {
    const canvas = document.getElementById(id);
    const rect = canvas ? canvas.getBoundingClientRect() : null;
    const chart = typeof Chart !== "undefined" && canvas ? Chart.getChart(canvas) : null;
    return {
      id: id,
      visible: Boolean(canvas && getComputedStyle(canvas).visibility !== "hidden" && getComputedStyle(canvas.parentElement).visibility !== "hidden" && rect && rect.width > 0 && rect.height > 0),
      width: rect ? rect.width : 0,
      height: rect ? rect.height : 0,
      dataPoints: chart && chart.data && chart.data.datasets && chart.data.datasets[0] ? chart.data.datasets[0].data.length : 0
    };
  });
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


def in_viewport(box_value, viewport):
    return inside(box_value, {"left": 0, "top": 0, "right": viewport["innerWidth"], "bottom": viewport["innerHeight"]})


def audit(width, height):
    page_errors = navigate(width, height)
    data = evaluate(LAYOUT_AUDIT)

    panel_map = {item["key"]: item for item in data["panels"]}
    overlap_pairs = []
    keys = list(panel_map)
    for i in range(len(keys)):
        for j in range(i + 1, len(keys)):
            first = panel_map[keys[i]]
            second = panel_map[keys[j]]
            if intersects(first["bbox"], second["bbox"]):
                overlap_pairs.append([keys[i], keys[j]])

    no_scroll = data["viewport"]["scrollHeight"] <= data["viewport"]["innerHeight"]
    all_visible = all(item["visible"] and in_viewport(item["bbox"], data["viewport"]) for item in data["panels"])
    internal_scroll = {key: item["metrics"]["scrollHeight"] - item["metrics"]["clientHeight"] for key, item in panel_map.items()}
    controls_body_overflow = data["controlsBody"]["scrollHeight"] - data["controlsBody"]["clientHeight"]

    evaluate("document.getElementById('tab-turbine').click()")
    time.sleep(0.2)
    evaluate("document.querySelector('.view-button[data-view=\"3d\"]').click()")
    time.sleep(0.4)
    render_3d = evaluate(CANVAS_AUDIT)

    evaluate("document.querySelector('.view-button[data-view=\"section\"]').click()")
    time.sleep(0.4)
    section_render = evaluate(CANVAS_AUDIT)

    section_views = []
    for view in VIEW_NAMES:
        evaluate('document.querySelector(\'.view-button[data-view="' + view + '"]\').click()')
        time.sleep(0.25)
        view_data = evaluate(VIEW_AUDIT)
        view_data["sceneVisible"] = bool(view_data["sceneBbox"] and view_data["sceneBbox"]["width"] > 0 and view_data["sceneBbox"]["height"] > 0)
        view_data["svgInsideScene"] = inside(view_data["svgBbox"], view_data["sceneBbox"])
        view_data["canvasInsideScene"] = inside(view_data["canvasBbox"], view_data["sceneBbox"])
        view_data["labelsInsideSvgViewBox"] = all(
            item["svgBox"]["x"] >= -1
            and item["svgBox"]["y"] >= -1
            and item["svgBox"]["x"] + item["svgBox"]["width"] <= 901
            and item["svgBox"]["y"] + item["svgBox"]["height"] <= 621
            for item in view_data["labels"]
        )
        view_label_pairs = []
        for i in range(len(view_data["labels"])):
            for j in range(i + 1, len(view_data["labels"])):
                if intersects(view_data["labels"][i]["bbox"], view_data["labels"][j]["bbox"]):
                    view_label_pairs.append([view_data["labels"][i]["name"], view_data["labels"][j]["name"]])
        view_data["labelOverlaps"] = view_label_pairs
        view_data["labelCount"] = len(view_data["labels"])
        section_views.append(view_data)

    evaluate("document.getElementById('tab-output').click()")
    time.sleep(0.4)
    tab_data = evaluate(r"""
    (function () {
      function visibility(id) { return getComputedStyle(document.getElementById(id)).visibility; }
      return {outputChecked: document.getElementById("tab-output").checked, outputVisibility: visibility("output-view"), turbineVisibility: visibility("turbine-view")};
    })()
    """)
    charts_before = evaluate(CHART_AUDIT)
    evaluate("document.getElementById('start-button').click()")
    time.sleep(3.5)
    charts_after = evaluate(CHART_AUDIT)

    evaluate("document.getElementById('tab-turbine').focus()")
    send(
        "Input.dispatchKeyEvent",
        {"type": "rawKeyDown", "key": "ArrowRight", "code": "ArrowRight", "windowsVirtualKeyCode": 39, "nativeVirtualKeyCode": 39},
    )
    send(
        "Input.dispatchKeyEvent",
        {"type": "keyUp", "key": "ArrowRight", "code": "ArrowRight", "windowsVirtualKeyCode": 39, "nativeVirtualKeyCode": 39},
    )
    time.sleep(0.2)
    arrow_right = evaluate("document.getElementById('tab-output').checked")
    evaluate("document.getElementById('tab-output').focus()")
    send(
        "Input.dispatchKeyEvent",
        {"type": "rawKeyDown", "key": "ArrowLeft", "code": "ArrowLeft", "windowsVirtualKeyCode": 37, "nativeVirtualKeyCode": 37},
    )
    send(
        "Input.dispatchKeyEvent",
        {"type": "keyUp", "key": "ArrowLeft", "code": "ArrowLeft", "windowsVirtualKeyCode": 37, "nativeVirtualKeyCode": 37},
    )
    time.sleep(0.2)
    arrow_left = evaluate("document.getElementById('tab-turbine').checked")

    slider_issues = []
    for slider in data["sliders"]:
        if not slider["separateElements"]:
            slider_issues.append({"slider": slider["index"], "issue": "separate-elements"})
        if not slider["hasMinMax"]:
            slider_issues.append({"slider": slider["index"], "issue": "min-max"})
        if slider["labelText"] and ":" in slider["labelText"]:
            slider_issues.append({"slider": slider["index"], "issue": "label-colon"})
        boxes = slider["bboxes"]
        if boxes["label"] and boxes["value"] and boxes["unit"] and not (boxes["label"]["right"] < boxes["value"]["left"] and boxes["output"]["right"] <= boxes["unit"]["left"] + 1):
            slider_issues.append({"slider": slider["index"], "issue": "box-order"})

    svg_fills = evaluate(r"""
    Array.from(document.querySelectorAll("#section-svg [fill]")).map(function (element) {
      return {tag: element.tagName, fill: element.getAttribute("fill"), computed: getComputedStyle(element).fill};
    })
    """)
    black_fills = [item for item in svg_fills if item["computed"] in ("rgb(0, 0, 0)", "black")]

    report = {
        "viewport": data["viewport"],
        "panels": data["panels"],
        "noScroll": no_scroll,
        "allPanelsVisible": all_visible,
        "overlapPairs": overlap_pairs,
        "noPanelOverlap": not overlap_pairs,
        "panelInternalScroll": internal_scroll,
        "controlsBody": data["controlsBody"],
        "controlsBodyScrollAmount": controls_body_overflow,
        "onlyControlsScrolls": all(value <= 1 for key, value in internal_scroll.items()) and controls_body_overflow > 0,
        "tab": tab_data,
        "chartsBeforeStart": charts_before,
        "chartsAfterStart": charts_after,
        "chartsVisible": all(item["visible"] and item["width"] > 0 and item["height"] > 0 for item in charts_after),
        "chartsHaveData": all(item["dataPoints"] > 0 for item in charts_after),
        "arrowKeySupport": arrow_right and arrow_left,
        "render3d": render_3d,
        "renderSection": section_render,
        "views": section_views,
        "viewsNonzero": all(item["sceneVisible"] for item in section_views),
        "svgInsideSceneAllViews": all(item["svgInsideScene"] for item in section_views),
        "canvasInsideSceneAllViews": all(item["canvasInsideScene"] for item in section_views),
        "labelsInsideSvgAllViews": all(item["labelsInsideSvgViewBox"] for item in section_views),
        "labelsAtMostFour": all(item["labelCount"] <= 4 for item in section_views),
        "labelOverlaps": [item for view in section_views for item in view["labelOverlaps"]],
        "blackSvgFills": black_fills,
        "groundCabinet": data["groundCabinet"],
        "smallText": data["smallText"],
        "sliders": data["sliders"],
        "sliderIssues": slider_issues,
        "consoleErrors": drain_errors() + page_errors,
    }
    report["pass"] = (
        report["noScroll"]
        and report["allPanelsVisible"]
        and report["noPanelOverlap"]
        and report["onlyControlsScrolls"]
        and report["tab"]["outputChecked"]
        and report["tab"]["outputVisibility"] == "visible"
        and report["tab"]["turbineVisibility"] == "hidden"
        and report["chartsVisible"]
        and report["chartsHaveData"]
        and report["arrowKeySupport"]
        and report["viewsNonzero"]
        and report["render3d"]["nonBlackRatio"] > 0.01
        and report["render3d"]["coloredRatio"] > 0.001
        and report["svgInsideSceneAllViews"]
        and report["canvasInsideSceneAllViews"]
        and report["labelsInsideSvgAllViews"]
        and report["labelsAtMostFour"]
        and not report["labelOverlaps"]
        and not report["blackSvgFills"]
        and report["groundCabinet"]["insideScene"]
        and not report["smallText"]
        and not report["sliderIssues"]
        and not report["consoleErrors"]
    )
    return report


def capture(width, height, path):
    navigate(width, height)
    evaluate("window.scrollTo(0, 0)")
    time.sleep(0.4)
    png = send("Page.captureScreenshot", {"format": "png", "captureBeyondViewport": False})["data"]
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
    baseline = json.loads((ROOT / "assets" / "data" / "results.json").read_text(encoding="utf-8"))
    median_settle = baseline["metrics"]["settling_time_s"]["value"]
    min_settle = baseline["metrics"]["settling_time_s"]["range"]["min"]
    max_settle = baseline["metrics"]["settling_time_s"]["range"]["max"]
    previous_final_error = 2.73
    current_settle = round(settling, 2) if settling is not None else None
    current_final_error = round(samples[-1]["e"], 2) if samples else None
    within_range = current_settle is not None and min_settle <= current_settle <= max_settle
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
            "resultsJsonSettleRangeS": [min_settle, max_settle],
            "previousRunFinalErrorDeg": previous_final_error,
            "settleDeltaS": round(current_settle - median_settle, 2) if current_settle is not None else None,
            "finalErrorDeltaDeg": round(current_final_error - previous_final_error, 2) if current_final_error is not None else None,
            "settlingWithinMeasuredRange": within_range,
            "withinNormalVariation": (
                within_range
                and current_final_error is not None
                and abs(current_final_error - previous_final_error) <= 3
            ),
        },
        "consoleErrors": drain_errors(),
    }


try:
    if not requests.get(BASE, timeout=2).ok:
        raise RuntimeError("Local server is not serving " + BASE)
    report = {"label": args.label, "widths": {}}
    for width, height in [(1440, 900), (1280, 720)]:
        report["widths"][str(width)] = audit(width, height)
        report["widths"][str(width)]["screenshot"] = capture(
            width,
            height,
            "screenshots/single-screen-1440.png" if width == 1440 else "screenshots/single-screen-1280.png",
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
