// supersys 前端：状态 / 规划 / 智能体。
const CLIENT_VERSION = "11"; // 请求里带上，便于确认页面是不是最新脚本
const $ = (id) => document.getElementById(id);
const nav = $("nav");
const VIEWS = ["status", "plan", "agent"];
const SECTION_BY_PATH = { "api/status": "status", "api/plan": "plan" };
let sections = [];
let agents = [];
let ready;

// 本地保存服务端最新数据：{height:[{id,name}], weight:[], meals:[], funds}
const state = { plan: emptySection(), status: emptySection() };

function emptySection() {
  return {
    height: [],
    weight: [],
    meals: [],
    sport: [],
    today: [],
    funds: null,
    income: null,
  };
}

/* ---------- 分区切换 ---------- */
function show(id) {
  for (const v of VIEWS) $(`view-${v}`).classList.toggle("on", v === id);
  for (const tab of nav.children) tab.classList.toggle("active", tab.dataset.id === id);
  $("run").style.display = id === "agent" ? "" : "none";
  history.replaceState(null, "", `#${id}`);
  if (id === "agent") loadStats().catch(() => {});
}

function renderNav() {
  nav.replaceChildren();
  for (const section of sections) {
    const tab = document.createElement("button");
    tab.className = "tab";
    tab.dataset.id = section.id;
    tab.textContent = section.name;
    tab.addEventListener("click", () => show(section.id));
    nav.append(tab);
  }
}

/* ---------- 常态 / 今日 / 基础：灰/亮切换，标签固定不动 ---------- */
function setupSwitchers() {
  for (const row of document.querySelectorAll(".switch-row")) {
    const labels = [...row.querySelectorAll(".switch")];
    const slots = [...row.querySelectorAll(".slot")];
    labels.forEach((label, index) => {
      label.addEventListener("click", () => {
        labels.forEach((item, i) => item.classList.toggle("on", i === index));
        slots.forEach((slot, i) => slot.classList.toggle("on", i === index));
      });
    });
  }
}

/* ---------- 接口 ---------- */
async function api(path, method = "GET", body) {
  const options = { method };
  if (body !== undefined) {
    options.headers = { "Content-Type": "application/json" };
    options.body = JSON.stringify(body);
  }
  const res = await fetch(path, options);
  if (res.status === 401) {
    location.replace("login");
    throw new Error("请先登录");
  }
  const data = await res.json().catch(() => ({}));
  if (!res.ok) throw new Error(data.error || "请求失败");
  return data;
}

const sectionPath = (section) => `api/${section}`;

async function fetchSection(section) {
  const data = await api(sectionPath(section));
  state[section] = data;
  return data;
}

function names(section, field) {
  return state[section][field].map((item) => item.name);
}

/* ---------- 时间 ---------- */
const WEEK_LABELS = ["一", "二", "三", "四", "五", "六", "日"];
// 运动日程显示用：紧凑写法，周日写「七」
const DAY_LABELS = ["一", "二", "三", "四", "五", "六", "七"];

// 1=周一 … 7=周日
function weekdayIndex(date = new Date()) {
  const day = date.getDay();
  return day === 0 ? 7 : day;
}

function weekdayLabel(date = new Date()) {
  return "周" + WEEK_LABELS[weekdayIndex(date) - 1];
}

function todayKey(date = new Date()) {
  const year = date.getFullYear();
  const month = String(date.getMonth() + 1).padStart(2, "0");
  const day = String(date.getDate()).padStart(2, "0");
  return `${year}-${month}-${day}`;
}

// 运动条件按周几：days 为空 = 每天
function appliesToday(item) {
  const days = item.days || [];
  return days.length === 0 || days.includes(weekdayIndex());
}

function sportPlanToday() {
  return state.plan.sport.filter(appliesToday);
}

// 状态里运动只算今天勾的
function statusNames(field) {
  if (field === "sport") {
    const today = todayKey();
    return state.status.sport
      .filter((item) => item.checkedOn === today)
      .map((item) => item.name);
  }
  return names("status", field);
}

/* ---------- 规划：约束条件定义（每行一个条件，改完点「确定」一次性提交） ---------- */
let defineSection = "plan";
let defineField = "meals";
let defineBase = []; // 打开弹窗时的条件列表，用来算这次改了哪些

