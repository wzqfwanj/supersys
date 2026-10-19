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

/* ---------- 本地存储模式（手机 App 离线用；PC 本地模式走本地服务） ---------- */
const LOCAL_MODE =
  location.protocol === "file:" || new URLSearchParams(location.search).has("local");
const LOCAL_KEY = "supersys_local_data";
const LOCAL_SECTIONS = [
  { id: "status", name: "状态" },
  { id: "plan", name: "规划" },
  { id: "agent", name: "智能体" },
];
const LOCAL_AGENTS = [
  { id: "base", name: "基础智能体" },
  { id: "finance", name: "财务智能体" },
  { id: "diet", name: "饮食智能体" },
  { id: "sport", name: "运动智能体" },
  { id: "supervisor", name: "监管智能体" },
];
const LOCAL_LIST_FIELDS = ["height", "weight", "meals", "sport", "today"];
const WEEKDAY_CHARS = { 一: 1, 二: 2, 三: 3, 四: 4, 五: 5, 六: 6, 日: 7, 天: 7, 七: 7 };

function localEmptyStore() {
  return {
    items: { plan: {}, status: {} },
    amounts: { plan: {}, status: {} },
    runs: {},
    nextId: 1,
  };
}

function localLoadStore() {
  try {
    let raw = null;
    if (window.SupersysNative && window.SupersysNative.loadData) {
      raw = window.SupersysNative.loadData();
    }
    if (!raw) raw = localStorage.getItem(LOCAL_KEY);
    if (!raw) return localEmptyStore();
    const data = JSON.parse(raw);
    if (typeof data.nextId !== "number") data.nextId = 1;
    return data;
  } catch (err) {
    return localEmptyStore();
  }
}

function localSaveStore(store) {
  const raw = JSON.stringify(store);
  try {
    if (window.SupersysNative && window.SupersysNative.saveData) {
      window.SupersysNative.saveData(raw);
      return;
    }
    localStorage.setItem(LOCAL_KEY, raw);
  } catch (err) {
    // 存储失败时静默，界面数据还在内存里
  }
}

// 运动条件文字里的周几：「高脚杯深蹲，一三五七」
function localParseSportText(text) {
  const value = String(text || "").trim();
  const match = value.match(
    /^(.*?)[，,、；;]\s*([一二三四五六日天七周星期礼拜每末作工到至0-9、，,；;\s\-~—和及与]+)$/
  );
  if (!match) return { name: value, days: [] };
  const name = match[1].trim();
  const spec = match[2];
  let days = [];
  if (spec.includes("每天")) {
    days = [1, 2, 3, 4, 5, 6, 7];
  } else if (spec.includes("周末")) {
    days = [6, 7];
  } else if (spec.includes("工作日")) {
    days = [1, 2, 3, 4, 5];
  } else {
    const range = spec.match(/([1-7一二三四五六日天七])\s*[-~—到至]\s*([1-7一二三四五六日天七])/);
    if (range) {
      const start = WEEKDAY_CHARS[range[1]] || Number(range[1]);
      const end = WEEKDAY_CHARS[range[2]] || Number(range[2]);
      for (let day = start; day <= end; day += 1) days.push(day);
    } else {
      for (const ch of spec) if (WEEKDAY_CHARS[ch]) days.push(WEEKDAY_CHARS[ch]);
    }
  }
  days = [...new Set(days)].filter((day) => day >= 1 && day <= 7).sort((a, b) => a - b);
  return { name, days };
}

function localCleanAmount(value) {
  if (value === null || value === undefined || value === "") return null;
  const text = String(value).replace(/[\s,，]/g, "");
  return /^-?\d+(\.\d+)?$/.test(text) ? text : null;
}

function localItems(store, section, field) {
  store.items[section] = store.items[section] || {};
  store.items[section][field] = store.items[section][field] || [];
  return store.items[section][field];
}

function localSection(store, section) {
  const data = { funds: null, income: null };
  for (const field of ["funds", "income"]) {
    const stored = (store.amounts[section] || {})[field];
    data[field] = stored === undefined ? null : stored;
  }
  for (const field of LOCAL_LIST_FIELDS) {
    let items = [...localItems(store, section, field)];
    if (section === "status" && field === "sport") {
      items = items.filter((item) => item.checkedOn === todayKey());
    }
    data[field] = items.map((item) => ({
      id: item.id,
      name: item.name,
      days: item.days || [],
      checkedOn: item.checkedOn || null,
    }));
  }
  return data;
}

function localAddItems(store, section, field, entries) {
  for (const entry of entries) {
    let name = String(entry.name || "").trim().slice(0, 200);
    let days = entry.days || [];
    if (field === "sport") {
      if (section === "plan") {
        const parsed = localParseSportText(name);
        name = parsed.name;
        days = parsed.days;
      } else {
        days = [];
      }
    }
    if (!name) throw new Error("条件不能为空");
    if (section === "status") {
      const plan = localItems(store, "plan", field);
      if (!plan.some((item) => item.name === name)) {
        throw new Error("「规划」里没有这个条件，先在那里定义");
      }
      if (field === "sport") {
        store.items.status.sport = localItems(store, "status", "sport").filter(
          (item) => item.checkedOn === todayKey()
        );
      }
    }
    const items = localItems(store, section, field);
    if (items.some((item) => item.name === name)) continue;
    items.push({
      id: store.nextId++,
      name,
      days,
      checkedOn: section === "status" && field === "sport" ? todayKey() : null,
    });
  }
}

