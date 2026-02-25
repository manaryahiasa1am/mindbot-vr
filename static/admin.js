(() => {
  const elToken = document.getElementById("adminToken");
  const btnLoad = document.getElementById("btnLoadStats");
  const btnExport = document.getElementById("btnExport");
  const toast = document.getElementById("adminToast");
  const statUsers = document.getElementById("statUsers");
  const statEmergencies = document.getElementById("statEmergencies");
  const statAvg = document.getElementById("statAvg");

  function setToast(text) {
    if (!text) {
      toast.classList.add("hidden");
      toast.textContent = "";
      return;
    }
    toast.textContent = text;
    toast.classList.remove("hidden");
  }

  async function api(path) {
    const token = (elToken.value || "").trim();
    const res = await fetch(path, { headers: { "X-Admin-Token": token } });
    if (!res.ok) throw new Error(await res.text());
    return res;
  }

  btnLoad.addEventListener("click", async () => {
    setToast("");
    try {
      const res = await api("/api/admin/stats");
      const data = await res.json();
      statUsers.textContent = String(data.total_users);
      statEmergencies.textContent = String(data.emergencies);
      statAvg.textContent = String(data.average_risk_score);
    } catch (e) {
      setToast(`Admin error: ${e.message}`);
    }
  });

  btnExport.addEventListener("click", async () => {
    setToast("");
    try {
      const token = (elToken.value || "").trim();
      const res = await fetch("/api/admin/export", { headers: { "X-Admin-Token": token } });
      if (!res.ok) throw new Error(await res.text());
      const blob = await res.blob();
      const url = URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = url;
      a.download = "mindbot_vr_export.csv";
      document.body.appendChild(a);
      a.click();
      a.remove();
      URL.revokeObjectURL(url);
    } catch (e) {
      setToast(`Export error: ${e.message}`);
    }
  });
})();