function addDefineRow(name = "", focus = false, id = "") {
  const tr = document.createElement("tr");
  tr.dataset.id = id ? String(id) : "";

  const nameTd = document.createElement("td");
  const input = document.createElement("input");
  input.type = "text";
  input.className = "meal-name";
  input.value = name;
  input.addEventListener("keydown", (event) => {
    // 回车 = 在末尾新增一行并聚焦，连续录入不用动鼠标。
    if (event.key === "Enter") {
      event.preventDefault();
      addDefineRow("", true);
    }
  });
  nameTd.append(input);

  const delTd = document.createElement("td");
  const del = document.createElement("button");
  del.type = "button";
  del.className = "meal-del";
  del.textContent = "×";
  del.title = "删除";
  del.addEventListener("click", () => tr.remove()); // 点「确定」才真正提交
  delTd.append(del);

  tr.append(nameTd, delTd);
  $("meal-rows").append(tr);
  if (focus) {
    input.focus();
    input.scrollIntoView({ block: "nearest" });
  }
  return input;
}

function formatDays(days) {
  return days.map((day) => DAY_LABELS[day - 1]).join("");
}

// 运动直接写在文字里：「高脚杯深蹲，一三五七」；没有周几就是每天。
function defineText(item) {
  if (defineField === "sport" && item.days && item.days.length) {
    return `${item.name}，${formatDays(item.days)}`;
  }
  return item.name;
}

function renderDefineRows() {
  defineBase = state[defineSection][defineField].map((item) => ({
    id: item.id,
    text: defineText(item),
  }));
  $("meals-msg").textContent = "";
  $("meal-rows").replaceChildren();
  if (!defineBase.length) {
    addDefineRow("", true);
  } else {
    for (const item of defineBase) addDefineRow(item.text, false, item.id);
  }
}

// 对比打开时的列表，算出这次要提交的 删除 / 改名 / 新增。
function collectDefineOps() {
  const kept = new Set();
  const rename = [];
  const create = [];
  for (const tr of $("meal-rows").children) {
    const input = tr.querySelector(".meal-name");
    const value = input.value.trim();
    if (!value) continue;
    const id = tr.dataset.id || "";
    if (id) {
      kept.add(id);
      const baseItem = defineBase.find((item) => String(item.id) === id);
      if (baseItem && baseItem.text !== value) rename.push({ id: Number(id), name: value });
    } else {
      create.push(value);
    }
  }
  const remove = defineBase.filter((item) => !kept.has(String(item.id))).map((item) => item.id);
  return { create, rename, delete: remove };
}

async function openDefine(section, field) {
  await ready;
  defineSection = section;
  defineField = field;
  $("meals-msg").textContent = "";
  await fetchSection(section); // 每次打开先取最新数据
  renderDefineRows();
  $("meals-modal").classList.add("on");
}

$("meals-add").addEventListener("click", () => {
  addDefineRow("", true);
});

$("meals-ok").addEventListener("click", async () => {
  const ops = collectDefineOps();
  if (!ops.create.length && !ops.rename.length && !ops.delete.length) {
    $("meals-modal").classList.remove("on");
    return;
  }
  try {
    state[defineSection] = await api(`api/${defineSection}/batch`, "POST", {
      field: defineField,
      ops,
    });
    $("meals-modal").classList.remove("on");
  } catch (err) {
    $("meals-msg").textContent = "保存失败：" + err.message;
  }
});

$("meals-modal").addEventListener("click", (event) => {
  if (event.target === $("meals-modal")) $("meals-modal").classList.remove("on");
});

/* ---------- 状态：勾选规划里定义的条件 ---------- */
let checkField = "meals";

