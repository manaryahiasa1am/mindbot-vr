(() => {
  const appEl = document.getElementById("app");
  const sessionKey = "mindbot_vr_session_id";
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
    btnSOS: document.getElementById("btnSOS"),
    btnReport: document.getElementById("btnReport"),
    toast: document.getElementById("toast"),
    hospitalList: document.getElementById("hospitalList"),
    map: document.getElementById("map"),
    mapFallback: document.getElementById("mapFallback"),
  };

  const center = {
    lat: Number(appEl.dataset.centerLat || "29.0661"),
    lng: Number(appEl.dataset.centerLng || "31.0994"),
  };

  const mapsKey = (appEl.dataset.mapsKey || "").trim();

  const pulseSeries = [];
  const pulseLabels = [];

  let chart = null;
  let map = null;
  let hospitalMarkers = [];
  let userMarker = null;

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
      els.pulseAlert.textContent = "Warning";
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

    if (mapsKey && map) {
      renderHospitalMarkers(data.hospitals);
    }
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
            backgroundColor: "rgba(67,229,255,.18)",
            fill: true,
            tension: 0.35,
            pointRadius: 2,
            pointHoverRadius: 3,
          },
        ],
      },
      options: {
        responsive: true,
        maintainAspectRatio: false,
        plugins: {
          legend: { display: false },
          tooltip: { enabled: true },
        },
        scales: {
          x: { ticks: { color: "rgba(169,183,223,.80)" }, grid: { color: "rgba(255,255,255,.06)" } },
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
    const maxPoints = 30;
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
          mapId: "DEMO_MAP_ID",
          disableDefaultUI: false,
        });

        new google.maps.Marker({
          position: center,
          map,
          title: "Beni Suef Center",
        });
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

  async function sendChat(text) {
    const trimmed = String(text || "").trim();
    if (!trimmed) return;

    addMessage("user", trimmed);
    els.chatInput.value = "";
    setToast("");

    try {
      const data = await apiJson("/api/ask_ai", {
        method: "POST",
        body: JSON.stringify({ message: trimmed, session_id: sessionId }),
      });
      sessionId = data.session_id;
      localStorage.setItem(sessionKey, sessionId);
      addMessage("assistant", data.reply);
      if (data.vitals) {
        const v = data.vitals;
        animateNumber(els.pulse, v.pulse_bpm, 1);
        animateNumber(els.temp, v.temperature_c, 1);
        animateNumber(els.oxygen, v.oxygen_percent, 1);
        animateNumber(els.air, v.air_quality_ppm, 0);
        applyAlerts(v);
        pushPulse(v.pulse_bpm);
      }
    } catch (e) {
      setToast(`Assistant error: ${e.message}`);
    }
  }

  async function sos() {
    setToast("Locating you for SOS…");

    function fallbackLocation() {
      return Promise.resolve({ coords: { latitude: center.lat, longitude: center.lng } });
    }

    const position = await new Promise((resolve) => {
      if (!navigator.geolocation) {
        fallbackLocation().then(resolve);
        return;
      }
      navigator.geolocation.getCurrentPosition(resolve, () => fallbackLocation().then(resolve), {
        enableHighAccuracy: true,
        timeout: 6000,
        maximumAge: 5000,
      });
    });

    const lat = position.coords.latitude;
    const lng = position.coords.longitude;
    try {
      const data = await apiJson("/api/sos", {
        method: "POST",
        body: JSON.stringify({ lat, lng }),
      });
      const h = data.nearest_hospital;
      setToast(`Nearest hospital: ${h.name} • ${h.distance_km} km • ${h.phone}`);

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

  function boot() {
    initChart();
    initMap();
    loadHospitals().catch((e) => setToast(`Hospitals load error: ${e.message}`));

    addMessage(
      "assistant",
      "Hi — I’m MindBot VR. Describe your symptoms (for example: headache + fever), and I will provide initial guidance."
    );

    refreshVitals().catch((e) => setToast(`Vitals error: ${e.message}`));
    setInterval(() => refreshVitals().catch(() => {}), 2000);

    els.chatForm.addEventListener("submit", (ev) => {
      ev.preventDefault();
      sendChat(els.chatInput.value);
    });
    els.btnSOS.addEventListener("click", () => sos());
    els.btnReport.addEventListener("click", () => openReport());
  }

  boot();
})();

