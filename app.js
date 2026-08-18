const ARCHIVE = "https://www.aapt.org/physicsteam/PT-exams.cfm";
const DATA_FILE = "aapt-problems.json";

const $ = selector => document.querySelector(selector);
const $$ = selector => [...document.querySelectorAll(selector)];
const state = {
  topic: "All topics",
  source: "All",
  levels: new Set([1, 2, 3]),
  index: 0,
  shuffle: false,
  shuffleOrder: [],
  shuffleCursor: 0,
  saved: new Set(JSON.parse(localStorage.getItem("phys-saved") || "[]")),
  solved: new Set(JSON.parse(localStorage.getItem("phys-solved") || "[]")),
};

let problems = [];
let topics = [];

function current() {
  return problems.filter(problem =>
    (state.topic === "All topics" || problem.topic === state.topic) &&
    (state.source === "All" || problem.source === state.source) &&
    state.levels.has(problem.difficulty)
  );
}

function escapeHtml(value) {
  return String(value).replace(/[&<>"']/g, character => ({
    "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#039;",
  })[character]);
}

function clearMath(elements) {
  if (window.MathJax?.typesetClear) window.MathJax.typesetClear(elements.filter(Boolean));
}

function typesetMath(elements) {
  if (!window.MathJax?.typesetPromise) return;
  window.MathJax.typesetPromise(elements.filter(Boolean)).catch(error =>
    console.warn("MathJax could not render part of this problem:", error));
}

function pdfSnippets(paths, altText) {
  if (!Array.isArray(paths) || !paths.length) return "";
  return `<div class="pdf-snippets">${paths.map((path, index) =>
    `<img class="pdf-snippet" src="${escapeHtml(path)}" alt="${escapeHtml(altText)}${paths.length > 1 ? `, part ${index + 1}` : ""}" loading="${index ? "lazy" : "eager"}">`
  ).join("")}</div>`;
}

function art(problem) {
  let drawing;
  if (["Gravitation", "Circular motion", "Rotation"].includes(problem.topic)) {
    drawing = '<div class="sketch"><i class="ring"></i><i class="ball"></i></div>';
  } else if (["Waves", "Optics", "Oscillations"].includes(problem.topic)) {
    drawing = '<div class="wave"></div>';
  } else if (["Electricity", "Magnetism", "Modern physics"].includes(problem.topic)) {
    drawing = '<div class="charges"><b class="charge">+</b><i class="arrow"></i><b class="charge">−</b></div>';
  } else if (["Thermodynamics", "Fluids"].includes(problem.topic)) {
    drawing = '<div class="vessel"></div>';
  } else {
    drawing = '<div class="sketch"><i class="ground"></i><b class="block">m</b><i class="force"></i></div>';
  }
  if (problem.hasDiagram) {
    drawing += '<span class="diagram-note">diagram or graph appears in the source PDF</span>';
  }
  return drawing;
}

function syncFilters() {
  $("#topic").value = state.topic;
  $$("#sources button").forEach(button =>
    button.classList.toggle("on", button.dataset.value === state.source));
  $$("#levels button").forEach(button => {
    const selected = button.dataset.value === "All"
      ? state.levels.size === 3
      : state.levels.has(Number(button.dataset.value));
    button.classList.toggle("on", selected);
  });
}

function shuffleArray(values) {
  const result = [...values];
  for (let index = result.length - 1; index > 0; index -= 1) {
    const swapIndex = Math.floor(Math.random() * (index + 1));
    [result[index], result[swapIndex]] = [result[swapIndex], result[index]];
  }
  return result;
}

function rebuildShuffle() {
  const list = current();
  state.shuffleOrder = shuffleArray(list.map(problem => problem.id));
  state.shuffleCursor = 0;
  if (state.shuffleOrder.length) {
    state.index = list.findIndex(problem => problem.id === state.shuffleOrder[0]);
  }
}

function syncShuffleButton() {
  const button = $("#random");
  button.classList.toggle("shuffle-active", state.shuffle);
  button.textContent = state.shuffle ? "⇄ shuffle on" : "⇄ shuffle";
  button.setAttribute("aria-pressed", String(state.shuffle));
}

function filtersChanged() {
  state.index = 0;
  if (state.shuffle) rebuildShuffle();
  syncFilters();
  render();
}