function renderCheckRows() {
  // 运动只列今天该做的；其它项列出规划里的全部条件。
  const planItems =
    checkField === "sport" ? sportPlanToday() : state.plan[checkField];
  const checkedNames = new Set(statusNames(checkField));

  const body = $("today-meal-rows");
  body.replaceChildren();
  if (!planItems.length) {
    const tr = document.createElement("tr");
    const td = document.createElement("td");
    td.colSpan = 2;
    td.className = "empty-cell";
    td.textContent =
      checkField === "sport" && state.plan.sport.length
        ? `今天（${weekdayLabel()}）没有安排运动`
        : "「规划 · 常态」还没有定义，先去那边设置";
    tr.append(td);
    body.append(tr);
    return;
  }
  for (const item of planItems) {
    const tr = document.createElement("tr");
    const nameTd = document.createElement("td");
    nameTd.textContent = item.name;
    const checkTd = document.createElement("td");
    const box = document.createElement("input");
    box.type = "checkbox";
    box.value = item.name;
    box.checked = checkedNames.has(item.name);
    checkTd.append(box);
    tr.append(nameTd, checkTd);
    body.append(tr);
  }
}

async function openCheck(field) {
  await ready;
  checkField = field;
  $("today-meals-msg").textContent = "";
  await Promise.all([fetchSection("plan"), fetchSection("status")]); // 先取最新数据
  renderCheckRows();
  $("today-meals-modal").classList.add("on");
}

$("meals-trigger").addEventListener("click", () => openCheck("meals"));
$("sport-trigger").addEventListener("click", () => openCheck("sport"));
$("today-trigger").addEventListener("click", () => openCheck("today"));
$("height-trigger").addEventListener("click", () => openCheck("height"));
$("weight-trigger").addEventListener("click", () => openCheck("weight"));
$("plan-meals-trigger").addEventListener("click", () => openDefine("plan", "meals"));
$("plan-sport-trigger").addEventListener("click", () => openDefine("plan", "sport"));
$("plan-today-trigger").addEventListener("click", () => openDefine("plan", "today"));
$("plan-height-trigger").addEventListener("click", () => openDefine("plan", "height"));
$("plan-weight-trigger").addEventListener("click", () => openDefine("plan", "weight"));

$("today-meals-ok").addEventListener("click", async () => {
  const checked = new Set(
    [...document.querySelectorAll("#today-meal-rows input:checked")].map((el) => el.value)
  );
  const planNames =
    checkField === "sport"
      ? sportPlanToday().map((item) => item.name)
      : names("plan", checkField);
  const statusItems =
    checkField === "sport"
      ? state.status.sport.filter((item) => item.checkedOn === todayKey())
      : [...state.status[checkField]];
  const statusNames = new Set(statusItems.map((item) => item.name));
  const create = planNames.filter((name) => checked.has(name) && !statusNames.has(name));
  const remove = statusItems.filter((item) => !checked.has(item.name)).map((item) => item.id);
  if (!create.length && !remove.length) {
    $("today-meals-modal").classList.remove("on");
    return;
  }
  try {
    state.status = await api("api/status/batch", "POST", {
      field: checkField,
      ops: { create, rename: [], delete: remove },
    });
    $("today-meals-modal").classList.remove("on");
  } catch (err) {
    $("today-meals-msg").textContent = "保存失败：" + err.message;
  }
});

$("today-meals-modal").addEventListener("click", (event) => {
  if (event.target === $("today-meals-modal")) $("today-meals-modal").classList.remove("on");
});

/* ---------- 数字字段（资金 / 收入）：弹窗里输入数字 ---------- */
let amountSection = "status";
let amountField = "funds";

async function openAmount(section, field) {
  await ready;
  amountSection = section;
  amountField = field;
  await fetchSection(section); // 先取最新数字
  $("funds-input").value = state[section][field] ?? "";
  $("funds-msg").textContent = "";
  $("funds-modal").classList.add("on");
  $("funds-input").focus();
  $("funds-input").select();
}

async function saveAmount() {
  try {
    state[amountSection] = await api(`api/${amountSection}/amounts`, "POST", {
      field: amountField,
      amount: $("funds-input").value,
    });
    $("funds-modal").classList.remove("on");
  } catch (err) {
    $("funds-msg").textContent = "保存失败：" + err.message;
  }
}

$("funds-trigger").addEventListener("click", () => openAmount("status", "funds"));
$("plan-funds-trigger").addEventListener("click", () => openAmount("plan", "funds"));
$("income-trigger").addEventListener("click", () => openAmount("status", "income"));
$("plan-income-trigger").addEventListener("click", () => openAmount("plan", "income"));
$("funds-ok").addEventListener("click", saveAmount);

