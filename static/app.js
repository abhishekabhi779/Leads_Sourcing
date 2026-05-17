/**
 * SBA Lead Sourcing Machine — Frontend App
 */

// ── State ─────────────────────────────────────
let currentPage = 1;
let currentSort = "current_approval_amount";
let currentOrder = "desc";
let charts = {};
let filtersLoaded = false;

// ── Helpers ───────────────────────────────────
const $ = (sel) => document.querySelector(sel);
const $$ = (sel) => document.querySelectorAll(sel);
const fmt = (n) => n != null ? Number(n).toLocaleString() : "—";
const fmtMoney = (n) => n != null ? "$" + Number(n).toLocaleString(undefined, {maximumFractionDigits: 0}) : "—";

// ── Init ──────────────────────────────────────
document.addEventListener("DOMContentLoaded", async () => {
    await loadFilters();
    await loadStats();
    await loadLeads();
    setupEventListeners();
});

// ── Load Filter Options ───────────────────────
async function loadFilters() {
    try {
        const res = await fetch("/api/filters");
        const data = await res.json();
        populateSelect("#filter-state", data.states);
        populateSelect("#filter-status", data.statuses);
        populateSelect("#filter-biz-type", data.business_types);
        populateSelect("#filter-biz-age", data.business_ages);
        populateSelect("#filter-emp", data.employee_brackets);
        populateSelect("#filter-loan-size", data.loan_size_brackets);
        populateSelect("#filter-gender", data.genders);
        populateSelect("#filter-veteran", data.veterans);
        populateSelect("#filter-method", data.processing_methods);
        filtersLoaded = true;
    } catch (e) {
        console.error("Failed to load filters:", e);
    }
}

function populateSelect(selector, values) {
    const el = $(selector);
    el.innerHTML = "";
    values.forEach(v => {
        const opt = document.createElement("option");
        opt.value = v;
        opt.textContent = v;
        el.appendChild(opt);
    });
}

// ── Load Global Stats ─────────────────────────
async function loadStats() {
    try {
        const res = await fetch("/api/stats");
        const data = await res.json();
        $("#stat-total .stat-value").textContent = fmt(data.total_leads);
        $("#stat-amount .stat-value").textContent = fmtMoney(data.total_approved);
        $("#stat-jobs .stat-value").textContent = data.avg_jobs;
        $("#stat-states .stat-value").textContent = data.total_states;
        renderCharts(data);
    } catch (e) {
        console.error("Failed to load stats:", e);
    }
}

// ── Build Filter Query String ─────────────────
function buildQuery() {
    const params = new URLSearchParams();
    const multiSelects = {
        "filter-state": "state", "filter-status": "status",
        "filter-biz-type": "biz_type", "filter-biz-age": "biz_age",
        "filter-emp": "emp_bracket", "filter-loan-size": "loan_bracket",
        "filter-gender": "gender", "filter-veteran": "veteran",
        "filter-method": "method"
    };
    for (const [id, param] of Object.entries(multiSelects)) {
        const sel = $(`#${id}`);
        const vals = Array.from(sel.selectedOptions).map(o => o.value);
        if (vals.length > 0) params.set(param, vals.join(","));
    }
    const q = $("#filter-search").value.trim();
    if (q) params.set("q", q);
    const minAmt = $("#filter-min-amount").value;
    if (minAmt) params.set("min_amount", minAmt);
    const maxAmt = $("#filter-max-amount").value;
    if (maxAmt) params.set("max_amount", maxAmt);
    const minJobs = $("#filter-min-jobs").value;
    if (minJobs) params.set("min_jobs", minJobs);
    const maxJobs = $("#filter-max-jobs").value;
    if (maxJobs) params.set("max_jobs", maxJobs);
    if ($("#filter-property").checked) params.set("has_property", "1");
    if ($("#filter-nonprofit-only").checked) params.set("nonprofit", "Y");
    params.set("page", currentPage);
    params.set("sort", currentSort);
    params.set("order", currentOrder);
    return params.toString();
}