function nextProblem() {
  const list = current();
  if (!list.length) return;
  if (!state.shuffle) {
    state.index += 1;
    render();
    return;
  }
  const validIds = new Set(list.map(problem => problem.id));
  if (!state.shuffleOrder.length || state.shuffleOrder.some(id => !validIds.has(id))) {
    rebuildShuffle();
  } else {
    state.shuffleCursor += 1;
    if (state.shuffleCursor >= state.shuffleOrder.length) rebuildShuffle();
    else state.index = list.findIndex(problem => problem.id === state.shuffleOrder[state.shuffleCursor]);
  }
  render();
}

function render() {
  let list = current();
  if (!list.length) {
    state.topic = "All topics";
    state.source = "All";
    state.levels = new Set([1, 2, 3]);
    state.shuffleOrder = [];
    syncFilters();
    toast("no matches — filters reset");
    list = current();
  }
  if (!list.length) return;

  state.index = (state.index % list.length + list.length) % list.length;
  const problem = list[state.index];
  const sourceName = `${problem.year} ${problem.source}${problem.variant ? ` ${problem.variant}` : ""} · ${problem.problemNumber}`;
  const mathElements = [$("#statement"), $("#choices"), $("#answerValue"), $("#explanation")];
  clearMath(mathElements);

  $("#position").textContent = String(state.index + 1).padStart(2, "0");
  $("#total").textContent = String(list.length).padStart(2, "0");
  $("#solved").textContent = state.solved.size;
  $("#bar").style.width = `${(state.index + 1) / list.length * 100}%`;
  $("#tags").innerHTML = [
    `<span class="tag source">${escapeHtml(problem.source)}</span>`,
    `<span class="tag">${escapeHtml(problem.topic)}</span>`,
    `<span class="tag">${escapeHtml(problem.subtopic)}</span>`,
    problem.hasDiagram ? '<span class="tag diagram-tag">source diagram</span>' : "",
  ].join("");
  $("#number").textContent = `ARCHIVE PROBLEM ${String(problem.id).padStart(3, "0")}`;
  $("#title").textContent = problem.title;
  const hasProblemImages = Array.isArray(problem.problemImages) && problem.problemImages.length > 0;
  $("#problemGrid").classList.toggle("pdf-mode", hasProblemImages);
  if (hasProblemImages) {
    $("#statement").innerHTML = pdfSnippets(problem.problemImages, `${sourceName} problem`);
    $("#diagram").innerHTML = "";
  } else {
    $("#statement").textContent = problem.statementLatex || problem.statement;
    $("#diagram").innerHTML = art(problem);
  }
  $("#source").href = ARCHIVE;
  $("#source").textContent = sourceName;
  $("#source").title = `Exam: ${problem.examFile}${problem.solutionFile ? ` | Solution: ${problem.solutionFile}` : ""}`;
  $("#dots").textContent = "●".repeat(problem.difficulty) + "○".repeat(3 - problem.difficulty);
  $("#dots").title = problem.difficultyBasis;
  $("#bookmark").textContent = state.saved.has(problem.id) ? "♥" : "♡";
  $("#bookmark").classList.toggle("saved", state.saved.has(problem.id));
  $("#answer").hidden = true;
  $("#show").innerHTML = `${problem.source === "USAPhO" ? "show solution" : "show answer"} <kbd>S</kbd>`;
  const answerLetter = /^[A-E]$/.test(problem.correctChoice || "") ? problem.correctChoice : "";
  $("#answerValue").textContent = answerLetter || "See the official solution below";
  const hasSolutionImages = Array.isArray(problem.solutionImages) && problem.solutionImages.length > 0;
  if (hasSolutionImages) {
    $("#explanation").innerHTML = pdfSnippets(problem.solutionImages, `${sourceName} solution`);
  } else {
    $("#explanation").textContent = problem.explanationLatex || problem.explanation;
  }
  $("#choices").classList.toggle("letter-choices", problem.source === "F=ma");
  $("#choices").innerHTML = problem.source === "F=ma"
    ? "ABCDE".split("").map(letter => `<button class="choice"><span>${letter}</span></button>`).join("")
    : "";
  $$(".choice").forEach((button, index) =>
    button.addEventListener("click", () => choose(button, index, problem)));
  typesetMath(mathElements);
}

