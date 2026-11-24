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

parser = argparse.ArgumentParser()
parser.add_argument("--label", default="after")
parser.add_argument("--screenshot")
parser.add_argument("--stable", action="store_true")
parser.add_argument("--baseline", action="store_true")
args = parser.parse_args()

all_console_errors = []

sock = socket.socket()
sock.bind(("127.0.0.1", 0))
PORT = sock.getsockname()[1]
sock.close()

profile = tempfile.mkdtemp(prefix="nacelle-overlap-check-")
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


ELEMENT_AUDIT = r"""
(function () {
  const all = Array.from(document.querySelectorAll("body *"));
  const indices = new Map(all.map(function (element, index) { return [element, index]; }));
  function nameOf(element) {
    const id = element.id ? "#" + element.id : "";
    const classAttribute = element.getAttribute("class") || "";
    const cls = classAttribute.trim() ? "." + classAttribute.trim().split(/\s+/).join(".") : "";
    const dataLabel = element.getAttribute("data-label") ? "[data-label=\"" + element.getAttribute("data-label") + "\"]" : "";
    return element.tagName.toLowerCase() + id + cls + dataLabel;
  }
  function categoryOf(element) {
    if (element.tagName.toLowerCase() === "g" && element.classList.contains("section-label")) return "label";
    if (element.closest(".section-label")) return "scene";
    if (element.id === "section-wind-label" || element.classList.contains("wind-caption")) return "label";
    if (element.closest(".section-readouts") || element.closest(".readouts-panel")) return "readout";
    if (element.closest(".controls-card") || element.closest(".control-group")) return "control";
    if (element.closest(".chart-section") || element.closest(".chart-card")) return "graph";
    if (element.classList.contains("view-area") || element.id === "simulation-scene" || element.id === "scene-container" || element.id === "section-view" || element.id === "section-svg") return "view";
    if (element.closest(".workflow-panel")) return "workflow";
    if (element.closest("#section-svg") || element.closest("#scene-container")) return "scene";
    return "other";
  }
  function areaOf(element) {
    let area = element.closest("[data-grid-area]");
    let areaName = area ? area.dataset.gridArea : null;
    if (!area) {
      area = element.closest(".simulation-view, .chart-section, .controls-card, .section-readouts, .readouts-panel, .workflow-panel");
      areaName = area ? nameOf(area) : null;
    }
    if (!area || area === element) return {area: areaName, rect: null};
    const rect = area.getBoundingClientRect();
    return {
      area: areaName,
      rect: {left: rect.left, top: rect.top, right: rect.right, bottom: rect.bottom, width: rect.width, height: rect.height}
    };
  }
  const elements = [];
  all.forEach(function (element, index) {
    const style = getComputedStyle(element);
    if (style.display === "none" || style.visibility === "hidden" || style.opacity === "0") return;
    const rect = element.getBoundingClientRect();
    if (rect.width <= 0 || rect.height <= 0) return;
    const ancestors = [];
    let parent = element.parentElement;
    while (parent) {
      const parentIndex = indices.get(parent);
      if (parentIndex !== undefined) ancestors.push(parentIndex);
      parent = parent.parentElement;
    }
    const area = areaOf(element);
    elements.push({
      index: index,
      name: nameOf(element),
      tag: element.tagName.toLowerCase(),
      id: element.id || null,
      className: element.getAttribute("class") || "",
      dataLabel: element.getAttribute("data-label"),
      inSectionLabel: Boolean(element.closest(".section-label")),
      category: categoryOf(element),
      position: style.position,
      rect: {left: rect.left, top: rect.top, right: rect.right, bottom: rect.bottom, width: rect.width, height: rect.height},
      ancestors: ancestors,
      area: area.area,
      areaRect: area.rect
    });
  });
  const visibleLabelGroups = elements.filter(function (item) {
    return item.tag === "g" && item.className.split(/\s+/).indexOf("section-label") !== -1;
  });
  const labelRects = elements.filter(function (item) {
    return item.inSectionLabel && item.tag === "rect";
  });
  const gearbox = visibleLabelGroups.find(function (item) { return item.dataLabel === "5"; });
  const generator = visibleLabelGroups.find(function (item) { return item.dataLabel === "4"; });
  const svg = document.getElementById("section-svg");
  const svgRect = svg ? svg.getBoundingClientRect() : null;
  const scene = document.getElementById("scene-container");
  const simulationScene = document.getElementById("simulation-scene");
  const sceneRect = simulationScene ? simulationScene.getBoundingClientRect() : null;
  const wind = document.querySelector(".wind-caption, #section-wind-label");
  const windRect = wind ? wind.getBoundingClientRect() : null;
  const windArea = wind ? areaOf(wind) : null;
  const labelsOutsideSvg = visibleLabelGroups.filter(function (item) {
    if (!svgRect) return false;
    const rect = item.rect;
    return rect.left < svgRect.left - 1 || rect.top < svgRect.top - 1 || rect.right > svgRect.right + 1 || rect.bottom > svgRect.bottom + 1;
  });
  const sliders = Array.from(document.querySelectorAll(".slider-control")).map(function (slider, index) {
    const label = slider.querySelector(".slider-label");
    const value = slider.querySelector(".slider-value");
    const ticks = slider.querySelector(".slider-ticks");
    const rectOf = function (node) {
      if (!node) return null;
      const rect = node.getBoundingClientRect();
      return {left: rect.left, top: rect.top, right: rect.right, bottom: rect.bottom, width: rect.width, height: rect.height};
    };
    return {index: index, label: rectOf(label), value: rectOf(value), ticks: rectOf(ticks)};
  });
  return {
    elements: elements,
    labelCount: visibleLabelGroups.length,
    labelRects: labelRects,
    labelsOutsideSvg: labelsOutsideSvg.map(function (item) { return {name: item.name, rect: item.rect}; }),
    gearbox: gearbox ? {name: gearbox.name, rect: gearbox.rect} : null,
    generator: generator ? {name: generator.name, rect: generator.rect} : null,
    staticSvgPosition: svg ? getComputedStyle(svg).position : null,
    staticScenePosition: scene ? getComputedStyle(scene).position : null,
    gridAreas: Array.from(document.querySelectorAll("[data-grid-area]")).map(function (item) { return item.dataset.gridArea; }),
    windCaption: windRect ? {
      name: nameOf(wind),
      rect: {left: windRect.left, top: windRect.top, right: windRect.right, bottom: windRect.bottom, width: windRect.width, height: windRect.height},
      area: windArea ? windArea.area : null,
      areaIsView: Boolean(windArea && windArea.area === "view"),
      aboveScene: Boolean(sceneRect && windRect.bottom <= sceneRect.top + 1)
    } : null,
    sliders: sliders
  };
})()
"""