$("funds-input").addEventListener("keydown", (event) => {
  if (event.key === "Enter") {
    event.preventDefault();
    saveAmount();
  }
});

$("funds-modal").addEventListener("click", (event) => {
  if (event.target === $("funds-modal")) $("funds-modal").classList.remove("on");
});

/* ---------- 智能体 ---------- */
const FIELD_LABELS = { height: "身高", weight: "体重", meals: "饮食", sport: "运动", today: "今日" };

// 条件列表的判断：状态里没勾 = 没满足；规划里没有 = 还没定义。
function listRule(fields, label) {
  return {
    missingPlan: () =>
      fields.some((field) => names("plan", field).length === 0)
        ? `「规划」里的${label}还没有定义`
        : null,
    isOk: () =>
      fields.every((field) =>
        names("plan", field).every((name) => names("status", field).includes(name))
      ),
    // 每条条件之间用「；」隔开，结果整体放一行。
    detail: () => {
      const parts = [];
      for (const field of fields) {
        const missing = names("plan", field).filter(
          (name) => !names("status", field).includes(name)
        );
        if (missing.length) parts.push(`${FIELD_LABELS[field]} 还差：${missing.join("；")}`);
      }
      return parts.join("；");
    },
  };
}

function parseAmount(value) {
  const text = String(value ?? "").replace(/[\s,，]/g, "");
  if (!text) return null;
  const number = Number(text);
  return Number.isFinite(number) ? number : null;
}

const fmtAmount = (number) => String(Math.round(number * 100) / 100);

/* 财务：资金、收入都是数字，规划填目标，状态填实际，实际 ≥ 目标算达标。 */
const AMOUNT_FIELDS = ["funds", "income"];
const AMOUNT_LABELS = { funds: "资金", income: "收入" };

const FINANCE_RULE = {
  missingPlan: () => {
    for (const field of AMOUNT_FIELDS) {
      if (parseAmount(state.plan[field]) === null) {
        return `「规划」里的${AMOUNT_LABELS[field]}还没有填写`;
      }
    }
    return null;
  },
  missingStatus: () => {
    for (const field of AMOUNT_FIELDS) {
      if (parseAmount(state.status[field]) === null) {
        return `「状态」里的${AMOUNT_LABELS[field]}还没有填写`;
      }
    }
    return null;
  },
  isOk: () =>
    AMOUNT_FIELDS.every(
      (field) => parseAmount(state.status[field]) >= parseAmount(state.plan[field])
    ),
  detail: () => {
    const parts = [];
    for (const field of AMOUNT_FIELDS) {
      const missing = parseAmount(state.plan[field]) - parseAmount(state.status[field]);
      if (missing > 0) {
        parts.push(`${AMOUNT_LABELS[field]} 还差：${fmtAmount(missing)} 元`);
      }
    }
    return parts.join("；");
  },
};

/* 运动：按周几安排。只判断「今天该做」的动作；状态里只算今天勾的。 */
const SPORT_RULE = {
  missingPlan: () => (state.plan.sport.length === 0 ? "「规划」里的运动还没有定义" : null),
  emptyText: () => (sportPlanToday().length === 0 ? `今天（${weekdayLabel()}）没有安排运动` : null),
  isOk: () => {
    const done = new Set(statusNames("sport"));
    return sportPlanToday().every((item) => done.has(item.name));
  },
  detail: () => {
    const done = new Set(statusNames("sport"));
    const missing = sportPlanToday()
      .filter((item) => !done.has(item.name))
      .map((item) => item.name);
    return `运动 还差：${missing.join("；")}`;
  },
};

const AGENT_RULES = {
  base: listRule(["height", "weight"], "身高体重"),
  finance: FINANCE_RULE,
  diet: listRule(["meals"], "饮食"),
  sport: SPORT_RULE,
  supervisor: listRule(["today"], "今日"),
};

function renderAgents(list) {
  const box = $("agent-list");
  box.replaceChildren();
  for (const agent of list) {
    const chip = document.createElement("span");
    chip.className = "agent";
    chip.textContent = agent.name;
    box.append(chip);
  }
}