// ── Load Leads ────────────────────────────────
async function loadLeads() {
    const tbody = $("#leads-tbody");
    tbody.innerHTML = '<tr><td colspan="8"><div class="loading"><div class="spinner"></div>Loading leads...</div></td></tr>';

    try {
        const res = await fetch(`/api/leads?${buildQuery()}`);
        const data = await res.json();

        // Update filtered count
        $("#filtered-count").innerHTML = `Showing <strong>${fmt(data.total)}</strong> leads (page ${data.page} of ${fmt(data.total_pages)})`;

        // Render rows
        tbody.innerHTML = "";
        if (data.leads.length === 0) {
            tbody.innerHTML = '<tr><td colspan="8" style="text-align:center;padding:40px;color:var(--text-muted)">No leads match your filters</td></tr>';
            return;
        }

        data.leads.forEach(lead => {
            const tr = document.createElement("tr");
            const statusClass = lead.loan_status === "Paid in Full" ? "status-paid" :
                lead.loan_status === "Charged Off" ? "status-charged" : "status-exempt";
            tr.innerHTML = `
                <td class="td-name" title="${esc(lead.borrower_name)}">${esc(lead.borrower_name || "—")}</td>
                <td>${esc(lead.borrower_city || "—")}</td>
                <td>${esc(lead.borrower_state || "—")}</td>
                <td class="td-amount">${fmtMoney(lead.current_approval_amount)}</td>
                <td class="td-jobs">${lead.jobs_reported || "—"}</td>
                <td>${shortType(lead.business_type)}</td>
                <td><span class="status-badge ${statusClass}">${esc(lead.loan_status || "—")}</span></td>
                <td><button class="btn-view" onclick="viewLead(${lead.id})">View</button></td>
            `;
            tbody.appendChild(tr);
        });

        renderPagination(data.page, data.total_pages, data.total);
    } catch (e) {
        tbody.innerHTML = '<tr><td colspan="8" style="color:var(--accent-rose);padding:20px">Error loading leads. Is the server running?</td></tr>';
        console.error(e);
    }
}

function esc(s) {
    if (!s) return "";
    const d = document.createElement("div");
    d.textContent = s;
    return d.innerHTML;
}

function shortType(t) {
    if (!t) return "—";
    const map = {"Corporation":"Corp","Limited  Liability Company(LLC)":"LLC",
        "Subchapter S Corporation":"S-Corp","Non-Profit Organization":"Non-Profit",
        "Sole Proprietorship":"Sole Prop","Limited Liability Partnership":"LLP",
        "Professional Association":"Prof Assoc","Cooperative":"Co-op"};
    return map[t] || t;
}

// ── Pagination ────────────────────────────────
function renderPagination(page, totalPages, total) {
    const el = $("#pagination");
    if (totalPages <= 1) { el.innerHTML = ""; return; }

    let html = `<button class="page-btn" onclick="goPage(1)" ${page===1?'disabled':''}>«</button>`;
    html += `<button class="page-btn" onclick="goPage(${page-1})" ${page===1?'disabled':''}>‹</button>`;

    const start = Math.max(1, page - 3);
    const end = Math.min(totalPages, page + 3);
    if (start > 1) html += `<span class="page-info">...</span>`;
    for (let i = start; i <= end; i++) {
        html += `<button class="page-btn ${i===page?'active':''}" onclick="goPage(${i})">${i}</button>`;
    }
    if (end < totalPages) html += `<span class="page-info">...</span>`;

    html += `<button class="page-btn" onclick="goPage(${page+1})" ${page===totalPages?'disabled':''}>›</button>`;
    html += `<button class="page-btn" onclick="goPage(${totalPages})" ${page===totalPages?'disabled':''}>»</button>`;
    html += `<span class="page-info">${fmt(total)} total</span>`;
    el.innerHTML = html;
}

function goPage(p) {
    currentPage = p;
    loadLeads();
    $("#content-area").scrollTo({top: 0, behavior: "smooth"});
}