function localApplyBatch(store, section, field, ops) {
  for (const rawId of ops.delete || []) {
    const id = Number(rawId);
    const items = localItems(store, section, field);
    const target = items.find((item) => item.id === id);
    if (!target) continue;
    store.items[section][field] = items.filter((item) => item.id !== id);
    if (section === "plan") {
      store.items.status[field] = localItems(store, "status", field).filter(
        (item) => item.name !== target.name
      );
    }
  }
  for (const op of ops.rename || []) {
    const id = Number(op && op.id !== undefined ? op.id : op[0]);
    const rawName = op && op.name !== undefined ? op.name : op && op[1];
    const items = localItems(store, section, field);
    const target = items.find((item) => item.id === id);
    if (!target || rawName === undefined) continue;
    let name = String(rawName).trim().slice(0, 200);
    let days = target.days;
    if (field === "sport" && section === "plan") {
      const parsed = localParseSportText(name);
      name = parsed.name;
      days = parsed.days;
    }
    if (!name) continue;
    const old = target.name;
    target.name = name;
    target.days = days;
    if (section === "plan") {
      for (const statusItem of localItems(store, "status", field)) {
        if (statusItem.name === old) statusItem.name = name;
      }
    }
  }
  const creates = (ops.create || []).map((item) =>
    typeof item === "string" ? { name: item } : item
  );
  localAddItems(store, section, field, creates);
}

async function localApi(path, method = "GET", body) {
  const store = localLoadStore();
  const clean = path.replace(/^\/+/, "").replace(/\?.*$/, "");
  const parts = clean.split("/");
  if (parts[0] !== "api") throw new Error("接口不存在");
  const resource = parts[1];
  if (resource === "session") return { auth: false, loggedIn: true, mode: "local" };
  if (resource === "sections") {
    return { app: "supersys", sections: LOCAL_SECTIONS, agents: LOCAL_AGENTS };
  }
  if (resource === "plan" || resource === "status") {
    const section = resource;
    if (parts.length === 2) return localSection(store, section);
    const action = parts[2];
    if (action === "batch" && method === "POST") {
      localApplyBatch(store, section, body.field, body.ops || {});
      localSaveStore(store);
      return localSection(store, section);
    }
    if (action === "amounts" && method === "POST") {
      store.amounts[section] = store.amounts[section] || {};
      store.amounts[section][body.field] = localCleanAmount(body.amount);
      localSaveStore(store);
      return localSection(store, section);
    }
  }
  if (resource === "runs") {
    if (method === "POST") {
      const results = (body.results || []).slice(0, 20);
      const ok = results.filter((item) => item.ok).length;
      store.runs[todayKey()] = { ok, total: results.length, results };
      localSaveStore(store);
      return { ok: true, date: todayKey(), okCount: ok, total: results.length };
    }
    const runs = Object.entries(store.runs)
      .map(([date, value]) => ({ date, ...value }))
      .sort((a, b) => (a.date < b.date ? -1 : 1));
    return { runs };
  }
  throw new Error("接口不存在");
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
  if (LOCAL_MODE) return localApi(path, method, body);
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

/* ---------- 登录云端（本地模式下也可以主动登录） ---------- */
const CLOUD_URL_KEY = "supersys_cloud_url";

function openLoginDialog() {
  $("login-url").value = localStorage.getItem(CLOUD_URL_KEY) || "";
  $("login-msg").textContent = "";
  $("login-modal").classList.add("on");
  $("login-url").focus();
}

$("login").addEventListener("click", openLoginDialog);
$("login-cancel").addEventListener("click", () => $("login-modal").classList.remove("on"));
$("login-modal").addEventListener("click", (event) => {
  if (event.target === $("login-modal")) $("login-modal").classList.remove("on");
});
$("login-ok").addEventListener("click", () => {
  let url = $("login-url").value.trim();
  const msg = $("login-msg");
  if (!url) {
    msg.textContent = "请输入服务器地址";
    return;
  }
  if (!/^https?:\/\//i.test(url)) url = "https://" + url;
  if (!url.endsWith("/")) url += "/";
  try {
    localStorage.setItem(CLOUD_URL_KEY, url);
  } catch (err) {
    // file:// 下 localStorage 不可用时忽略
  }
  location.href = url + "login";
});

/* ---------- 启动 ---------- */
ready = (async function boot() {
  // 云端模式显示「退出」，本地模式显示「登录」（可以主动登录云端）
  try {
    const session = await api("api/session");
    if (session.auth) {
      $("logout").hidden = false;
      $("logout").addEventListener("click", async () => {
        await api("api/auth/logout", "POST", {});
        location.replace("login");
      });
    } else {
      $("login").hidden = false;
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