// 结果统一放一行：每条条件之间用「；」隔开。
function judge(rule) {
  if (!rule) return "暂无检查规则";
  const planMissing = rule.missingPlan && rule.missingPlan();
  if (planMissing) return planMissing;
  const statusMissing = rule.missingStatus && rule.missingStatus();
  if (statusMissing) return statusMissing;
  const empty = rule.emptyText && rule.emptyText();
  if (empty) return empty;
  if (rule.isOk()) return "已达标";
  return `未达标：${rule.detail()}`;
}

async function checkAll() {
  await Promise.all([fetchSection("plan"), fetchSection("status")]);
  const body = $("check-body");
  body.replaceChildren();
  const results = [];
  for (const agent of agents) {
    const text = judge(AGENT_RULES[agent.id]);
    results.push({ agent: agent.id, name: agent.name, ok: text === "已达标", text });
    const tr = document.createElement("tr");
    const name = document.createElement("td");
    name.textContent = agent.name;
    const result = document.createElement("td");
    result.textContent = text;
    tr.append(name, result);
    body.append(tr);
  }
  $("check-modal").classList.add("on");
  await recordRun(results);
  await loadStats();
}

// 每天执行一次就记一条（同一天多次执行保留最后一次）
async function recordRun(results) {
  try {
    await api("api/runs", "POST", { results });
  } catch (err) {
    // 记录失败不打断执行结果的显示
  }
}

/* ---------- 统计图：每天一根柱 = 当天达标数 ---------- */
function statDateKey(date = new Date()) {
  const year = date.getFullYear();
  const month = String(date.getMonth() + 1).padStart(2, "0");
  const day = String(date.getDate()).padStart(2, "0");
  return `${year}-${month}-${day}`;
}

async function loadStats() {
  const barBox = $("stats-bars");
  const startLabel = $("stats-start");
  barBox.replaceChildren();
  startLabel.textContent = "";
  let runs = [];
  try {
    runs = (await api("api/runs")).runs || [];
  } catch (err) {
    return;
  }
  if (!runs.length) return;

  const byDate = new Map(runs.map((run) => [run.date, run]));
  const today = new Date();
  const todayValue = statDateKey(today);
  const viewDays = [];
  for (let back = 29; back >= 0; back--) {
    viewDays.push(
      statDateKey(new Date(today.getFullYear(), today.getMonth(), today.getDate() - back))
    );
  }
  for (const key of viewDays) {
    const run = byDate.get(key);
    const bar = document.createElement("div");
    bar.className = "stat-bar" + (key === todayValue ? " today" : "") + (run ? "" : " empty");
    if (run) {
      const ratio = run.total ? run.ok / run.total : 0;
      bar.style.height = `${Math.max(6, Math.round(ratio * 100))}%`;
      bar.title = `${key}：达标 ${run.ok}/${run.total}`;
    } else {
      bar.title = `${key}：没有执行`;
    }
    barBox.append(bar);
  }
  startLabel.textContent = viewDays[0].slice(5).replace("-", "/");
}

$("check-close").addEventListener("click", () => $("check-modal").classList.remove("on"));
$("check-modal").addEventListener("click", (event) => {
  if (event.target === $("check-modal")) $("check-modal").classList.remove("on");
});

/* ---------- 执行：只在智能体分区可用 ---------- */
function currentView() {
  return VIEWS.find((view) => $(`view-${view}`).classList.contains("on"));
}

$("run").addEventListener("click", () => {
  if (currentView() === "agent") checkAll();
});

/* ---------- 启动 ---------- */
ready = (async function boot() {
  // 云端模式有登录保护，显示「退出」按钮
  try {
    const session = await api("api/session");
    if (session.auth) {
      $("logout").hidden = false;
      $("logout").addEventListener("click", async () => {
        await api("api/logout", "POST", {});
        location.replace("login");
      });
    }
  } catch (err) {
    // 没登录的话 api() 已经跳到登录页了
  }
  const data = await api("api/sections");
  sections = data.sections;
  agents = data.agents;
  renderNav();
  setupSwitchers();
  renderAgents(agents);
  const fromHash = location.hash.slice(1);
  show(sections.some((s) => s.id === fromHash) ? fromHash : sections[0].id);
  await Promise.all([fetchSection("status"), fetchSection("plan")]);
})();
