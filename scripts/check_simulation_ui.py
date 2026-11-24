import base64
import io
import json
import os
import socket
import subprocess
import tempfile
import time
from pathlib import Path

import requests
from websocket import create_connection
from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
BASE = "http://localhost:8000/simulation.html"
CHROME = r"C:\Program Files\Google\Chrome\Application\chrome.exe"
SHOT = ROOT / "screenshots" / "ui-simulation-1440-fixed.png"
PALETTE = {
    "#0b1220",
    "#111a2e",
    "#1f2d46",
    "#e2e8f0",
    "#94a3b8",
    "#22d3ee",
    "#22c55e",
    "#f59e0b",
    "#ef4444",
    "#cbd5e1",
    "none",
}

all_console_errors = []

sock = socket.socket()
sock.bind(("127.0.0.1", 0))
PORT = sock.getsockname()[1]
sock.close()

profile = tempfile.mkdtemp(prefix="nacelle-fix-check-")
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


FONT_CHECK = r"""
(function () {
  const targets = [];
  document.querySelectorAll(".site-footer, .section-readouts").forEach(function (root) {
    const walker = document.createTreeWalker(root, NodeFilter.SHOW_TEXT);
    while (walker.nextNode()) {
      const node = walker.currentNode;
      if (!node.textContent.trim()) continue;
      const parent = node.parentElement;
      const size = parseFloat(getComputedStyle(parent).fontSize);
      targets.push({scope: root.className, tag: parent.tagName, text: node.textContent.trim().slice(0, 60), fontSize: size});
    }
  });
  const below14 = targets.filter(function (item) { return item.fontSize < 14; });
  const sizes = targets.map(function (item) { return item.fontSize; });
  return {
    checkedTextNodes: targets.length,
    minFontSize: sizes.length ? Math.min.apply(null, sizes) : null,
    maxFontSize: sizes.length ? Math.max.apply(null, sizes) : null,
    below14: below14
  };
})()
"""

CHART_FONT_CHECK = r"""
(function () {
  if (typeof Chart === "undefined") return {available: false, below14: []};
  const below14 = [];
  const defaults = parseFloat(Chart.defaults.font.size);
  if (!Number.isFinite(defaults) || defaults < 14) {
    below14.push({scope: "Chart.defaults.font.size", fontSize: defaults});
  }
  const instances = Chart.instances ? Object.values(Chart.instances) : [];
  const effective = function (value) {
    const parsed = parseFloat(value);
    return Number.isFinite(parsed) ? parsed : defaults;
  };
  instances.forEach(function (chart, index) {
    Object.keys(chart.scales || {}).forEach(function (key) {
      const options = chart.scales[key].options || {};
      const tick = effective(options.ticks && options.ticks.font && options.ticks.font.size);
      const title = effective(options.title && options.title.font && options.title.font.size);
      if (tick < 14) below14.push({scope: "chart " + index + " " + key + " ticks", fontSize: tick});
      if (options.title && options.title.display && title < 14) {
        below14.push({scope: "chart " + index + " " + key + " title", fontSize: title});
      }
    });
  });
  return {available: true, defaultsFontSize: defaults, chartCount: instances.length, below14: below14};
})()
"""

SVG_FILL_CHECK = r"""
(function () {
  function normalize(value) {
    if (!value) return "";
    const text = String(value).trim().toLowerCase();
    if (text === "none") return "none";
    const match = text.match(/rgba?\((\d+),\s*(\d+),\s*(\d+)/);
    if (match) {
      return "#" + [match[1], match[2], match[3]].map(function (part) {
        return Number(part).toString(16).padStart(2, "0");
      }).join("");
    }
    return text;
  }
  const palette = new Set(["#0b1220", "#111a2e", "#1f2d46", "#e2e8f0", "#94a3b8", "#22d3ee", "#22c55e", "#f59e0b", "#ef4444", "#cbd5e1", "none"]);
  const bad = [];
  const elements = Array.from(document.querySelectorAll("#section-view svg, #section-view svg *"));
  elements.forEach(function (element) {
    const attr = element.getAttribute("fill");
    const computed = getComputedStyle(element).fill;
    const value = normalize(attr || computed);
    if (!palette.has(value)) {
      bad.push({tag: element.tagName, id: element.id || null, fillAttribute: attr, computedFill: computed, normalized: value});
    }
  });
  return {checkedElements: elements.length, badFills: bad};
})()
"""


