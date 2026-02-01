document.addEventListener('DOMContentLoaded', () => {
    // UI Elements
    const userFilter = document.getElementById('userFilter');
    const filterMode = document.getElementById('filterMode');

    // Dynamic Inputs
    const rangeInput = document.getElementById('rangeFilter');
    const relativeFilter = document.getElementById('relativeFilter');
    const yearFilter = document.getElementById('yearFilter');
    const monthFilter = document.getElementById('monthFilter');
    const dayFilter = document.getElementById('dayFilter');

    // Containers
    const rangeContainer = document.getElementById('rangeInputContainer');
    const relativeContainer = document.getElementById('relativeInputContainer');
    const granularYearContainer = document.getElementById('granularYearContainer');
    const granularMonthContainer = document.getElementById('granularMonthContainer');
    const granularDayContainer = document.getElementById('granularDayContainer');

    const tableBody = document.getElementById('reportsTableBody');
    const noDataMsg = document.getElementById('noDataMessage');

    const btnExportCSV = document.getElementById('btnExportCSV');
    const btnExportJSON = document.getElementById('btnExportJSON');
    const btnExportExcel = document.getElementById('btnExportExcel');

    // Initialize Flatpickr
    const fp = flatpickr(rangeInput, {
        mode: "range",
        dateFormat: "Y-m-d",
        onChange: fetchData // Auto fetch on change
    });

    // Populate Year Dropdown (Current year down to 2020)
    const currentYear = new Date().getFullYear();
    for (let y = currentYear; y >= 2020; y--) {
        const opt = document.createElement('option');
        opt.value = y;
        opt.textContent = y;
        yearFilter.appendChild(opt);
    }
    // Select current year by default
    yearFilter.value = currentYear;

    // --- State Management ---

    function updateVisibility() {
        const mode = filterMode.value;

        // Hide all first
        rangeContainer.classList.add('hidden');
        relativeContainer.classList.add('hidden');
        granularYearContainer.classList.add('hidden');
        granularMonthContainer.classList.add('hidden');
        granularDayContainer.classList.add('hidden');

        if (mode === 'range') {
            rangeContainer.classList.remove('hidden');
        } else if (mode === 'relative') {
            relativeContainer.classList.remove('hidden');
        } else if (mode === 'granular') {
            granularYearContainer.classList.remove('hidden');
            granularMonthContainer.classList.remove('hidden');
            granularDayContainer.classList.remove('hidden');
        } else if (mode === 'today') {
            // No extra inputs needed
        }
    }

    // --- Fetch Logic ---

    async function fetchData() {
        const params = buildParams();
        const loader = document.getElementById('loadingSpinner');

        // Show loader, hide table and messages
        loader.style.display = 'block';
        tableBody.innerHTML = '';
        noDataMsg.style.display = 'none';

        try {
            const res = await fetch(`/api/attendance_records?${params.toString()}`);
            if (!res.ok) throw new Error("Failed to fetch data");
            const data = await res.json();
            loader.style.display = 'none';
            renderTable(data);
        } catch (err) {
            console.error(err);
            loader.style.display = 'none';
            tableBody.innerHTML = `<tr><td colspan="4" style="padding:1rem; text-align:center; color:red;">Error loading data</td></tr>`;
        }
    }

    function buildParams() {
        const params = new URLSearchParams();
        const mode = filterMode.value;

        // User Filter applies universally
        if (userFilter.value) {
            params.append('user_id', userFilter.value);
        }

        if (mode === 'today') {
            const today = new Date().toISOString().split('T')[0];
            params.append('date', today);
        }
        else if (mode === 'range') {
            const selectedDates = fp.selectedDates;
            if (selectedDates.length === 2) {
                // Flatpickr gives Date objects. Convert to ISO start/end
                const start = selectedDates[0];
                const end = selectedDates[1];

                // Set end to end of day
                const startISO = start.toISOString();
                const endISO = new Date(end.setHours(23, 59, 59, 999)).toISOString();

                params.append('start_iso', startISO);
                params.append('end_iso', endISO);
            }
        }
        else if (mode === 'relative') {
            const val = relativeFilter.value;
            const now = new Date();
            let start = new Date(now);

            // Subtract time
            if (val === '30m') start.setMinutes(now.getMinutes() - 30);
            if (val === '1h') start.setHours(now.getHours() - 1);
            if (val === '2h') start.setHours(now.getHours() - 2);
            if (val === '6h') start.setHours(now.getHours() - 6);
            if (val === '12h') start.setHours(now.getHours() - 12);
            if (val === '24h') start.setHours(now.getHours() - 24);

            params.append('start_iso', start.toISOString());
            params.append('end_iso', now.toISOString());
        }
        else if (mode === 'granular') {
            if (yearFilter.value) params.append('year', yearFilter.value);
            if (monthFilter.value) params.append('month', monthFilter.value);
            if (dayFilter.value) params.append('day', dayFilter.value);
        }

        return params;
    }

    function renderTable(data) {
        tableBody.innerHTML = '';

        if (data.length === 0) {
            noDataMsg.style.display = 'block';
            return;
        } else {
            noDataMsg.style.display = 'none';
        }

        data.forEach(row => {
            // Parse ISO timestamp and format in user's local timezone
            const date = new Date(row.timestamp);

            const dateStr = date.toLocaleDateString(undefined, {
                year: 'numeric',
                month: 'short',
                day: 'numeric'
            });

            const timeStr = date.toLocaleTimeString(undefined, {
                hour: 'numeric',
                minute: '2-digit',
                hour12: true
            });

            const tr = document.createElement('tr');
            tr.style.borderBottom = '1px solid rgba(255, 255, 255, 0.05)';
            tr.innerHTML = `
                <td style="padding: 1rem;">${row.id}</td>
                <td style="padding: 1rem; font-weight: bold;">${row.name}</td>
                <td style="padding: 1rem;">${row.class_name || '-'}</td>
                <td style="padding: 1rem;">${row.father_name || '-'}</td>
                <td style="padding: 1rem;">${dateStr}</td>
                <td style="padding: 1rem; font-family: monospace;">${timeStr}</td>
            `;
            tableBody.appendChild(tr);
        });
    }

    function doExport(format) {
        const params = buildParams();
        window.location.href = `/api/export/${format}?${params.toString()}`;
    }

    // Event Listeners
    filterMode.addEventListener('change', () => {
        updateVisibility();
        fetchData();
    });

    userFilter.addEventListener('change', fetchData);
    relativeFilter.addEventListener('change', fetchData);
    yearFilter.addEventListener('change', fetchData);
    monthFilter.addEventListener('change', fetchData);
    dayFilter.addEventListener('change', fetchData);

    btnExportCSV.addEventListener('click', () => doExport('csv'));
    btnExportJSON.addEventListener('click', () => doExport('json'));
    btnExportExcel.addEventListener('click', () => doExport('excel'));

    // Init
    updateVisibility();
    fetchData();
});