// ── Lead Detail Modal ─────────────────────────
async function viewLead(id) {
    $("#modal-overlay").classList.remove("hidden");
    $("#modal-content").innerHTML = '<div class="loading"><div class="spinner"></div>Loading...</div>';

    try {
        const res = await fetch(`/api/lead/${id}`);
        const d = await res.json();
        $("#modal-content").innerHTML = `
            <h2 class="modal-title">${esc(d.borrower_name)}</h2>
            <p class="modal-subtitle">${esc(d.borrower_address || "")} • ${esc(d.borrower_city || "")}, ${esc(d.borrower_state || "")} ${esc(d.borrower_zip || "")}</p>

            <div class="detail-grid">
                <div class="detail-card"><h4>Loan Amount</h4><p class="money">${fmtMoney(d.current_approval_amount)}</p></div>
                <div class="detail-card"><h4>Forgiven</h4><p class="money">${fmtMoney(d.forgiveness_amount)}</p></div>
                <div class="detail-card"><h4>Jobs Reported</h4><p>${d.jobs_reported || "—"}</p></div>
                <div class="detail-card"><h4>Loan Status</h4><p>${esc(d.loan_status)}</p></div>
            </div>

            <div class="detail-section">
                <h3>📋 Business Info</h3>
                ${detailRow("Type", d.business_type)}
                ${detailRow("Age", d.business_age)}
                ${detailRow("NAICS Code", d.naics_code)}
                ${detailRow("Franchise", d.franchise_name)}
                ${detailRow("Gender", d.gender)}
                ${detailRow("Veteran", d.veteran)}
                ${detailRow("Non-Profit", d.nonprofit === "Y" ? "Yes" : "No")}
                ${detailRow("Rural/Urban", d.rural_urban === "R" ? "Rural" : "Urban")}
                ${detailRow("HUBZone", d.hubzone)}
                ${detailRow("LMI Area", d.lmi)}
            </div>

            <div class="detail-section">
                <h3>💰 Financial Breakdown</h3>
                ${detailRow("Approved", fmtMoney(d.current_approval_amount))}
                ${detailRow("Initial Approval", fmtMoney(d.initial_approval_amount))}
                ${detailRow("Payroll", fmtMoney(d.payroll_proceed))}
                ${detailRow("Rent", fmtMoney(d.rent_proceed))}
                ${detailRow("Utilities", fmtMoney(d.utilities_proceed))}
                ${detailRow("Mortgage", fmtMoney(d.mortgage_proceed))}
                ${detailRow("Healthcare", fmtMoney(d.health_care_proceed))}
                ${detailRow("Debt Interest", fmtMoney(d.debt_interest_proceed))}
                ${detailRow("Total Proceeds", fmtMoney(d.total_proceeds))}
                ${detailRow("Forgiveness", fmtMoney(d.forgiveness_amount))}
                ${detailRow("Forgiveness Date", d.forgiveness_date)}
            </div>

            <div class="detail-section">
                <h3>📍 Project Location</h3>
                ${detailRow("City", d.project_city)}
                ${detailRow("State", d.project_state)}
                ${detailRow("County", d.project_county)}
                ${detailRow("ZIP", d.project_zip)}
                ${detailRow("District", d.congressional_district)}
            </div>

            <div class="detail-section">
                <h3>🏦 Lender Info</h3>
                ${detailRow("Servicing Lender", d.servicing_lender_name)}
                ${detailRow("Lender City", d.servicing_lender_city + ", " + d.servicing_lender_state)}
                ${detailRow("Originating Lender", d.originating_lender)}
            </div>

            <div class="detail-section">
                <h3>📝 Loan Details</h3>
                ${detailRow("Loan #", d.loan_number)}
                ${detailRow("Date Approved", d.date_approved)}
                ${detailRow("Term (months)", d.term)}
                ${detailRow("SBA Guaranty %", d.sba_guaranty_pct + "%")}
                ${detailRow("Processing", d.processing_method)}
            </div>
        `;
    } catch (e) {
        $("#modal-content").innerHTML = '<p style="color:var(--accent-rose)">Error loading details</p>';
    }
}

function detailRow(label, value) {
    return `<div class="detail-row"><span class="label">${label}</span><span class="value">${esc(String(value || "—"))}</span></div>`;
}

// ── Charts ────────────────────────────────────
const CHART_COLORS = [
    '#3b82f6','#8b5cf6','#10b981','#f59e0b','#f43f5e',
    '#06b6d4','#ec4899','#84cc16','#f97316','#6366f1',
    '#14b8a6','#e11d48','#a855f7','#22c55e','#eab308',
    '#0ea5e9','#d946ef','#65a30d','#fb923c','#818cf8'
];

function renderCharts(data) {
    renderBarChart("chart-state", data.by_state);
    renderDoughnutChart("chart-type", data.by_type);
    renderDoughnutChart("chart-status", data.by_status);
    renderBarChart("chart-employees", data.by_employees);
}

