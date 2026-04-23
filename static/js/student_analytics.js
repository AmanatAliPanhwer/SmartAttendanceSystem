document.addEventListener("DOMContentLoaded", function () {
    const studentSelect = document.getElementById("studentSelect");
    const calendarDays = document.getElementById("calendarDays");
    const calendarMonthYear = document.getElementById("calendarMonthYear");
    const prevMonthBtn = document.getElementById("prevMonth");
    const nextMonthBtn = document.getElementById("nextMonth");
    const analyticsContent = document.getElementById("analyticsContent");
    const noSelection = document.getElementById("noSelection");
    const summaryStats = document.getElementById("summaryStats");
    
    let currentDate = new Date();
    let selectedUserId = null;
    let presentDays = [];

    studentSelect.addEventListener("change", function () {
        selectedUserId = this.value;
        if (selectedUserId) {
            analyticsContent.style.display = "block";
            summaryStats.style.display = "flex";
            noSelection.style.display = "none";
            fetchStudentData();
        } else {
            analyticsContent.style.display = "none";
            summaryStats.style.display = "none";
            noSelection.style.display = "block";
        }
    });

    prevMonthBtn.addEventListener("click", () => {
        currentDate.setMonth(currentDate.getMonth() - 1);
        fetchStudentData();
    });

    nextMonthBtn.addEventListener("click", () => {
        currentDate.setMonth(currentDate.getMonth() + 1);
        fetchStudentData();
    });

    async function fetchStudentData() {
        if (!selectedUserId) return;

        const month = currentDate.getMonth() + 1;
        const year = currentDate.getFullYear();

        try {
            const response = await fetch(`/api/student_calendar/${selectedUserId}?month=${month}&year=${year}`);
            const data = await response.json();
            
            presentDays = data.present_days;
            updateStats(data.stats);
            renderCalendar();
        } catch (error) {
            console.error("Error fetching student data:", error);
        }
    }

    function updateStats(stats) {
        document.getElementById("monthCount").textContent = stats.month_present;
        document.getElementById("totalCount").textContent = stats.total_present;
        calendarMonthYear.textContent = `${stats.month_name} ${stats.year}`;
    }

    function renderCalendar() {
        calendarDays.innerHTML = "";
        
        const year = currentDate.getFullYear();
        const month = currentDate.getMonth();
        
        const firstDayOfMonth = new Date(year, month, 1).getDay();
        const daysInMonth = new Date(year, month + 1, 0).getDate();
        
        const prevMonthLastDay = new Date(year, month, 0).getDate();
        const today = new Date();
        const todayStr = today.toISOString().split('T')[0];

        // 1. Previous Month Days (Padding)
        for (let i = firstDayOfMonth; i > 0; i--) {
            const dayDiv = document.createElement("div");
            dayDiv.classList.add("calendar-day", "other-month");
            dayDiv.textContent = prevMonthLastDay - i + 1;
            calendarDays.appendChild(dayDiv);
        }

        // 2. Current Month Days
        for (let i = 1; i <= daysInMonth; i++) {
            const dayDiv = document.createElement("div");
            dayDiv.classList.add("calendar-day");
            dayDiv.textContent = i;
            
            const dateStr = `${year}-${String(month + 1).padStart(2, '0')}-${String(i).padStart(2, '0')}`;
            
            if (presentDays.includes(dateStr)) {
                dayDiv.classList.add("present");
            }
            
            if (dateStr === todayStr) {
                dayDiv.classList.add("today");
            }
            
            calendarDays.appendChild(dayDiv);
        }

        // 3. Next Month Days (Padding to fill 6 rows if needed, or just 1 row)
        const totalDaysShown = firstDayOfMonth + daysInMonth;
        const nextMonthDays = 42 - totalDaysShown; // Standard 6-row calendar
        
        for (let i = 1; i <= nextMonthDays; i++) {
            const dayDiv = document.createElement("div");
            dayDiv.classList.add("calendar-day", "other-month");
            dayDiv.textContent = i;
            calendarDays.appendChild(dayDiv);
        }
    }
});
