/* Chart helpers. All data comes from /api/stats/* (live database queries). */
(function () {
  "use strict";
  const PALETTE = ["#39338a", "#f2a516", "#0f9d8a", "#e5564b", "#7c74d9", "#5bb8e8", "#b88a2e", "#9aa0b4"];
  const STATUS_COLORS = { submitted: "#9aa0b4", shortlisted: "#5bb8e8", selected: "#39338a", rejected: "#e5564b",
    allocated: "#0f9d8a", withdrawn: "#3d3a4f" };
  if (window.Chart) {
    Chart.defaults.font.family = getComputedStyle(document.body).fontFamily;
    Chart.defaults.color = "#6b6880";
    Chart.defaults.plugins.legend.labels.boxWidth = 12;
    Chart.defaults.maintainAspectRatio = false;
  }

  function empty(canvas, msg) {
    const box = canvas.parentElement;
    box.innerHTML = '<div class="empty-state py-5"><i class="bi bi-bar-chart"></i><div class="mt-2 small">' +
      (msg || "No data yet") + "</div></div>";
  }

  function sum(arr) { return (arr || []).reduce((a, b) => a + b, 0); }

  window.Charts = {
    doughnutStatus(id, counts) {
      const c = document.getElementById(id); if (!c) return;
      const labels = Object.keys(counts).filter((k) => counts[k] > 0);
      if (!labels.length) return empty(c, "No applications yet");
      new Chart(c, { type: "doughnut", data: { labels: labels.map((l) => l[0].toUpperCase() + l.slice(1)),
        datasets: [{ data: labels.map((l) => counts[l]), backgroundColor: labels.map((l) => STATUS_COLORS[l] || "#ccc"), borderWidth: 0 }] },
        options: { cutout: "62%", plugins: { legend: { position: "bottom" } } } });
    },
    bar(id, labels, datasets, opts = {}) {
      const c = document.getElementById(id); if (!c) return;
      if (!labels.length || !datasets.some((d) => sum(d.data) > 0)) return empty(c, opts.emptyText);
      new Chart(c, { type: "bar", data: { labels, datasets: datasets.map((d, i) => Object.assign(
        { backgroundColor: PALETTE[i % PALETTE.length], borderRadius: 6, maxBarThickness: 34 }, d)) },
        options: { indexAxis: opts.horizontal ? "y" : "x", plugins: { legend: { display: datasets.length > 1, position: "bottom" } },
          scales: { x: { grid: { display: false }, ticks: { precision: 0 } }, y: { beginAtZero: true, ticks: { precision: 0 }, grid: { color: "#eee" } } } } });
    },
    line(id, labels, values, label) {
      const c = document.getElementById(id); if (!c) return;
      if (!sum(values)) return empty(c, "No activity in this period");
      new Chart(c, { type: "line", data: { labels: labels.map((l) => l.slice(5)), datasets: [{ label, data: values,
        borderColor: "#39338a", backgroundColor: "rgba(57,51,138,.12)", fill: true, tension: .35, pointRadius: 2 }] },
        options: { plugins: { legend: { display: false } }, scales: { y: { beginAtZero: true, ticks: { precision: 0 } }, x: { grid: { display: false } } } } });
    },
  };

  window.loadAdminCharts = async function () {
    try {
      const d = await api("/api/stats/admin");
      Charts.bar("chartDomain", d.internships_by_domain.labels, [
        { label: "Internships", data: d.internships_by_domain.values },
        { label: "Seats", data: d.internships_by_domain.seats }], { emptyText: "No published internships" });
      Charts.doughnutStatus("chartStatus", d.application_status);
      Charts.bar("chartAlloc", d.allocation_by_internship.labels, [
        { label: "Seats", data: d.allocation_by_internship.seats },
        { label: "Allocated", data: d.allocation_by_internship.allocated },
        { label: "Applications", data: d.allocation_by_internship.applications }], { horizontal: true, emptyText: "No internships yet" });
      Charts.bar("chartSkills", d.skill_demand.labels, [
        { label: "Internships requiring", data: d.skill_demand.demand },
        { label: "Students having", data: d.skill_demand.supply }], { emptyText: "No skill data yet" });
      Charts.bar("chartScores", d.score_distribution.labels, [{ label: "Applications", data: d.score_distribution.values }],
        { emptyText: "No scored applications" });
      Charts.line("chartTimeline", d.applications_timeline.labels, d.applications_timeline.values, "Applications");
    } catch (e) { console.error(e); }
  };

  window.loadCompanyCharts = async function () {
    try {
      const d = await api("/api/stats/company");
      Charts.bar("chartApps", d.applications_by_internship.labels, [
        { label: "Applications", data: d.applications_by_internship.values },
        { label: "Seats", data: d.applications_by_internship.seats },
        { label: "Allocated", data: d.applications_by_internship.allocated }], { emptyText: "No internships yet" });
      Charts.doughnutStatus("chartStatus", d.application_status);
      Charts.bar("chartScores", d.score_distribution.labels, [{ label: "Applicants", data: d.score_distribution.values }],
        { emptyText: "No applicants yet" });
    } catch (e) { console.error(e); }
  };

  window.loadStudentCharts = async function () {
    try {
      const d = await api("/api/stats/student");
      Charts.doughnutStatus("chartStatus", d.application_status);
      Charts.bar("chartGaps", d.skill_gaps.labels, [{ label: "Internships asking for it", data: d.skill_gaps.values }],
        { horizontal: true, emptyText: "No skill gaps found — great!" });
    } catch (e) { console.error(e); }
  };
})();