function choose(button, selectedIndex, problem) {
  const correctIndex = /^[A-E]$/.test(problem.correctChoice || "")
    ? "ABCDE".indexOf(problem.correctChoice)
    : -1;
  $$(".choice").forEach((choice, index) => {
    choice.classList.remove("selected", "correct", "wrong");
    if (index === correctIndex) choice.classList.add("correct");
    else if (choice === button && correctIndex >= 0) choice.classList.add("wrong");
  });
  button.classList.add("selected");
  reveal();
}

function reveal() {
  const panel = $("#answer");
  const opening = panel.hidden;
  panel.hidden = !opening;
  const problem = current()[state.index];
  const noun = problem?.source === "USAPhO" ? "solution" : "answer";
  $("#show").innerHTML = `${opening ? "hide" : "show"} ${noun} <kbd>S</kbd>`;
  if (opening && problem) {
    state.solved.add(problem.id);
    save();
    $("#solved").textContent = state.solved.size;
  }
}

function save() {
  localStorage.setItem("phys-saved", JSON.stringify([...state.saved]));
  localStorage.setItem("phys-solved", JSON.stringify([...state.solved]));
}

function bookmark() {
  const problem = current()[state.index];
  if (!problem) return;
  state.saved.has(problem.id) ? state.saved.delete(problem.id) : state.saved.add(problem.id);
  save();
  render();
  toast(state.saved.has(problem.id) ? "saved to bookmarks" : "removed from bookmarks");
}

function toast(message) {
  const element = $("#toast");
  element.textContent = message;
  element.classList.add("show");
  clearTimeout(toast.timer);
  toast.timer = setTimeout(() => element.classList.remove("show"), 1800);
}

function showView(name) {
  $$(".view").forEach(element => element.classList.remove("active"));
  $$("nav button").forEach(button =>
    button.classList.toggle("active", button.dataset.view === name));
  $(`#${name}`).classList.add("active");
  window.scrollTo({top: 0, behavior: "smooth"});
  if (name === "library") renderLibrary();
}

function renderLibrary() {
  const query = $("#search").value.toLowerCase();
  const onlySaved = $("#savedOnly").checked;
  const list = problems.filter(problem =>
    (!onlySaved || state.saved.has(problem.id)) &&
    `${problem.title} ${problem.topic} ${problem.subtopic} ${problem.source} ${problem.year} ${problem.problemNumber} ${problem.statement}`
      .toLowerCase().includes(query)
  );
  $("#list").innerHTML = list.length ? list.map(problem => `
    <div class="row" data-id="${problem.id}" tabindex="0">
      <span>${String(problem.id).padStart(3, "0")}</span>
      <div><strong>${escapeHtml(problem.title)}</strong><span>${escapeHtml(problem.subtopic)} · ${"●".repeat(problem.difficulty)}${"○".repeat(3-problem.difficulty)}</span></div>
      <span>${problem.year} ${escapeHtml(problem.source)}${problem.variant ? ` ${problem.variant}` : ""}</span>
      <span>${escapeHtml(problem.topic)}</span><b>→</b>
    </div>`).join("") : '<p class="empty">No problems found. Try a broader search.</p>';
  $$(".row").forEach(row => {
    row.addEventListener("click", () => openProblem(Number(row.dataset.id)));
    row.addEventListener("keydown", event => {
      if (event.key === "Enter" || event.key === " ") openProblem(Number(row.dataset.id));
    });
  });
}

function openProblem(id) {
  const problem = problems.find(item => item.id === id);
  if (!problem) return;
  state.topic = problem.topic;
  state.source = "All";
  state.levels = new Set([1, 2, 3]);
  state.shuffle = false;
  state.shuffleOrder = [];
  syncShuffleButton();
  syncFilters();
  state.index = current().findIndex(item => item.id === id);
  showView("practice");
  render();
}