function renderBarChart(canvasId, items) {
    const ctx = document.getElementById(canvasId);
    if (charts[canvasId]) charts[canvasId].destroy();
    charts[canvasId] = new Chart(ctx, {
        type: "bar",
        data: {
            labels: items.map(i => i.label),
            datasets: [{
                data: items.map(i => i.value),
                backgroundColor: CHART_COLORS.slice(0, items.length),
                borderRadius: 4,
                borderSkipped: false,
            }]
        },
        options: {
            responsive: true,
            maintainAspectRatio: false,
            plugins: { legend: { display: false } },
            scales: {
                x: {
                    ticks: { color: "#64748b", font: { size: 10 }, maxRotation: 45 },
                    grid: { display: false }
                },
                y: {
                    ticks: { color: "#64748b", font: { family: "JetBrains Mono", size: 10 },
                        callback: v => v >= 1000 ? (v/1000)+"K" : v },
                    grid: { color: "rgba(255,255,255,0.04)" }
                }
            }
        }
    });
}

function renderDoughnutChart(canvasId, items) {
    const ctx = document.getElementById(canvasId);
    if (charts[canvasId]) charts[canvasId].destroy();
    charts[canvasId] = new Chart(ctx, {
        type: "doughnut",
        data: {
            labels: items.map(i => i.label),
            datasets: [{
                data: items.map(i => i.value),
                backgroundColor: CHART_COLORS.slice(0, items.length),
                borderWidth: 0,
                hoverOffset: 6
            }]
        },
        options: {
            responsive: true,
            maintainAspectRatio: false,
            cutout: "65%",
            plugins: {
                legend: {
                    position: "right",
                    labels: { color: "#94a3b8", font: { size: 10 }, padding: 8, boxWidth: 12 }
                }
            }
        }
    });
}

// ── Event Listeners ───────────────────────────
function setupEventListeners() {
    // Apply filters
    $("#btn-apply").addEventListener("click", () => { currentPage = 1; loadLeads(); });

    // Search on enter
    $("#filter-search").addEventListener("keydown", (e) => {
        if (e.key === "Enter") { currentPage = 1; loadLeads(); }
    });

    // Clear filters
    $("#btn-clear-filters").addEventListener("click", () => {
        $$("#filter-panel select").forEach(s => { for (let o of s.options) o.selected = false; });
        $$("#filter-panel input[type='text'], #filter-panel input[type='number']").forEach(i => i.value = "");
        $$("#filter-panel input[type='checkbox']").forEach(c => c.checked = false);
        currentPage = 1;
        loadLeads();
    });

    // Export
    $("#btn-export").addEventListener("click", () => {
        const q = buildQuery();
        window.open(`/api/leads/export?${q}`, "_blank");
    });

    // Sort
    $$("#leads-table th[data-sort]").forEach(th => {
        th.addEventListener("click", () => {
            const col = th.dataset.sort;
            if (currentSort === col) {
                currentOrder = currentOrder === "asc" ? "desc" : "asc";
            } else {
                currentSort = col;
                currentOrder = "desc";
            }
            $$("#leads-table th").forEach(t => t.classList.remove("sorted"));
            th.classList.add("sorted");
            currentPage = 1;
            loadLeads();
        });
    });

    // Chart/Table toggle
    $("#btn-toggle-charts").addEventListener("click", () => {
        $("#charts-panel").style.display = "grid";
        $("#btn-toggle-charts").classList.add("active");
        $("#btn-toggle-table").classList.remove("active");
    });
    $("#btn-toggle-table").addEventListener("click", () => {
        $("#charts-panel").style.display = "none";
        $("#btn-toggle-table").classList.add("active");
        $("#btn-toggle-charts").classList.remove("active");
    });

    // Modal close
    $("#modal-close").addEventListener("click", () => $("#modal-overlay").classList.add("hidden"));
    $("#modal-overlay").addEventListener("click", (e) => {
        if (e.target === $("#modal-overlay")) $("#modal-overlay").classList.add("hidden");
    });
    document.addEventListener("keydown", (e) => {
        if (e.key === "Escape") $("#modal-overlay").classList.add("hidden");
    });
}
