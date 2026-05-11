const CITIES = [
  { key: "tianjin", label: "天津" },
  { key: "beijing", label: "北京" },
  { key: "shanghai", label: "上海" },
  { key: "chongqing", label: "重庆" },
  { key: "guangzhou", label: "广州" }
];

const SLOTS = ["17", "18", "21", "24", "25", "26"];

const EXAMS = [
  { key: "all", label: "全部" },
  { key: "zhongkao", label: "中考真题" },
  { key: "yimo", label: "一模" },
  { key: "ermo", label: "二模" },
  { key: "topic", label: "专题训练" }
];

const TAG_LABELS = {
  geometry: "几何",
  folding: "折叠",
  translation: "平移",
  rotation: "旋转",
  "dynamic-point": "动点",
  function: "函数",
  algebra: "代数",
  "quadratic-function": "二次函数",
  "coordinate-plane": "坐标平面"
};

const state = {
  city: "tianjin",
  slot: "24",
  exam: "all",
  problems: []
};

async function loadProblems() {
  try {
    const response = await fetch("../data/problems.json");
    if (!response.ok) {
      throw new Error("Failed to load problems.json");
    }

    return await response.json();
  } catch (error) {
    return window.__PROBLEMS_DATA__ || [];
  }
}

function publishedProblems() {
  return state.problems.filter((problem) => problem.status === "published");
}

function getExamGroup(problem) {
  const exam = problem.exam || "";

  if (exam === "zhongkao") {
    return "zhongkao";
  }

  if (exam.includes("yimo")) {
    return "yimo";
  }

  if (exam.includes("ermo")) {
    return "ermo";
  }

  return "topic";
}

function countByCity(cityKey) {
  return publishedProblems().filter((problem) => problem.city === cityKey).length;
}

function countBySlot(slot) {
  return publishedProblems().filter((problem) => problem.city === state.city && problem.slot === slot).length;
}

function countByExam(examKey) {
  return getFilteredProblems({ exam: examKey }).length;
}

function getFilteredProblems(overrides = {}) {
  const city = overrides.city || state.city;
  const slot = overrides.slot || state.slot;
  const exam = overrides.exam || state.exam;

  return publishedProblems()
    .filter((problem) => problem.city === city)
    .filter((problem) => problem.slot === slot)
    .filter((problem) => exam === "all" || getExamGroup(problem) === exam)
    .sort((left, right) => right.year - left.year || left.examLabel.localeCompare(right.examLabel, "zh-Hans-CN"));
}

function renderCitySelector() {
  const root = document.querySelector("#city-selector");
  const count = document.querySelector("#city-count");

  if (!root || !count) {
    return;
  }

  count.textContent = `${publishedProblems().length} 道已发布`;
  root.innerHTML = CITIES.map((city) => {
    const total = countByCity(city.key);
    const isActive = city.key === state.city;

    return `
      <button class="library-city-card ${isActive ? "is-active" : ""}" type="button" data-city="${city.key}">
        <strong>${city.label}</strong>
        <span>${total ? `${total} 道题` : "待补充"}</span>
      </button>
    `;
  }).join("");
}

function renderSlotSelector() {
  const root = document.querySelector("#slot-selector");

  if (!root) {
    return;
  }

  root.innerHTML = SLOTS.map((slot) => {
    const total = countBySlot(slot);
    const isActive = slot === state.slot;

    return `
      <button class="library-slot-card ${isActive ? "is-active" : ""}" type="button" data-slot="${slot}">
        <span>第 ${slot} 题</span>
        <strong>${total ? `${total} 题` : "待补充"}</strong>
      </button>
    `;
  }).join("");
}

function renderExamSelector() {
  const root = document.querySelector("#exam-selector");

  if (!root) {
    return;
  }

  root.innerHTML = EXAMS.map((exam) => {
    const total = countByExam(exam.key);
    const isActive = exam.key === state.exam;

    return `
      <button class="library-exam-tab ${isActive ? "is-active" : ""}" type="button" data-exam="${exam.key}">
        ${exam.label}
        <span>${total}</span>
      </button>
    `;
  }).join("");
}

function renderProblemCard(problem) {
  const tags = Array.isArray(problem.tags)
    ? problem.tags.map((tag) => TAG_LABELS[tag] || tag).join(" / ")
    : "";

  return `
    <a class="library-problem-row" href="${problem.path}" target="_blank" rel="noopener noreferrer">
      <div class="library-problem-main">
        <strong>${problem.title}</strong>
        <p>${problem.cityLabel} · ${problem.year} · ${problem.examLabel} · 第 ${problem.slot} 题</p>
      </div>
      <div class="library-problem-meta">
        <span>${tags || "数学综合"}</span>
        <span class="is-published">已发布</span>
      </div>
      <span class="library-problem-arrow" aria-hidden="true">→</span>
    </a>
  `;
}

function renderEmptyState() {
  return `
    <div class="library-empty">
      <h3>这个位置还在补题中</h3>
      <p>可以先切换城市、题号或考试类型。后续会继续补充更多中考真题与模拟真题。</p>
    </div>
  `;
}

function renderResults() {
  const title = document.querySelector("#results-title");
  const count = document.querySelector("#results-count");
  const list = document.querySelector("#results-list");
  const city = CITIES.find((item) => item.key === state.city);
  const exam = EXAMS.find((item) => item.key === state.exam);
  const results = getFilteredProblems();

  if (!title || !count || !list || !city || !exam) {
    return;
  }

  title.textContent = `${city.label} · 第 ${state.slot} 题 · ${exam.label}`;
  count.textContent = `${results.length} 道`;
  list.innerHTML = results.length ? results.map(renderProblemCard).join("") : renderEmptyState();
}

function bindEvents() {
  document.addEventListener("click", (event) => {
    const cityButton = event.target.closest("[data-city]");
    const slotButton = event.target.closest("[data-slot]");
    const examButton = event.target.closest("[data-exam]");

    if (cityButton) {
      state.city = cityButton.dataset.city;
      state.exam = "all";
      render();
    }

    if (slotButton) {
      state.slot = slotButton.dataset.slot;
      state.exam = "all";
      render();
    }

    if (examButton) {
      state.exam = examButton.dataset.exam;
      render();
    }
  });
}

function render() {
  renderCitySelector();
  renderSlotSelector();
  renderExamSelector();
  renderResults();
}

loadProblems().then((problems) => {
  state.problems = problems;
  render();
  bindEvents();
});