def wait_for_label_set():
    latest = None
    for _ in range(60):
        latest = evaluate(ELEMENT_AUDIT)
        if latest["gearbox"] and latest["generator"]:
            return latest
        time.sleep(0.2)
    return latest


def intersects(a, b):
    return min(a["right"], b["right"]) - max(a["left"], b["left"]) > 1 and min(a["bottom"], b["bottom"]) - max(a["top"], b["top"]) > 1


def audit(width, height):
    page_errors = navigate(width, height)
    evaluate('document.querySelector(\'.view-button[data-view="section"]\').click()')
    time.sleep(0.5)
    data = wait_for_label_set()
    elements = data["elements"]
    by_index = {item["index"]: item for item in elements}

    all_pairs = []
    target_categories = {"label", "readout", "control", "graph", "view"}
    target_pairs = []
    for i in range(len(elements)):
        first = elements[i]
        for j in range(i + 1, len(elements)):
            second = elements[j]
            if first["index"] in second["ancestors"] or second["index"] in first["ancestors"]:
                continue
            if not intersects(first["rect"], second["rect"]):
                continue
            pair = {
                "first": first["name"],
                "second": second["name"],
                "firstCategory": first["category"],
                "secondCategory": second["category"],
            }
            all_pairs.append(pair)
            if first["category"] in target_categories and second["category"] in target_categories:
                target_pairs.append(pair)

    outside_area = []
    for item in elements:
        area = item["areaRect"]
        if not area:
            continue
        rect = item["rect"]
        if (
            rect["left"] < area["left"] - 1
            or rect["top"] < area["top"] - 1
            or rect["right"] > area["right"] + 1
            or rect["bottom"] > area["bottom"] + 1
        ):
            outside_area.append({"name": item["name"], "area": item["area"], "rect": rect, "areaRect": area})

    absolute_outside = []
    for item in elements:
        if item["position"] not in ("absolute", "fixed"):
            continue
        parent_index = item["ancestors"][0] if item["ancestors"] else None
        parent = by_index.get(parent_index)
        if not parent:
            continue
        rect = item["rect"]
        parent_rect = parent["rect"]
        if (
            rect["left"] < parent_rect["left"] - 1
            or rect["top"] < parent_rect["top"] - 1
            or rect["right"] > parent_rect["right"] + 1
            or rect["bottom"] > parent_rect["bottom"] + 1
        ):
            absolute_outside.append({"name": item["name"], "parent": parent["name"], "rect": rect, "parentRect": parent_rect})

    label_pair_overlaps = []
    label_rects = data["labelRects"]
    for i in range(len(label_rects)):
        for j in range(i + 1, len(label_rects)):
            if intersects(label_rects[i]["rect"], label_rects[j]["rect"]):
                label_pair_overlaps.append({"first": label_rects[i]["name"], "second": label_rects[j]["name"]})

    slider_issues = []
    for slider in data["sliders"]:
        label = slider["label"]
        value = slider["value"]
        ticks = slider["ticks"]
        if not label or not value:
            continue
        gap = value["left"] - label["right"]
        if gap < 7.5:
            slider_issues.append({"slider": slider["index"], "pair": "label-value", "gap": round(gap, 2)})
        if ticks and label and ticks["top"] - label["bottom"] < 7.5:
            slider_issues.append({"slider": slider["index"], "pair": "label-ticks", "gap": round(ticks["top"] - label["bottom"], 2)})

    report = {
        "visibleElements": len(elements),
        "allIntersectingPairs": all_pairs,
        "allIntersectingPairCount": len(all_pairs),
        "targetIntersectingPairs": target_pairs,
        "targetIntersectingPairCount": len(target_pairs),
        "outsideGridArea": outside_area,
        "outsideGridAreaCount": len(outside_area),
        "absoluteOutsideParent": absolute_outside,
        "absoluteOutsideParentCount": len(absolute_outside),
        "visibleSectionLabels": data["labelCount"],
        "labelRectOverlaps": label_pair_overlaps,
        "labelRectOverlapCount": len(label_pair_overlaps),
        "labelsOutsideSvg": data["labelsOutsideSvg"],
        "labelsOutsideSvgCount": len(data["labelsOutsideSvg"]),
        "gearbox": data["gearbox"],
        "generator": data["generator"],
        "gearboxGeneratorDifferentRows": bool(
            data["gearbox"]
            and data["generator"]
            and abs(data["gearbox"]["rect"]["top"] - data["generator"]["rect"]["top"]) > 20
        ),
        "svgPosition": data["staticSvgPosition"],
        "scenePosition": data["staticScenePosition"],
        "gridAreas": data["gridAreas"],
        "windCaption": data["windCaption"],
        "sliderIssues": slider_issues,
        "sliderIssueCount": len(slider_issues),
        "consoleErrors": drain_errors() + page_errors,
    }
    return report


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

    if args.screenshot:
        navigate(1440, 900)
        evaluate('document.querySelector(\'.view-button[data-view="section"]\').click()')
        evaluate("window.scrollTo(0, 0)")
        wait_for_label_set()
        time.sleep(0.2)
        png = send("Page.captureScreenshot", {"format": "png", "captureBeyondViewport": False})["data"]
        path = Path(args.screenshot)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(base64.b64decode(png))
        report["screenshot"] = str(path)

    if args.stable:
        report["stableRun"] = stable_run()

    report["consoleErrors"] = sorted(set(all_console_errors))
    if not args.baseline:
        report["pass"] = (
            all(
                item["targetIntersectingPairCount"] == 0
                and item["outsideGridAreaCount"] == 0
                and item["absoluteOutsideParentCount"] == 0
                and                 item["labelRectOverlapCount"] == 0
                and item["labelsOutsideSvgCount"] == 0
                and item["visibleSectionLabels"] <= 4
                and item["gearboxGeneratorDifferentRows"]
                and item["sliderIssueCount"] == 0
                and item["svgPosition"] == "static"
                and item["scenePosition"] == "static"
                and item["windCaption"] is not None
                and item["windCaption"]["areaIsView"]
                and item["windCaption"]["aboveScene"]
                for item in report["widths"].values()
            )
            and (not args.stable or report["stableRun"]["comparison"]["withinNormalVariation"])
            and not report["consoleErrors"]
        )
    print(json.dumps(report, indent=2))
    raise SystemExit(0 if args.baseline or report.get("pass", False) else 1)
finally:
    try:
        ws.close()
    except Exception:
        pass
    chrome.terminate()
