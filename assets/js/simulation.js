(function () {
  "use strict";

  // CONFIG
  const THREE_URL = "https://cdnjs.cloudflare.com/ajax/libs/three.js/0.187.0/three.module.js";
  const SCENE_HEIGHT = 120;
  const TOWER_HEIGHT = SCENE_HEIGHT * 0.55;
  const PAD_HEIGHT = 1.4;
  const FIXED_STEP = 0.02;
  const DEG_TO_RAD = Math.PI / 180;
  const ROTOR_RPM_AT_REF = 14;
  const GEAR_RATIO = 50;

  const PRESETS = {
    stable: { kp: 1.2, kd: 0.6, deadband: 0.5, maxRate: 4, lag: 0.3, noise: 1.5, delay: 0.4 },
    aggressive: { kp: 2.8, kd: 0, deadband: 0.2, maxRate: 8, lag: 0.2, noise: 1.5, delay: 1 },
    sluggish: { kp: 0.3, kd: 0.1, deadband: 1, maxRate: 1.5, lag: 1, noise: 1, delay: 0.2 }
  };

  const state = {
    running: false,
    time: 0,
    accumulator: 0,
    heading: 0,
    trueWindDirection: 100,
    windTarget: 100,
    windChangeTimer: 7,
    gusts: false,
    gustPhase: 0,
    sensorQueue: [],
    sensorReading: 0,
    previousError: 0,
    filteredDerivative: 0,
    yawRate: 0,
    yawCommand: 0,
    power: 0,
    bladeAngle: 0,
    status: "IDLE",
    alignedTime: 0,
    faultTime: 0,
    hasAligned: false,
    params: {
      kp: 1.2,
      kd: 0.6,
      deadband: 0.5,
      maxRate: 4,
      lag: 0.3,
      noise: 1.5,
      delay: 0.4,
      windSpeed: 12
    }
  };

  window.simulationState = state;

  import(THREE_URL).then(function (THREE) {
    start(THREE);
  }).catch(function (error) {
    console.error("Unable to load the 3D scene library.", error);
  });

  function start(THREE) {
    const container = document.getElementById("scene-container");
    if (!container) return;

    // SCENE
    const scene = new THREE.Scene();
    scene.fog = new THREE.Fog(0xbcdcf5, 190, 470);

    const skyGeometry = new THREE.SphereGeometry(500, 32, 16);
    const skyMaterial = new THREE.ShaderMaterial({
      uniforms: {
        topColor: { value: new THREE.Color(0x1e5aa8) },
        bottomColor: { value: new THREE.Color(0xd9ecfb) },
        offset: { value: 30 },
        exponent: { value: 0.7 }
      },
      vertexShader: [
        "varying vec3 vWorldPosition;",
        "void main() {",
        "  vec4 worldPosition = modelMatrix * vec4(position, 1.0);",
        "  vWorldPosition = worldPosition.xyz;",
        "  gl_Position = projectionMatrix * modelViewMatrix * vec4(position, 1.0);",
        "}"
      ].join("\n"),
      fragmentShader: [
        "uniform vec3 topColor;",
        "uniform vec3 bottomColor;",
        "uniform float offset;",
        "uniform float exponent;",
        "varying vec3 vWorldPosition;",
        "void main() {",
        "  float h = normalize(vWorldPosition + vec3(0.0, offset, 0.0)).y;",
        "  float t = pow(max(h, 0.0), exponent);",
        "  gl_FragColor = vec4(mix(bottomColor, topColor, t), 1.0);",
        "}"
      ].join("\n"),
      side: THREE.BackSide,
      depthWrite: false
    });
    scene.add(new THREE.Mesh(skyGeometry, skyMaterial));

    const groundGeometry = new THREE.PlaneGeometry(320, 320, 96, 96);
    groundGeometry.rotateX(-Math.PI / 2);
    const groundPositions = groundGeometry.attributes.position;
    for (let i = 0; i < groundPositions.count; i += 1) {
      const x = groundPositions.getX(i);
      const z = groundPositions.getZ(i);
      const height = Math.sin(x * 0.07) * Math.cos(z * 0.06) * 0.55 + Math.sin((x + z) * 0.03) * 0.35;
      groundPositions.setY(i, height);
    }
    groundGeometry.computeVertexNormals();
    const ground = new THREE.Mesh(groundGeometry, new THREE.MeshStandardMaterial({
      color: 0x5d8a4a,
      roughness: 1,
      metalness: 0
    }));
    ground.receiveShadow = true;
    scene.add(ground);

    const renderer = new THREE.WebGLRenderer({ antialias: true });
    renderer.setPixelRatio(Math.min(window.devicePixelRatio || 1, 2));
    renderer.shadowMap.enabled = true;
    renderer.shadowMap.type = THREE.PCFSoftShadowMap;
    renderer.outputColorSpace = THREE.SRGBColorSpace;
    renderer.toneMapping = THREE.ACESFilmicToneMapping;
    renderer.toneMappingExposure = 1.05;
    container.appendChild(renderer.domElement);

    // LIGHTING
    scene.add(new THREE.HemisphereLight(0xcfe9ff, 0x4b6b3c, 1.6));

    const sun = new THREE.DirectionalLight(0xfff1d2, 2.4);
    sun.position.set(90, 150, 70);
    sun.castShadow = true;
    sun.shadow.mapSize.set(2048, 2048);
    sun.shadow.camera.left = -130;
    sun.shadow.camera.right = 130;
    sun.shadow.camera.top = 150;
    sun.shadow.camera.bottom = -60;
    sun.shadow.camera.near = 1;
    sun.shadow.camera.far = 420;
    sun.shadow.bias = -0.0004;
    sun.shadow.radius = 4;
    sun.target.position.set(0, 30, 0);
    scene.add(sun);
    scene.add(sun.target);

    // TURBINE MODEL
    const concreteMaterial = new THREE.MeshStandardMaterial({ color: 0xa8adb3, roughness: 0.95 });
    const steelMaterial = new THREE.MeshStandardMaterial({ color: 0xd7e2ec, metalness: 0.65, roughness: 0.35 });
    const darkMaterial = new THREE.MeshStandardMaterial({ color: 0x34465c, metalness: 0.6, roughness: 0.4 });
    const bladeMaterial = new THREE.MeshStandardMaterial({ color: 0xf1f5f9, metalness: 0.1, roughness: 0.5 });
    const cabinetMaterial = new THREE.MeshStandardMaterial({ color: 0x3f6f77, metalness: 0.25, roughness: 0.6 });
    const accentMaterial = new THREE.MeshStandardMaterial({ color: 0x22d3ee, metalness: 0.3, roughness: 0.4 });

    function addShadow(mesh) {
      mesh.castShadow = true;
      mesh.receiveShadow = true;
      return mesh;
    }

    function createRoundedBox(width, height, depth, radius, material) {
      const shape = new THREE.Shape();
      const x = -width / 2;
      const y = -height / 2;
      shape.moveTo(x + radius, y);
      shape.lineTo(x + width - radius, y);
      shape.quadraticCurveTo(x + width, y, x + width, y + radius);
      shape.lineTo(x + width, y + height - radius);
      shape.quadraticCurveTo(x + width, y + height, x + width - radius, y + height);
      shape.lineTo(x + radius, y + height);
      shape.quadraticCurveTo(x, y + height, x, y + height - radius);
      shape.lineTo(x, y + radius);
      shape.quadraticCurveTo(x, y, x + radius, y);

      const geometry = new THREE.ExtrudeGeometry(shape, {
        depth: depth,
        bevelEnabled: true,
        bevelThickness: 0.22,
        bevelSize: 0.22,
        bevelSegments: 3,
        curveSegments: 8
      });
      geometry.center();
      return addShadow(new THREE.Mesh(geometry, material));
    }

    const turbine = new THREE.Group();
    scene.add(turbine);

    const pad = addShadow(new THREE.Mesh(new THREE.CylinderGeometry(8, 8.6, PAD_HEIGHT, 40), concreteMaterial));
    pad.position.y = PAD_HEIGHT / 2;
    turbine.add(pad);

    const towerTopY = PAD_HEIGHT + TOWER_HEIGHT;
    const tower = addShadow(new THREE.Mesh(new THREE.CylinderGeometry(1.7, 3.4, TOWER_HEIGHT, 32), steelMaterial));
    tower.position.y = PAD_HEIGHT + TOWER_HEIGHT / 2;
    turbine.add(tower);

    const cabinet = new THREE.Group();
    const cabinetBody = addShadow(new THREE.Mesh(new THREE.BoxGeometry(4.6, 5.6, 3.2), cabinetMaterial));
    cabinetBody.position.y = 2.8;
    cabinet.add(cabinetBody);
    const cabinetDoor = addShadow(new THREE.Mesh(new THREE.BoxGeometry(3.4, 4.4, 0.12), darkMaterial));
    cabinetDoor.position.set(0, 2.8, 1.66);
    cabinet.add(cabinetDoor);
    const cabinetHandle = new THREE.Mesh(new THREE.BoxGeometry(0.14, 0.7, 0.12), accentMaterial);
    cabinetHandle.position.set(1.1, 2.8, 1.78);
    cabinet.add(cabinetHandle);
    cabinet.position.set(6.2, PAD_HEIGHT, 2.4);
    turbine.add(cabinet);

    const bearingCore = addShadow(new THREE.Mesh(new THREE.CylinderGeometry(2.1, 2.1, 0.6, 32), darkMaterial));
    bearingCore.position.y = towerTopY + 0.3;
    turbine.add(bearingCore);
    const bearingRing = addShadow(new THREE.Mesh(new THREE.TorusGeometry(2.3, 0.38, 14, 48), darkMaterial));
    bearingRing.rotation.x = Math.PI / 2;
    bearingRing.position.y = towerTopY + 0.6;
    turbine.add(bearingRing);

    const yawAssembly = new THREE.Group();
    yawAssembly.position.y = towerTopY;
    turbine.add(yawAssembly);

    const nacelleWidth = 4.6;
    const nacelleHeight = 3.8;
    const nacelleDepth = 7.5;
    const nacelleY = 2.9;
    const nacelle = createRoundedBox(nacelleWidth, nacelleHeight, nacelleDepth, 0.9, steelMaterial);
    nacelle.position.set(0, nacelleY, 0);
    yawAssembly.add(nacelle);

    const roofY = nacelleHeight / 2 + 0.22;

    const vaneMast = addShadow(new THREE.Mesh(new THREE.CylinderGeometry(0.09, 0.09, 2.2, 10), darkMaterial));
    vaneMast.position.set(-1.2, roofY + 1.1, -1.6);
    yawAssembly.add(vaneMast);
    const vaneFin = addShadow(new THREE.Mesh(new THREE.BoxGeometry(0.08, 0.85, 1.5), accentMaterial));
    vaneFin.position.set(-1.2, roofY + 2.2, -1.85);
    yawAssembly.add(vaneFin);
    const vaneArrow = addShadow(new THREE.Mesh(new THREE.ConeGeometry(0.42, 0.9, 3), accentMaterial));
    vaneArrow.rotation.x = Math.PI / 2;
    vaneArrow.position.set(-1.2, roofY + 2.2, -0.85);
    yawAssembly.add(vaneArrow);

    const anemometer = new THREE.Group();
    anemometer.position.set(1.3, roofY + 2.05, -1.6);
    anemometer.add(addShadow(new THREE.Mesh(new THREE.CylinderGeometry(0.09, 0.09, 2.0, 10), darkMaterial)));
    anemometer.children[0].position.y = -1.0;
    anemometer.add(addShadow(new THREE.Mesh(new THREE.SphereGeometry(0.22, 12, 8), darkMaterial)));
    for (let i = 0; i < 3; i += 1) {
      const spoke = new THREE.Group();
      spoke.rotation.y = (i * Math.PI * 2) / 3;
      const arm = addShadow(new THREE.Mesh(new THREE.BoxGeometry(1.2, 0.07, 0.07), darkMaterial));
      arm.position.x = 0.6;
      const cup = addShadow(new THREE.Mesh(new THREE.SphereGeometry(0.26, 12, 8), accentMaterial));
      cup.position.x = 1.2;
      spoke.add(arm);
      spoke.add(cup);
      anemometer.add(spoke);
    }
    yawAssembly.add(anemometer);

    const rotor = new THREE.Group();
    rotor.position.set(0, nacelleY, nacelleDepth / 2 + 1.3);
    yawAssembly.add(rotor);

    const hub = addShadow(new THREE.Mesh(new THREE.SphereGeometry(1.5, 24, 16), steelMaterial));
    hub.scale.z = 1.25;
    rotor.add(hub);
    const nose = addShadow(new THREE.Mesh(new THREE.ConeGeometry(1.45, 2.0, 24), steelMaterial));
    nose.rotation.x = Math.PI / 2;
    nose.position.z = 1.7;
    rotor.add(nose);

    const bladeGeometry = new THREE.CylinderGeometry(0.14, 0.95, 26, 10);
    bladeGeometry.translate(0, 13, 0);
    for (let i = 0; i < 3; i += 1) {
      const pivot = new THREE.Group();
      pivot.rotation.z = (i * Math.PI * 2) / 3;
      const blade = addShadow(new THREE.Mesh(bladeGeometry, bladeMaterial));
      blade.scale.z = 0.32;
      blade.rotation.y = 0.16;
      pivot.add(blade);
      rotor.add(pivot);
    }

    // CAMERA
    const camera = new THREE.PerspectiveCamera(45, 1, 0.1, 2000);
    camera.position.set(72, 52, 118);

    class OrbitControls {
      constructor(cameraInstance, domElement) {
        this.camera = cameraInstance;
        this.domElement = domElement;
        this.target = new THREE.Vector3();
        this.minDistance = 35;
        this.maxDistance = 360;
        this.minPolarAngle = 0.12;
        this.maxPolarAngle = Math.PI / 2 - 0.03;
        this.rotateSpeed = 0.0045;
        this.zoomSpeed = 0.0012;
        this.enableDamping = true;
        this.dampingFactor = 0.09;
        this.dragging = false;
        this.lastX = 0;
        this.lastY = 0;
        this.scale = 1;
        this.offset = new THREE.Vector3();
        this.spherical = new THREE.Spherical();
        this.sphericalDelta = new THREE.Spherical();

        this.onPointerDown = this.handlePointerDown.bind(this);
        this.onPointerMove = this.handlePointerMove.bind(this);
        this.onPointerUp = this.handlePointerUp.bind(this);
        this.onWheel = this.handleWheel.bind(this);
        this.onContextMenu = function (event) { event.preventDefault(); };

        domElement.addEventListener("pointerdown", this.onPointerDown);
        domElement.addEventListener("pointermove", this.onPointerMove);
        domElement.addEventListener("pointerup", this.onPointerUp);
        domElement.addEventListener("pointercancel", this.onPointerUp);
        domElement.addEventListener("wheel", this.onWheel, { passive: false });
        domElement.addEventListener("contextmenu", this.onContextMenu);

        this.update();
      }

      handlePointerDown(event) {
        if (event.button !== 0) return;
        this.dragging = true;
        this.lastX = event.clientX;
        this.lastY = event.clientY;
        this.domElement.setPointerCapture(event.pointerId);
      }

      handlePointerMove(event) {
        if (!this.dragging) return;
        const deltaX = event.clientX - this.lastX;
        const deltaY = event.clientY - this.lastY;
        this.lastX = event.clientX;
        this.lastY = event.clientY;
        this.sphericalDelta.theta -= deltaX * this.rotateSpeed;
        this.sphericalDelta.phi -= deltaY * this.rotateSpeed;
      }

      handlePointerUp(event) {
        this.dragging = false;
        if (this.domElement.hasPointerCapture(event.pointerId)) {
          this.domElement.releasePointerCapture(event.pointerId);
        }
      }

      handleWheel(event) {
        event.preventDefault();
        this.scale *= Math.exp(event.deltaY * this.zoomSpeed);
      }

      update() {
        this.offset.copy(this.camera.position).sub(this.target);
        this.spherical.setFromVector3(this.offset);
        this.spherical.theta += this.sphericalDelta.theta;
        this.spherical.phi += this.sphericalDelta.phi;
        this.spherical.phi = Math.max(this.minPolarAngle, Math.min(this.maxPolarAngle, this.spherical.phi));
        this.spherical.radius *= this.scale;
        this.spherical.radius = Math.max(this.minDistance, Math.min(this.maxDistance, this.spherical.radius));
        this.offset.setFromSpherical(this.spherical);
        this.camera.position.copy(this.target).add(this.offset);
        this.camera.lookAt(this.target);

        if (this.enableDamping) {
          this.sphericalDelta.theta *= 1 - this.dampingFactor;
          this.sphericalDelta.phi *= 1 - this.dampingFactor;
        } else {
          this.sphericalDelta.set(0, 0, 0);
        }
        this.scale = 1;
      }
    }

    const controls = new OrbitControls(camera, renderer.domElement);
    controls.target.set(0, 44, 0);
    controls.update();

    function resize() {
      const width = Math.max(container.clientWidth, 1);
      const height = Math.max(container.clientHeight, 1);
      renderer.setSize(width, height, false);
      camera.aspect = width / height;
      camera.updateProjectionMatrix();
    }

    window.addEventListener("resize", resize);
    if (typeof ResizeObserver !== "undefined") {
      new ResizeObserver(resize).observe(container);
    }

    // WIND MODEL
    function wrapDegrees(angle) {
      return ((((angle + 180) % 360) + 360) % 360) - 180;
    }

    function randomBetween(min, max) {
      return min + Math.random() * (max - min);
    }

    function gustAngle() {
      return state.gusts ? Math.sin(state.gustPhase * 2.4) * 12 : 0;
    }

    function updateWind(dt) {
      state.windChangeTimer -= dt;
      if (state.windChangeTimer <= 0) {
        state.windTarget = wrapDegrees(state.windTarget + randomBetween(-50, 50));
        state.windChangeTimer = randomBetween(4, 10);
      }
      const difference = wrapDegrees(state.windTarget - state.trueWindDirection);
      const stepSize = 1.5 * dt;
      state.trueWindDirection = wrapDegrees(state.trueWindDirection + (Math.abs(difference) <= stepSize ? difference : Math.sign(difference) * stepSize));
      state.gustPhase += dt;
    }

    // SENSOR
    function gaussian() {
      let u = 0;
      let v = 0;
      while (u === 0) u = Math.random();
      while (v === 0) v = Math.random();
      return Math.sqrt(-2 * Math.log(u)) * Math.cos(2 * Math.PI * v);
    }

    function updateSensor() {
      const measured = wrapDegrees(state.trueWindDirection + gustAngle() - state.heading) + gaussian() * state.params.noise;
      state.sensorQueue.push({ time: state.time, value: measured });
      const cutoff = state.time - state.params.delay;
      while (state.sensorQueue.length > 0 && state.sensorQueue[0].time <= cutoff) {
        state.sensorReading = state.sensorQueue.shift().value;
      }
    }

    // CONTROLLER
    function updateController(dt) {
      const error = state.sensorReading;
      const rawDerivative = (error - state.previousError) / dt;
      const filterAlpha = 1 - Math.exp(-dt / 0.15);
      state.filteredDerivative += (rawDerivative - state.filteredDerivative) * filterAlpha;

      let command = 0;
      if (Math.abs(error) >= state.params.deadband) {
        command = state.params.kp * error + state.params.kd * state.filteredDerivative;
      }
      state.yawCommand = Math.max(-state.params.maxRate, Math.min(state.params.maxRate, command));
      state.previousError = error;
    }

    // YAW MOTOR
    function updateMotor(dt) {
      const lagAlpha = 1 - Math.exp(-dt / state.params.lag);
      state.yawRate += (state.yawCommand - state.yawRate) * lagAlpha;
      state.heading = wrapDegrees(state.heading + state.yawRate * dt);
      yawAssembly.rotation.y = -state.heading * DEG_TO_RAD;
    }

    // POWER
    function updatePower() {
      const misalignment = wrapDegrees(state.trueWindDirection - state.heading);
      state.power = Math.max(0, Math.cos(misalignment * DEG_TO_RAD) ** 2) * 100;
    }

    function step(dt) {
      state.time += dt;
      updateWind(dt);
      updateSensor();
      updateController(dt);
      updateMotor(dt);
      updatePower();
      const bladeSpeed = (0.35 + state.params.windSpeed * 0.06) * (0.3 + state.power / 100);
      state.bladeAngle += bladeSpeed * dt;
      rotor.rotation.z = state.bladeAngle;
    }

    // CONTROLS
    const sliderInputs = Array.from(document.querySelectorAll(".slider-control input[data-param]"));
    const presetButtons = Array.from(document.querySelectorAll(".preset-button"));
    const startButton = document.getElementById("start-button");
    const pauseButton = document.getElementById("pause-button");
    const resetButton = document.getElementById("reset-button");
    const gustButton = document.getElementById("gust-button");
    const toggleControls = document.getElementById("toggle-controls");
    const controlsBody = document.getElementById("controls-body");
    const panelTabs = Array.from(document.querySelectorAll('.tab-button[role="tab"]'));

    function selectPanelTab(tab) {
      panelTabs.forEach(function (button) {
        const active = button === tab;
        button.setAttribute("aria-selected", String(active));
        button.tabIndex = active ? 0 : -1;
        const panel = document.getElementById(button.getAttribute("aria-controls"));
        if (panel) panel.hidden = !active;
      });
      window.requestAnimationFrame(function () {
        charts.forEach(function (chart) {
          if (chart) chart.resize();
        });
      });
    }

    panelTabs.forEach(function (tab, index) {
      tab.addEventListener("click", function () {
        selectPanelTab(tab);
      });
      tab.addEventListener("keydown", function (event) {
        if (event.key !== "ArrowRight" && event.key !== "ArrowLeft") return;
        event.preventDefault();
        const step = event.key === "ArrowRight" ? 1 : -1;
        const next = panelTabs[(index + step + panelTabs.length) % panelTabs.length];
        selectPanelTab(next);
        next.focus();
      });
    });

    function formatValue(value) {
      return String(Number(Number(value).toFixed(2)));
    }

    function setOutput(param, value) {
      const output = document.getElementById(param + "-value");
      if (output) output.textContent = formatValue(value);
    }

    sliderInputs.forEach(function (input) {
      const param = input.dataset.param;
      setOutput(param, state.params[param]);
      input.addEventListener("input", function () {
        state.params[param] = Number(input.value);
        setOutput(param, input.value);
        presetButtons.forEach(function (button) {
          button.setAttribute("aria-pressed", "false");
        });
      });
    });

    function applyPreset(name) {
      const preset = PRESETS[name];
      if (!preset) return;
      Object.keys(preset).forEach(function (key) {
        state.params[key] = preset[key];
        const input = document.getElementById(key);
        if (input) input.value = preset[key];
        setOutput(key, preset[key]);
      });
      presetButtons.forEach(function (button) {
        button.setAttribute("aria-pressed", String(button.dataset.preset === name));
      });
    }

    presetButtons.forEach(function (button) {
      button.addEventListener("click", function () {
        applyPreset(button.dataset.preset);
      });
    });

    function setRunning(running) {
      state.running = running;
      if (!running) state.accumulator = 0;
      pauseButton.textContent = running ? "Pause" : "Resume";
    }

    startButton.addEventListener("click", function () {
      setRunning(true);
    });

    pauseButton.addEventListener("click", function () {
      setRunning(!state.running);
    });

    gustButton.addEventListener("click", function () {
      state.gusts = !state.gusts;
      gustButton.textContent = state.gusts ? "Gusts on" : "Gusts off";
      gustButton.setAttribute("aria-pressed", String(state.gusts));
    });

    resetButton.addEventListener("click", function () {
      setRunning(false);
      pauseButton.textContent = "Pause";
      state.time = 0;
      state.accumulator = 0;
      state.heading = 0;
      state.trueWindDirection = 100;
      state.windTarget = 100;
      state.windChangeTimer = randomBetween(4, 10);
      state.gusts = false;
      state.gustPhase = 0;
      state.sensorQueue.length = 0;
      state.sensorReading = 0;
      state.previousError = 0;
      state.filteredDerivative = 0;
      state.yawRate = 0;
      state.yawCommand = 0;
      state.power = 0;
      state.bladeAngle = 0;
      state.status = "IDLE";
      state.alignedTime = 0;
      state.faultTime = 0;
      state.hasAligned = false;
      history.length = 0;
      lastSampleTime = 0;
      gustButton.textContent = "Gusts off";
      gustButton.setAttribute("aria-pressed", "false");
      yawAssembly.rotation.y = 0;
      rotor.rotation.z = 0;
    });

    toggleControls.addEventListener("click", function () {
      const hiding = !controlsBody.hidden;
      controlsBody.hidden = hiding;
      toggleControls.textContent = hiding ? "Show controls" : "Hide controls";
      toggleControls.setAttribute("aria-expanded", String(!hiding));
    });

    const viewButtons = Array.from(document.querySelectorAll(".view-button"));
    const simulationScene = document.getElementById("simulation-scene");
    const sectionWindLabel = document.getElementById("section-wind-label");
    const sectionWindLayer = document.getElementById("section-wind-layer");
    const sectionNacelle = document.getElementById("section-nacelle");
    const sectionRotor = document.getElementById("section-rotor");
    const sectionShaft = document.getElementById("section-shaft");
    const sectionBottomSpokes = document.getElementById("section-bottom-spokes");
    const sectionGeneratorSpokes = document.getElementById("section-generator-spokes");
    const readoutWindSpeed = document.getElementById("readout-wind-speed");
    const readoutWindDirection = document.getElementById("readout-wind-direction");
    const readoutHeading = document.getElementById("readout-heading");
    const readoutMisalignment = document.getElementById("readout-misalignment");
    const readoutYawCommand = document.getElementById("readout-yaw-command");
    const readoutYawRate = document.getElementById("readout-yaw-rate");
    const readoutMotorState = document.getElementById("readout-motor-state");
    const readoutRotorRpm = document.getElementById("readout-rotor-rpm");
    const readoutGeneratorRpm = document.getElementById("readout-generator-rpm");
    const readoutPower = document.getElementById("readout-power");

    const sectionState = {
      rotorAngle: 0,
      generatorAngle: 0,
      shaftOffset: 0,
      windPhase: 0
    };

    const svgNamespace = "http://www.w3.org/2000/svg";
    const windArrows = [];

    for (let i = 0; i < 6; i += 1) {
      const arrow = document.createElementNS(svgNamespace, "g");
      const line = document.createElementNS(svgNamespace, "line");
      const head = document.createElementNS(svgNamespace, "polygon");
      line.setAttribute("x1", "-18");
      line.setAttribute("y1", "0");
      line.setAttribute("x2", "18");
      line.setAttribute("y2", "0");
      line.setAttribute("fill", "none");
      line.setAttribute("stroke", "var(--accent)");
      line.setAttribute("stroke-width", "2");
      head.setAttribute("points", "18,0 8,-6 8,6");
      head.setAttribute("fill", "var(--accent)");
      head.setAttribute("stroke", "var(--accent)");
      head.setAttribute("stroke-width", "2");
      arrow.setAttribute("class", "wind-arrow");
      arrow.setAttribute("fill", "var(--accent)");
      arrow.setAttribute("stroke", "var(--accent)");
      arrow.setAttribute("stroke-width", "2");
      arrow.appendChild(line);
      arrow.appendChild(head);
      sectionWindLayer.appendChild(arrow);
      windArrows.push(arrow);
    }

    const cameraPresets = {
      "3d": new THREE.Vector3(72, 52, 118),
      top: new THREE.Vector3(0, 190, 0.1),
      front: new THREE.Vector3(0, 60, 190),
      side: new THREE.Vector3(190, 60, 0)
    };

    function setView(view) {
      simulationScene.setAttribute("data-view", view);
      viewButtons.forEach(function (button) {
        const active = button.dataset.view === view;
        button.classList.toggle("is-active", active);
        button.setAttribute("aria-pressed", String(active));
      });

      const preset = cameraPresets[view];
      if (preset) {
        camera.position.copy(preset);
        controls.target.set(0, 35, 0);
        controls.update();
      }
    }

    viewButtons.forEach(function (button) {
      button.addEventListener("click", function () {
        setView(button.dataset.view);
      });
    });

    function rotorRpm() {
      const powerFraction = Math.max(0, Math.min(1, state.power / 100));
      return ROTOR_RPM_AT_REF * (state.params.windSpeed / 12) * powerFraction;
    }

    function updateSection(dt) {
      const rpm = rotorRpm();
      const generatorRpm = rpm * GEAR_RATIO;
      const rotorRadians = rpm * Math.PI / 30;

      sectionState.rotorAngle = (sectionState.rotorAngle + rotorRadians * dt) % (Math.PI * 2);
      sectionState.generatorAngle = (sectionState.generatorAngle + rotorRadians * GEAR_RATIO * dt) % (Math.PI * 2);
      sectionState.shaftOffset = (sectionState.shaftOffset + rotorRadians * 18 * dt) % 40;
      sectionState.windPhase = (sectionState.windPhase + (state.params.windSpeed / 12) * dt * 0.22) % 1;

      const rotorDegrees = (sectionState.rotorAngle * 180) / Math.PI;
      const generatorDegrees = (sectionState.generatorAngle * 180) / Math.PI;
      sectionRotor.setAttribute("transform", "translate(575 168) rotate(" + rotorDegrees.toFixed(2) + ")");
      sectionBottomSpokes.setAttribute("transform", "rotate(" + rotorDegrees.toFixed(2) + ")");
      sectionGeneratorSpokes.setAttribute("transform", "rotate(" + generatorDegrees.toFixed(2) + ")");
      sectionShaft.setAttribute("stroke-dashoffset", (-sectionState.shaftOffset).toFixed(2));
      sectionNacelle.setAttribute("transform", "rotate(" + (-state.heading).toFixed(2) + " 450 168)");

      const windDirection = wrapDegrees(state.trueWindDirection + gustAngle());
      const windAngle = (windDirection - 90) * DEG_TO_RAD;
      const fromX = Math.cos(windAngle);
      const fromY = Math.sin(windAngle);
      const travelAngle = (Math.atan2(-fromY, -fromX) * 180) / Math.PI;

      windArrows.forEach(function (arrow, index) {
        const progress = (sectionState.windPhase + index / windArrows.length) % 1;
        const distance = 280 - progress * 240;
        const offset = ((index % 3) - 1) * 22;
        const x = 575 + fromX * distance - fromY * offset;
        const y = 168 + fromY * distance + fromX * offset;
        arrow.setAttribute("transform", "translate(" + x.toFixed(1) + " " + y.toFixed(1) + ") rotate(" + travelAngle.toFixed(1) + ")");
        arrow.setAttribute("opacity", (0.35 + 0.65 * (1 - progress)).toFixed(2));
      });

      const windText = state.params.windSpeed.toFixed(1) + " m/s from " + Math.round(windDirection) + "°";
      sectionWindLabel.textContent = "Wind " + windText;
    }

    const stageElements = Array.from(document.querySelectorAll(".workflow-stage"));
    const stageValueElements = stageElements.map(function (stage) {
      return stage.querySelector(".stage-value");
    });
    const stateIndicator = document.getElementById("state-indicator");
    const stateLabel = document.getElementById("state-label");
    const misalignmentCurrent = document.getElementById("misalignment-current");
    const yawCurrent = document.getElementById("yaw-current");
    const powerCurrent = document.getElementById("power-current");

    function trueError() {
      return wrapDegrees(state.trueWindDirection - state.heading);
    }

    function updateWorkflow(frameTime) {
      const error = trueError();
      const magnitude = Math.abs(error);
      const deadbandOpen = magnitude < state.params.deadband;
      const motorOn = Math.abs(state.yawRate) > 0.05;
      const values = [
        Math.round(state.trueWindDirection) + " deg, " + state.params.windSpeed + " m/s",
        Math.round(error) + " deg",
        state.yawCommand.toFixed(2) + " deg/s, deadband " + (deadbandOpen ? "open" : "closed"),
        state.yawRate.toFixed(2) + " deg/s, motor " + (motorOn ? "ON" : "OFF"),
        Math.round(state.power) + "%"
      ];

      values.forEach(function (value, index) {
        if (stageValueElements[index]) stageValueElements[index].textContent = value;
      });

      let activeStage = -1;
      if (state.running) {
        if (magnitude < 5) activeStage = 4;
        else if (state.time < 1) activeStage = 0;
        else if (Math.abs(state.yawRate) < 0.5) activeStage = 1;
        else if (Math.abs(state.yawRate) < 2.5) activeStage = 2;
        else activeStage = 3;
      }

      stageElements.forEach(function (stage, index) {
        stage.classList.toggle("is-active", index === activeStage);
      });

      if (!state.running) {
        state.status = "IDLE";
        state.alignedTime = 0;
        state.faultTime = 0;
      } else if (magnitude > 45) {
        state.faultTime += frameTime;
        state.alignedTime = 0;
        state.status = state.hasAligned && state.faultTime > 10 ? "FAULT" : "TURNING";
      } else {
        state.faultTime = 0;
        if (magnitude < 5) {
          state.alignedTime += frameTime;
          if (state.alignedTime >= 3) {
            state.status = "ALIGNED";
            state.hasAligned = true;
          } else {
            state.status = "MONITORING";
          }
        } else {
          state.alignedTime = 0;
          state.status = "TURNING";
        }
      }

      stateIndicator.setAttribute("data-state", state.status);
      if (state.status === "FAULT") {
        stateLabel.textContent = "FAULT: error " + Math.round(magnitude) + "° for " + Math.floor(state.faultTime) + " s";
      } else {
        stateLabel.textContent = state.status;
      }
      misalignmentCurrent.textContent = Math.round(error) + " deg";
      yawCurrent.textContent = state.yawRate.toFixed(1) + " deg/s";
      powerCurrent.textContent = Math.round(state.power) + "%";
      readoutWindSpeed.textContent = state.params.windSpeed.toFixed(1);
      readoutWindDirection.textContent = String(Math.round(state.trueWindDirection));
      readoutHeading.textContent = String(Math.round(state.heading));
      readoutMisalignment.textContent = String(Math.round(error));
      readoutYawCommand.textContent = state.yawCommand.toFixed(2);
      readoutYawRate.textContent = state.yawRate.toFixed(1);
      readoutMotorState.textContent = motorOn ? "ON" : "OFF";
      readoutRotorRpm.textContent = rotorRpm().toFixed(1);
      readoutGeneratorRpm.textContent = (rotorRpm() * GEAR_RATIO).toFixed(0);
      readoutPower.textContent = String(Math.round(state.power));
    }

    const tourButton = document.getElementById("tour-button");
    const tourNext = document.getElementById("tour-next");
    const tourStatus = document.getElementById("tour-status");
    const tourVoice = document.getElementById("tour-voice");
    const tourViews = ["top", "top", "section", "section", "3d"];
    let tourIndex = -1;
    let tourTimer = null;

    function stopSpeech() {
      if ("speechSynthesis" in window) window.speechSynthesis.cancel();
    }

    function speak(text) {
      if (!tourVoice.checked) return;
      if (!("speechSynthesis" in window) || typeof SpeechSynthesisUtterance !== "function") return;
      stopSpeech();
      const utterance = new SpeechSynthesisUtterance(text);
      window.speechSynthesis.speak(utterance);
    }

    function clearTour() {
      if (tourTimer !== null) {
        window.clearTimeout(tourTimer);
        tourTimer = null;
      }
      stageElements.forEach(function (stage) {
        stage.classList.remove("is-tour-active");
      });
      stopSpeech();
    }

    function endTour() {
      clearTour();
      tourIndex = -1;
      tourButton.textContent = "Guided tour";
      tourButton.setAttribute("aria-pressed", "false");
      tourNext.hidden = true;
      tourStatus.hidden = true;
      tourStatus.textContent = "";
    }

    function showTourStage(index) {
      clearTour();
      const stage = stageElements[index];
      if (!stage) {
        endTour();
        return;
      }
      tourIndex = index;
      stage.classList.add("is-tour-active");
      setView(tourViews[index]);
      const sentence = stage.querySelector("p").textContent;
      tourStatus.textContent = "Stage " + (index + 1) + " of 5. " + sentence;
      tourStatus.hidden = false;
      tourNext.hidden = false;
      tourButton.textContent = "Stop tour";
      tourButton.setAttribute("aria-pressed", "true");
      speak(sentence);
      tourTimer = window.setTimeout(function () {
        if (tourIndex < stageElements.length - 1) showTourStage(tourIndex + 1);
        else endTour();
      }, 4000);
    }

    tourButton.addEventListener("click", function () {
      if (tourIndex === -1) showTourStage(0);
      else endTour();
    });

    tourNext.addEventListener("click", function () {
      if (tourIndex === -1) return;
      if (tourIndex < stageElements.length - 1) showTourStage(tourIndex + 1);
      else endTour();
    });

    tourVoice.addEventListener("change", function () {
      if (!tourVoice.checked) stopSpeech();
    });

    const history = [];
    let lastSampleTime = 0;
    let lastChartUpdate = 0;
    const charts = [];

    const bandPlugin = {
      id: "targetBand",
      beforeDatasetsDraw: function (chart) {
        const y = chart.scales.y;
        const area = chart.chartArea;
        const ctx = chart.ctx;
        const top = y.getPixelForValue(5);
        const bottom = y.getPixelForValue(-5);
        ctx.save();
        ctx.fillStyle = "rgba(34, 211, 238, 0.12)";
        ctx.fillRect(area.left, top, area.right - area.left, bottom - top);
        ctx.restore();
      }
    };

    const zeroLinePlugin = {
      id: "zeroLine",
      beforeDatasetsDraw: function (chart) {
        const y = chart.scales.y;
        const area = chart.chartArea;
        const ctx = chart.ctx;
        const zero = y.getPixelForValue(0);
        ctx.save();
        ctx.strokeStyle = "rgba(226, 232, 240, 0.6)";
        ctx.lineWidth = 1.5;
        ctx.beginPath();
        ctx.moveTo(area.left, zero);
        ctx.lineTo(area.right, zero);
        ctx.stroke();
        ctx.restore();
      }
    };

    if (typeof Chart !== "undefined") {
      Chart.defaults.color = "#94a3b8";
      Chart.defaults.font.family = "system-ui, sans-serif";
      Chart.defaults.font.size = 14;

      function buildChart(canvasId, yMin, yMax, color, plugins) {
        const canvas = document.getElementById(canvasId);
        if (!canvas) return null;
        return new Chart(canvas.getContext("2d"), {
          type: "line",
          data: {
            datasets: [{
              data: [],
              borderColor: color,
              borderWidth: 2,
              pointRadius: 0,
              tension: 0
            }]
          },
          options: {
            responsive: true,
            maintainAspectRatio: false,
            animation: false,
            parsing: false,
            plugins: {
              legend: { display: false },
              tooltip: { enabled: false }
            },
            scales: {
              x: {
                type: "linear",
                title: { display: true, text: "time (s)", color: "#94a3b8", font: { size: 14 } },
                ticks: { color: "#94a3b8", font: { size: 14 } },
                grid: { color: "#1f2d46" }
              },
              y: {
                min: yMin,
                max: yMax,
                ticks: { color: "#94a3b8", font: { size: 14 } },
                grid: { color: "#1f2d46" }
              }
            }
          },
          plugins: plugins || []
        });
      }

      charts.push(buildChart("misalignment-chart", -90, 90, "#22d3ee", [bandPlugin]));
      charts.push(buildChart("yaw-chart", -10, 10, "#f59e0b", [zeroLinePlugin]));
      charts.push(buildChart("power-chart", 0, 100, "#22c55e", []));
    }

    function sampleHistory() {
      if (!state.running || state.time - lastSampleTime < 0.2) return;
      lastSampleTime = state.time;
      history.push({ t: state.time, e: trueError(), r: state.yawRate, p: state.power });
      while (history.length > 0 && history[0].t < state.time - 60) history.shift();
    }

    function updateCharts() {
      const now = performance.now();
      if (now - lastChartUpdate < 100) return;
      lastChartUpdate = now;

      const windowEnd = Math.max(60, state.time);
      const windowStart = windowEnd - 60;
      const series = [
        history.map(function (point) { return { x: point.t, y: point.e }; }),
        history.map(function (point) { return { x: point.t, y: point.r }; }),
        history.map(function (point) { return { x: point.t, y: point.p }; })
      ];

      charts.forEach(function (chart, index) {
        if (!chart) return;
        chart.data.datasets[0].data = series[index];
        chart.options.scales.x.min = windowStart;
        chart.options.scales.x.max = windowEnd;
        chart.update("none");
      });
    }

    // RENDER LOOP
    resize();

    let lastFrameTime = performance.now();

    function animate(now) {
      requestAnimationFrame(animate);
      const frameTime = Math.min((now - lastFrameTime) / 1000, 0.25);
      lastFrameTime = now;

      if (state.running) {
        state.accumulator += frameTime;
        while (state.accumulator >= FIXED_STEP) {
          step(FIXED_STEP);
          state.accumulator -= FIXED_STEP;
        }
      }

      sampleHistory();
      updateSection(frameTime);
      updateWorkflow(frameTime);
      updateCharts();
      controls.update();
      renderer.render(scene, camera);
    }

    requestAnimationFrame(animate);
  }
})();