function attachEvents() {
  $("#topic").addEventListener("change", event => {
    state.topic = event.target.value;
    filtersChanged();
  });
  $$("#sources button").forEach(button => button.addEventListener("click", () => {
    state.source = button.dataset.value;
    filtersChanged();
  }));
  $$("#levels button").forEach(button => button.addEventListener("click", () => {
    if (button.dataset.value === "All") {
      state.levels = new Set([1, 2, 3]);
    } else {
      const level = Number(button.dataset.value);
      if (state.levels.size === 3) state.levels = new Set([level]);
      else if (state.levels.has(level) && state.levels.size > 1) state.levels.delete(level);
      else state.levels.add(level);
    }
    filtersChanged();
  }));
  $("#next").addEventListener("click", nextProblem);
  $("#random").addEventListener("click", () => {
    state.shuffle = !state.shuffle;
    if (state.shuffle) rebuildShuffle();
    else state.shuffleOrder = [];
    syncShuffleButton();
    render();
    toast(state.shuffle ? "shuffle on — no repeats until the deck is finished" : "shuffle off");
  });
  $("#show").addEventListener("click", reveal);
  $("#bookmark").addEventListener("click", bookmark);
  $$("nav button").forEach(button =>
    button.addEventListener("click", () => showView(button.dataset.view)));
  $("#theme").addEventListener("click", () => {
    document.body.classList.toggle("dark");
    localStorage.setItem("phys-theme", document.body.classList.contains("dark") ? "dark" : "light");
  });
  $("#search").addEventListener("input", renderLibrary);
  $("#savedOnly").addEventListener("change", renderLibrary);
  document.addEventListener("keydown", event => {
    if (["INPUT", "SELECT"].includes(document.activeElement.tagName)) return;
    if (event.key === "ArrowRight") nextProblem();
    if (event.key === "ArrowLeft") { state.index -= 1; render(); }
    if (event.key.toLowerCase() === "s") reveal();
    if (event.key.toLowerCase() === "b") bookmark();
  });
}

function loadDataset(dataset) {
  if (!dataset || !Array.isArray(dataset.problems) || !dataset.problems.length) {
    throw new Error("The selected file does not contain a non-empty problems array.");
  }
  problems = dataset.problems;
  topics = [...new Set(problems.map(problem => problem.topic))].sort();
  $("#topic").innerHTML = ["All topics", ...topics]
    .map(topic => `<option>${escapeHtml(topic)}</option>`).join("");
  $("#topicGrid").innerHTML = topics.map(topic => `
    <button class="topic-tile" data-topic="${escapeHtml(topic)}">
      <strong>${escapeHtml(topic)}</strong>
      <span>${problems.filter(problem => problem.topic === topic).length} PROBLEMS →</span>
    </button>`).join("");
  $$(".topic-tile").forEach(tile => tile.addEventListener("click", () => {
    state.topic = tile.dataset.topic;
    state.index = 0;
    syncFilters();
    showView("practice");
    render();
  }));
  state.index = 0;
  if (state.shuffle) rebuildShuffle();
  syncShuffleButton();
  render();
  renderLibrary();
  toast(`${problems.length} problems loaded from ${dataset.examCount || "the supplied"} exams`);
}

function showFilePicker(loadError) {
  $("#title").textContent = "Choose the problem dataset.";
  $("#statement").textContent = location.protocol === "file:"
    ? "Your browser blocks automatic JSON loading from file:// pages. Select aapt-problems.json below, or serve this folder with python3 -m http.server 8000."
    : `The archive data could not be loaded automatically: ${loadError.message}`;
  $("#diagram").innerHTML = '<div class="sketch"><b class="block">JSON</b></div>';
  $("#choices").innerHTML = '<button class="choice dataset-picker"><i>↥</i>choose aapt-problems.json</button><input id="datasetFile" type="file" accept=".json,.txt,application/json" hidden>';
  $(".dataset-picker").addEventListener("click", () => $("#datasetFile").click());
  $("#datasetFile").addEventListener("change", async event => {
    const file = event.target.files[0];
    if (!file) return;
    try {
      loadDataset(JSON.parse(await file.text()));
    } catch (error) {
      $("#statement").textContent = `Could not read ${file.name}: ${error.message}`;
    }
  });
}

async function init() {
  if (localStorage.getItem("phys-theme") === "dark") document.body.classList.add("dark");
  attachEvents();
  $("#title").textContent = "Loading the AAPT archive…";
  $("#statement").textContent = "Parsing 658 indexed problems from the local dataset.";
  try {
    const response = await fetch(DATA_FILE);
    if (!response.ok) throw new Error(`HTTP ${response.status}`);
    loadDataset(await response.json());
  } catch (error) {
    showFilePicker(error);
    console.error(error);
  }
}

init();