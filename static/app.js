(() => {
  const appEl = document.getElementById("app");
  const htmlEl = document.documentElement;
  const sessionKey = "mindbot_vr_session_id";
  const themeKey = "mindbot_vr_theme";
  let sessionId = localStorage.getItem(sessionKey) || "";

  const els = {
    pulse: document.getElementById("pulseValue"),
    temp: document.getElementById("tempValue"),
    oxygen: document.getElementById("oxygenValue"),
    air: document.getElementById("airValue"),
    pulseAlert: document.getElementById("pulseAlert"),
    tempAlert: document.getElementById("tempAlert"),
    chatMessages: document.getElementById("chatMessages"),
    chatForm: document.getElementById("chatForm"),
    chatInput: document.getElementById("chatInput"),
    btnSend: document.getElementById("btnSend"),
    btnSOS: document.getElementById("btnSOS"),
    btnReport: document.getElementById("btnReport"),
    btnTheme: document.getElementById("btnTheme"),
    toast: document.getElementById("toast"),
    hospitalList: document.getElementById("hospitalList"),
    map: document.getElementById("map"),
    mapFallback: document.getElementById("mapFallback"),
    sosResult: document.getElementById("sosResult"),
    aiLoading: document.getElementById("aiLoading"),
    riskPill: document.getElementById("riskPill"),
    riskIndicator: document.getElementById("riskIndicator"),
    riskText: document.getElementById("riskText"),
    riskMeta: document.getElementById("riskMeta"),
  };

  const center = {
    lat: Number(appEl.dataset.centerLat || "29.0661"),
    lng: Number(appEl.dataset.centerLng || "31.0994"),
  };
  const mapsKey = (appEl.dataset.mapsKey || "").trim();

  let lastRiskLevel = "";
  let lastKnownLocation = { lat: center.lat, lng: center.lng };

  const pulseSeries = [];
  const pulseLabels = [];
  let chart = null;
  let map = null;
  let userMarker = null;
  let hospitalMarkers = [];

  function setTheme(next) {
    const theme = next === "light" ? "light" : "dark";
    htmlEl.dataset.theme = theme;
    localStorage.setItem(themeKey, theme);
  }

  function toggleTheme() {
    setTheme(htmlEl.dataset.theme === "light" ? "dark" : "light");
  }

  function setToast(text) {
    if (!text) {
      els.toast.classList.add("hidden");
      els.toast.textContent = "";
      return;
    }
    els.toast.textContent = text;
    els.toast.classList.remove("hidden");
  }

  function addMessage(role, text) {
    const div = document.createElement("div");
    div.className = `msg ${role === "user" ? "user" : "bot"}`;
    div.textContent = text;
    els.chatMessages.appendChild(div);
    els.chatMessages.scrollTop = els.chatMessages.scrollHeight;
    return div;
  }

  function addTypingIndicator() {
    const div = document.createElement("div");
    div.className = "msg bot typing";
    const dots = document.createElement("span");
    dots.className = "dots";
    for (let i = 0; i < 3; i++) {
      const d = document.createElement("span");
      d.className = "dot";
      dots.appendChild(d);
    }
    const label = document.createElement("span");
    label.textContent = "MindBot VR is typing";
    div.appendChild(dots);
    div.appendChild(label);
    els.chatMessages.appendChild(div);
    els.chatMessages.scrollTop = els.chatMessages.scrollHeight;
    return div;
  }

  function typewriterInto(el, text, cps = 55) {
    const src = String(text || "");
    el.textContent = "";
    let i = 0;
    const interval = Math.max(10, Math.floor(1000 / cps));
    return new Promise((resolve) => {
      const t = setInterval(() => {
        i += 1;
        el.textContent = src.slice(0, i);
        els.chatMessages.scrollTop = els.chatMessages.scrollHeight;
        if (i >= src.length) {
          clearInterval(t);
          resolve();
        }
      }, interval);
    });
  }

  function animateNumber(el, nextValue, decimals = 0) {
    const current = Number(el.dataset.value || "0");
    const target = Number(nextValue);
    const start = performance.now();
    const duration = 420;
    el.dataset.value = String(target);

    function frame(now) {
      const t = Math.min(1, (now - start) / duration);
      const eased = 1 - Math.pow(1 - t, 3);
      const v = current + (target - current) * eased;
      el.textContent = v.toFixed(decimals);
      if (t < 1) requestAnimationFrame(frame);
    }
    requestAnimationFrame(frame);
  }

  function applyAlerts(vitals) {
    if (vitals.pulse_bpm > 110) {
      els.pulseAlert.textContent = "High";
      els.pulseAlert.className = "pill pill-warn";
    } else {
      els.pulseAlert.textContent = "Normal";
      els.pulseAlert.className = "pill pill-ok";
    }

    if (vitals.temperature_c > 38) {
      els.tempAlert.textContent = "Fever";
      els.tempAlert.className = "pill pill-danger";
    } else {
      els.tempAlert.textContent = "Normal";
      els.tempAlert.className = "pill pill-ok";
    }
  }

  function setRiskUI(risk) {
    const level = String((risk || {}).risk_level || "");
    const score = Number((risk || {}).risk_score || 0);

    els.riskText.textContent = level ? `Risk: ${level}` : "Risk: --";
    els.riskMeta.textContent = `Score: ${Number.isFinite(score) ? score : "--"}`;

    appEl.classList.remove("risk-low", "risk-medium", "risk-critical", "critical");
    if (level === "Critical") {
      appEl.classList.add("risk-critical", "critical");
      els.riskIndicator.style.background = "rgba(255,61,113,.9)";
      els.riskPill.style.borderColor = "rgba(255,61,113,.35)";
      els.riskPill.style.color = "rgba(255,61,113,.95)";
    } else if (level === "Medium") {
      appEl.classList.add("risk-medium");
      els.riskIndicator.style.background = "rgba(255,183,3,.9)";
      els.riskPill.style.borderColor = "rgba(255,183,3,.35)";
      els.riskPill.style.color = "rgba(255,183,3,.95)";
    } else if (level === "Low") {
      appEl.classList.add("risk-low");
      els.riskIndicator.style.background = "rgba(46,229,157,.9)";
      els.riskPill.style.borderColor = "rgba(46,229,157,.35)";
      els.riskPill.style.color = "rgba(46,229,157,.95)";
    } else {
      els.riskIndicator.style.background = "rgba(169,183,223,.7)";
      els.riskPill.style.borderColor = "rgba(255,255,255,.14)";
      els.riskPill.style.color = "";
    }

    if (level && level !== lastRiskLevel) {
      if (level === "Critical") playIcuAlert("critical");
      if (level === "Medium") playIcuAlert("medium");
      lastRiskLevel = level;
    }
  }

  let audioCtx = null;
  let lastBeepAt = 0;
  function playIcuAlert(kind) {
    const now = Date.now();
    if (now - lastBeepAt < 1200) return;
    lastBeepAt = now;

    try {
      audioCtx = audioCtx || new (window.AudioContext || window.webkitAudioContext)();
      const ctx = audioCtx;
      const o = ctx.createOscillator();
      const g = ctx.createGain();
      o.type = "sine";
      o.frequency.value = kind === "critical" ? 880 : 660;
      g.gain.value = 0.0001;
      o.connect(g);
      g.connect(ctx.destination);
      o.start();
      const t0 = ctx.currentTime;
      g.gain.exponentialRampToValueAtTime(0.14, t0 + 0.02);
      g.gain.exponentialRampToValueAtTime(0.0001, t0 + (kind === "critical" ? 0.28 : 0.18));
      o.stop(t0 + (kind === "critical" ? 0.30 : 0.20));
    } catch (_) {
      return;
    }
  }

  async function apiJson(path, options = {}) {
    const res = await fetch(path, {
      headers: { "Content-Type": "application/json" },
      ...options,
    });
    if (!res.ok) {
      const text = await res.text();
      throw new Error(text || `HTTP ${res.status}`);
    }
    return res.json();
  }

  async function loadHospitals() {
    const data = await apiJson("/api/hospitals");
    els.hospitalList.replaceChildren();
    for (const h of data.hospitals) {
      const item = document.createElement("div");
      item.className = "hospital-item";

      const left = document.createElement("div");
      const name = document.createElement("div");
      name.className = "hospital-name";
      name.textContent = h.name;
      const meta = document.createElement("div");
      meta.className = "hospital-meta";
      meta.textContent = `${h.address} • ${h.phone}`;
      left.appendChild(name);
      left.appendChild(meta);

      const actions = document.createElement("div");
      actions.className = "hospital-actions";
      const tel = document.createElement("a");
      tel.className = "tel";
      tel.href = `tel:${String(h.phone).replace(/\s+/g, "")}`;
      tel.textContent = "Call";
      actions.appendChild(tel);

      item.appendChild(left);
      item.appendChild(actions);
      els.hospitalList.appendChild(item);
    }
    if (mapsKey && map) renderHospitalMarkers(data.hospitals);
  }

  function initChart() {
    const ctx = document.getElementById("pulseChart");
    chart = new Chart(ctx, {
      type: "line",
      data: {
        labels: pulseLabels,
        datasets: [
          {
            label: "Pulse BPM",
            data: pulseSeries,
            borderColor: "rgba(67,229,255,.95)",
            backgroundColor: "rgba(67,229,255,.16)",
            fill: true,
            tension: 0.32,
            pointRadius: 0,
          },
        ],
      },
      options: {
        responsive: true,
        maintainAspectRatio: false,
        animation: false,
        plugins: { legend: { display: false } },
        scales: {
          x: { display: false },
          y: { ticks: { color: "rgba(169,183,223,.80)" }, grid: { color: "rgba(255,255,255,.06)" } },
        },
      },
    });
  }

  function pushPulse(pulse) {
    const t = new Date();
    const label = `${String(t.getHours()).padStart(2, "0")}:${String(t.getMinutes()).padStart(2, "0")}:${String(
      t.getSeconds()
    ).padStart(2, "0")}`;
    pulseLabels.push(label);
    pulseSeries.push(pulse);
    const maxPoints = 60;
    while (pulseSeries.length > maxPoints) {
      pulseSeries.shift();
      pulseLabels.shift();
    }
    if (chart) chart.update("none");
  }

  async function refreshVitals() {
    const qs = sessionId ? `?session_id=${encodeURIComponent(sessionId)}` : "";
    const data = await apiJson(`/api/vitals${qs}`);
    sessionId = data.session_id;
    localStorage.setItem(sessionKey, sessionId);

    const v = data.vitals;
    animateNumber(els.pulse, v.pulse_bpm, 1);
    animateNumber(els.temp, v.temperature_c, 1);
    animateNumber(els.oxygen, v.oxygen_percent, 1);
    animateNumber(els.air, v.air_quality_ppm, 0);
    applyAlerts(v);
    pushPulse(v.pulse_bpm);
    setRiskUI(data.risk || {});
  }

  function loadGoogleMapsScript(key) {
    return new Promise((resolve, reject) => {
      if (window.google && window.google.maps) {
        resolve();
        return;
      }
      const s = document.createElement("script");
      s.src = `https://maps.googleapis.com/maps/api/js?key=${encodeURIComponent(key)}`;
      s.async = true;
      s.defer = true;
      s.onload = () => resolve();
      s.onerror = () => reject(new Error("Google Maps failed to load"));
      document.head.appendChild(s);
    });
  }

  function initMap() {
    if (!mapsKey) {
      els.map.classList.add("hidden");
      els.mapFallback.classList.remove("hidden");
      const iframe = document.createElement("iframe");
      iframe.width = "100%";
      iframe.height = "100%";
      iframe.style.border = "0";
      iframe.loading = "lazy";
      iframe.referrerPolicy = "no-referrer-when-downgrade";
      iframe.src = `https://www.google.com/maps?q=${center.lat},${center.lng}&z=13&output=embed`;
      els.mapFallback.appendChild(iframe);
      return;
    }

    loadGoogleMapsScript(mapsKey)
      .then(() => {
        map = new google.maps.Map(els.map, {
          center,
          zoom: 13,
          disableDefaultUI: false,
        });
        new google.maps.Marker({ position: center, map, title: "Beni Suef Center" });
      })
      .catch((e) => {
        setToast(e.message);
        els.map.classList.add("hidden");
        els.mapFallback.classList.remove("hidden");
      });
  }

  function renderHospitalMarkers(hospitals) {
    for (const m of hospitalMarkers) m.setMap(null);
    hospitalMarkers = [];
    for (const h of hospitals) {
      const marker = new google.maps.Marker({
        position: { lat: h.lat, lng: h.lng },
        map,
        title: h.name,
      });
      hospitalMarkers.push(marker);
    }
  }

  async function getGeo() {
    function fallback() {
      return Promise.resolve({ coords: { latitude: center.lat, longitude: center.lng } });
    }
    return new Promise((resolve) => {
      if (!navigator.geolocation) {
        fallback().then(resolve);
        return;
      }
      navigator.geolocation.getCurrentPosition(resolve, () => fallback().then(resolve), {
        enableHighAccuracy: true,
        timeout: 6000,
        maximumAge: 5000,
      });
    });
  }

  async function sendChat(text) {
    const trimmed = String(text || "").trim();
    if (!trimmed) return;

    addMessage("user", trimmed);
    els.chatInput.value = "";
    setToast("");

    els.btnSend.disabled = true;
    els.chatInput.disabled = true;
    els.aiLoading.classList.remove("hidden");

    const typing = addTypingIndicator();

    try {
      const data = await apiJson("/api/ask_ai", {
        method: "POST",
        body: JSON.stringify({ message: trimmed, session_id: sessionId, lat: lastKnownLocation.lat, lng: lastKnownLocation.lng }),
      });
      sessionId = data.session_id;
      localStorage.setItem(sessionKey, sessionId);

      typing.remove();
      const msgEl = addMessage("assistant", "");
      await typewriterInto(msgEl, data.reply, 70);

      if (data.vitals) {
        const v = data.vitals;
        animateNumber(els.pulse, v.pulse_bpm, 1);
        animateNumber(els.temp, v.temperature_c, 1);
        animateNumber(els.oxygen, v.oxygen_percent, 1);
        animateNumber(els.air, v.air_quality_ppm, 0);
        applyAlerts(v);
        pushPulse(v.pulse_bpm);
      }
      if (data.risk) setRiskUI(data.risk);

      if (data.auto_emergency && data.auto_emergency.enabled && data.auto_emergency.nearest_hospital) {
        const h = data.auto_emergency.nearest_hospital;
        els.sosResult.textContent = `AUTO EMERGENCY: ${h.name} • ${h.distance_km} km • ETA ${h.eta_minutes} min • ${h.phone}`;
        playIcuAlert("critical");
      }
    } catch (e) {
      typing.remove();
      setToast(`Assistant error: ${e.message}`);
    } finally {
      els.btnSend.disabled = false;
      els.chatInput.disabled = false;
      els.aiLoading.classList.add("hidden");
      els.chatInput.focus();
    }
  }

  async function sos() {
    setToast("Activating SOS…");
    const position = await getGeo();
    const lat = position.coords.latitude;
    const lng = position.coords.longitude;
    lastKnownLocation = { lat, lng };

    try {
      const data = await apiJson("/api/sos", {
        method: "POST",
        body: JSON.stringify({ lat, lng, session_id: sessionId }),
      });
      sessionId = data.session_id;
      localStorage.setItem(sessionKey, sessionId);

      const h = data.nearest_hospital;
      els.sosResult.textContent = `SOS: ${h.name} • ${h.distance_km} km • ETA ${h.eta_minutes} min • ${h.phone}`;
      setToast(`Nearest hospital: ${h.name} • ETA ${h.eta_minutes} min`);
      playIcuAlert("critical");

      if (mapsKey && map && window.google && window.google.maps) {
        if (userMarker) userMarker.setMap(null);
        userMarker = new google.maps.Marker({
          position: { lat, lng },
          map,
          title: "Your location",
          icon: {
            path: google.maps.SymbolPath.CIRCLE,
            scale: 7,
            fillColor: "#43e5ff",
            fillOpacity: 0.9,
            strokeColor: "#ffffff",
            strokeWeight: 2,
          },
        });
        map.panTo({ lat, lng });
      }
    } catch (e) {
      setToast(`SOS failed: ${e.message}`);
    }
  }

  function openReport() {
    const qs = sessionId ? `?session_id=${encodeURIComponent(sessionId)}` : "";
    window.open(`/api/report${qs}`, "_blank", "noopener");
  }

  async function boot() {
    setTheme(localStorage.getItem(themeKey) || "dark");
    els.btnTheme.addEventListener("click", toggleTheme);

    initChart();
    initMap();
    await loadHospitals();

    addMessage(
      "assistant",
      "Welcome to MindBot VR. Describe symptoms (example: fever + cough + fatigue). I will compute a risk score and guidance."
    );

    const position = await getGeo();
    lastKnownLocation = { lat: position.coords.latitude, lng: position.coords.longitude };

    await refreshVitals();
    setInterval(() => refreshVitals().catch(() => {}), 1000);

    els.chatForm.addEventListener("submit", (ev) => {
      ev.preventDefault();
      sendChat(els.chatInput.value);
    });
    els.btnSOS.addEventListener("click", () => sos());
    els.btnReport.addEventListener("click", () => openReport());
  }

  boot().catch((e) => setToast(`Boot error: ${e.message}`));
})();