def sample_pixels(selector):
    evaluate(
        "(function () { const el = document.querySelector(" + json.dumps(selector) + "); if (!el) return false; el.scrollIntoView({block: 'center'}); return true; })()"
    )
    time.sleep(0.3)
    rect = evaluate(
        "(function () { const el = document.querySelector(" + json.dumps(selector) + "); const r = el.getBoundingClientRect(); return {x: r.x, y: r.y, width: r.width, height: r.height}; })()"
    )
    if not rect or rect["width"] <= 0 or rect["height"] <= 0:
        return {"error": "container has no visible area", "rect": rect}
    png = send(
        "Page.captureScreenshot",
        {
            "format": "png",
            "captureBeyondViewport": False,
            "fromSurface": True,
            "clip": {
                "x": rect["x"],
                "y": rect["y"],
                "width": rect["width"],
                "height": rect["height"],
                "scale": 1,
            },
        },
    )["data"]
    image = Image.open(io.BytesIO(base64.b64decode(png))).convert("RGB")
    pixels = list(image.get_flattened_data() if hasattr(image, "get_flattened_data") else image.getdata())
    total = len(pixels)
    pure = sum(1 for red, green, blue in pixels if red == 0 and green == 0 and blue == 0)
    near = sum(1 for red, green, blue in pixels if max(red, green, blue) <= 8)
    return {
        "rect": rect,
        "totalPixels": total,
        "pureBlackPixels": pure,
        "nearBlackPixels": near,
        "pureBlackShare": round(pure / total, 6) if total else None,
        "nearBlackShare": round(near / total, 6) if total else None,
        "underTwoPercent": near / total < 0.02 if total else False,
    }


def run():
    report = {"widths": {}, "consoleErrors": []}

    for width, height in [(1440, 900), (375, 812)]:
        page_errors = navigate(width, height)
        scene_pixels = sample_pixels("#scene-container")
        evaluate('document.querySelector(\'.view-button[data-view="section"]\').click()')
        time.sleep(0.4)
        section_pixels = sample_pixels("#section-view")
        fonts = evaluate(FONT_CHECK)
        chart_fonts = evaluate(CHART_FONT_CHECK)
        svg_fills = evaluate(SVG_FILL_CHECK)
        report["widths"][str(width)] = {
            "sectionViewPixels": section_pixels,
            "scenePixels": scene_pixels,
            "fonts": fonts,
            "chartFonts": chart_fonts,
            "svgFills": svg_fills,
            "consoleErrors": drain_errors() + page_errors,
        }

    navigate(1440, 900)
    evaluate('document.querySelector(\'.view-button[data-view="section"]\').click()')
    evaluate("window.scrollTo(0, 0)")
    time.sleep(0.4)
    screenshot = send("Page.captureScreenshot", {"format": "png", "captureBeyondViewport": False})["data"]
    SHOT.write_bytes(base64.b64decode(screenshot))
    report["screenshot"] = str(SHOT)

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
    report["stableRun"] = {
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

    report["consoleErrors"] = sorted(set(all_console_errors))
    report["pass"] = (
        all(
            item["sectionViewPixels"].get("underTwoPercent")
            and item["scenePixels"].get("underTwoPercent")
            and not item["fonts"]["below14"]
            and not item["chartFonts"]["below14"]
            and not item["svgFills"]["badFills"]
            for item in report["widths"].values()
        )
        and report["stableRun"]["comparison"]["withinNormalVariation"]
        and not report["consoleErrors"]
    )
    return report


try:
    if not requests.get(BASE, timeout=2).ok:
        raise RuntimeError("Local server is not serving " + BASE)
    result = run()
    print(json.dumps(result, indent=2))
    raise SystemExit(0 if result["pass"] else 1)
finally:
    try:
        ws.close()
    except Exception:
        pass
    chrome.terminate()
