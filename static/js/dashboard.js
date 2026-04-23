document.addEventListener("DOMContentLoaded", function () {
  fetchDashboardStats();

  // Set current date
  const now = new Date();
  document.getElementById("current-date").textContent = now.toLocaleDateString(
    "en-PK",
    {
      day: "numeric",
      month: "short",
      year: "numeric",
    }
  );
});

async function fetchDashboardStats() {
  try {
    const response = await fetch("/api/dashboard_stats");
    const data = await response.json();

    updateStats(data);
    renderWeeklyChart(data.weekly_data);
    renderClassChart(data.class_distribution);
    renderRecentLogs(data.recent_logs);
  } catch (error) {
    console.error("Error fetching dashboard stats:", error);
  }
}

function updateStats(data) {
  document.getElementById("total-students").textContent = data.total_users;
  document.getElementById("today-attendance").textContent = data.today_count;
}

function renderWeeklyChart(weeklyData) {
  const ctx = document.getElementById("weeklyChart").getContext("2d");

  const labels = weeklyData.map((d) => {
    const date = new Date(d.date);
    return date.toLocaleDateString("en-PK", { weekday: "short" });
  });
  const counts = weeklyData.map((d) => d.count);

  new Chart(ctx, {
    type: "line",
    data: {
      labels: labels,
      datasets: [
        {
          label: "Students Present",
          data: counts,
          borderColor: "#FFD700",
          backgroundColor: "rgba(255, 215, 0, 0.1)",
          borderWidth: 3,
          fill: true,
          tension: 0.4,
          pointBackgroundColor: "#FFD700",
          pointRadius: 4,
        },
      ],
    },
    options: {
      responsive: true,
      maintainAspectRatio: false,
      plugins: {
        legend: {
          display: false,
        },
      },
      scales: {
        y: {
          beginAtZero: true,
          grid: {
            color: "rgba(255, 255, 255, 0.05)",
          },
          ticks: {
            color: "rgba(255, 255, 255, 0.6)",
            stepSize: 1,
          },
        },
        x: {
          grid: {
            display: false,
          },
          ticks: {
            color: "rgba(255, 255, 255, 0.6)",
          },
        },
      },
    },
  });
}

function renderClassChart(classDist) {
  const ctx = document.getElementById("classChart").getContext("2d");

  if (classDist.length === 0) {
    // Show empty state if no data
    ctx.font = "14px Inter";
    ctx.fillStyle = "rgba(255, 255, 255, 0.5)";
    ctx.textAlign = "center";
    ctx.fillText("No data for today", ctx.canvas.width / 2, ctx.canvas.height / 2);
    return;
  }

  const labels = classDist.map((c) => "Class " + c.class);
  const counts = classDist.map((c) => c.count);

  new Chart(ctx, {
    type: "doughnut",
    data: {
      labels: labels,
      datasets: [
        {
          data: counts,
          backgroundColor: [
            "#FFD700",
            "#FFA500",
            "#FF8C00",
            "#DAA520",
            "#B8860B",
            "#ffd900",
            "#ffea00",
          ],
          borderWidth: 0,
          hoverOffset: 10,
        },
      ],
    },
    options: {
      responsive: true,
      maintainAspectRatio: false,
      plugins: {
        legend: {
          position: "right",
          labels: {
            color: "rgba(255, 255, 255, 0.7)",
            padding: 20,
            font: {
              family: "Inter",
            },
          },
        },
      },
    },
  });
}

function renderRecentLogs(logs) {
  const tbody = document.getElementById("recent-logs-body");
  tbody.innerHTML = "";

  if (logs.length === 0) {
    tbody.innerHTML = '<tr><td colspan="3" style="text-align:center; opacity:0.5;">No recent activity</td></tr>';
    return;
  }

  logs.forEach((log) => {
    const tr = document.createElement("tr");
    tr.innerHTML = `
            <td>${log.name}</td>
            <td>Class ${log.class || "N/A"}</td>
            <td>${log.time}</td>
        `;
    tbody.appendChild(tr);
  });
}
