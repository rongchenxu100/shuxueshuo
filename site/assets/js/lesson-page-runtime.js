/**
 * 互动题页公共运行时：步骤导航、滑块、缩略图、题目折叠、IntersectionObserver。
 * 题页在定义 STEPS / POLICIES / STEP_LABELS、diagramMarkupFor、drawMini 后调用
 * LessonPageRuntime.init({ ... })。
 *
 * 暴露：window.LessonPageRuntime
 */
(function (global) {
  "use strict";

  function esc(s) {
    return String(s)
      .replaceAll("&", "&amp;")
      .replaceAll("<", "&lt;")
      .replaceAll(">", "&gt;");
  }

  function clamp(v, min, max) {
    return Math.max(min, Math.min(max, v));
  }

  function defaultFmt(v, precision) {
    const p = precision ?? 3;
    return Number(v)
      .toFixed(p)
      .replace(/\.?0+$/, "")
      .replace(/\.$/, "");
  }

  /**
   * @param {{ value: number, display: string }[]} landmarks
   * @param {number} [epsilon]
   * @param {number} [precision]
   */
  function createFmtFromLandmarks(landmarks, epsilon, precision) {
    const eps = epsilon ?? 0.004;
    if (!landmarks || !landmarks.length) {
      return function fmt(v) {
        return defaultFmt(v, precision);
      };
    }
    return function fmt(v) {
      const n = Number(v);
      for (let i = 0; i < landmarks.length; i += 1) {
        const item = landmarks[i];
        if (Math.abs(n - Number(item.value)) < eps) return String(item.display);
      }
      return defaultFmt(v, precision);
    };
  }

  function isMiniItemActive(item, activeT, miniEpsilon, rangeEpsilon) {
    const eps = rangeEpsilon ?? 0.0001;
    if (item.range && Array.isArray(item.range) && item.range.length >= 2) {
      const lo = Number(item.range[0]);
      const hi = Number(item.range[1]);
      const openLeft = Boolean(item.openLeft);
      const leftOk = openLeft ? activeT > lo + eps : activeT >= lo - eps;
      return leftOk && activeT <= hi + eps;
    }
    return Math.abs(activeT - Number(item.t)) < (miniEpsilon ?? 0.03);
  }

  function init(config) {
    const STEPS = config.steps || config.STEPS;
    const POLICIES = config.policies || config.POLICIES;
    const STEP_LABELS = config.stepLabels || config.STEP_LABELS;
    const diagramMarkupFor = config.diagramMarkupFor;
    const drawMini = config.drawMini;
    const groupTitle = typeof config.groupTitle === "function" ? config.groupTitle : null;
    const legendHtml = config.legendHtml ?? config.legendHTML ?? "";
    const sliderLabel = config.sliderLabel ?? "P 点 · t＝OP";
    const paramPrefix = config.paramLabelPrefix ?? "t=";
    const miniEpsilon = config.miniEpsilon ?? 0.03;
    const rangeEpsilon = config.rangeEpsilon ?? 0.0001;
    const viewBoxW = config.viewBoxWidth ?? 1080;
    const viewBoxH = config.viewBoxHeight ?? 760;
    const policyStepKey = config.policyStepKey ?? "id";
    const stepRangeStep = config.stepRangeStep ?? 0.001;
    const goToProblemMode = config.goToProblemMode ?? "doubleScroll";

    let fmt = config.fmt;
    if (typeof fmt !== "function") {
      fmt = createFmtFromLandmarks(config.paramLandmarks, config.paramLandmarkEpsilon, config.paramPrecision);
    }

    const stepCards = document.getElementById("stepCards");
    const stepNav = document.getElementById("stepNav");
    const mobileStepNav = document.getElementById("mobileStepNav");
    const problemCard = document.getElementById("problemCard");
    const problemToggle = document.getElementById("problemToggle");
    const railProgressText = document.getElementById("railProgressText");
    const railProgressFill = document.getElementById("railProgressFill");
    const mobileStepSheet = document.getElementById("mobileStepSheet");
    const mobileStepToggle = document.getElementById("mobileStepToggle");
    const mobileStepClose = document.getElementById("mobileStepClose");
    const mobileStepCount = document.getElementById("mobileStepCount");
    const mobileStepName = document.getElementById("mobileStepName");

    if (!stepCards || !stepNav || !STEPS || !POLICIES || !STEP_LABELS) {
      console.warn("LessonPageRuntime.init: missing DOM or STEPS/POLICIES/STEP_LABELS");
      return null;
    }

    let stepIndex = 0;
    let problemUserPreference = null;
    let stepObserver = null;
    const localVarsByStep = {};

    function defaultGroupTitle(section) {
      return section;
    }

    function renderStepNavMarkup() {
      const problemEntry =
        '<div class="step-group step-group-problem"><div class="step-group-title">题目</div><div class="step-dots">' +
        '<button class="step-dot" type="button" data-problem-nav="true" title="回到完整原题">原题</button></div></div>';
      const groups = [];
      STEPS.forEach(function (step) {
        let group = groups.find(function (item) {
          return item.section === step.section;
        });
        if (!group) {
          group = { section: step.section, steps: [] };
          groups.push(group);
        }
        group.steps.push(step);
      });
      return (
        problemEntry +
        groups
          .map(function (group) {
            const dots = group.steps
              .map(function (step, localIndex) {
                const index = STEPS.indexOf(step);
                const dot =
                  '<button class="step-dot ' +
                  (index < stepIndex ? "done " : "") +
                  (index === stepIndex ? "active" : "") +
                  '" type="button" data-step="' +
                  index +
                  '" title="' +
                  esc(step.title) +
                  '">' +
                  esc(STEP_LABELS[step[policyStepKey]]) +
                  "</button>";
                return localIndex === 0 ? dot : '<span class="step-connector"></span>' + dot;
              })
              .join("");
            const title = (groupTitle || defaultGroupTitle)(group.section);
            return (
              '<div class="step-group"><div class="step-group-title">' +
              esc(title) +
              '</div><div class="step-dots">' +
              dots +
              "</div></div>"
            );
          })
          .join("")
      );
    }

    function renderStepNav() {
      stepNav.innerHTML = renderStepNavMarkup();
      if (mobileStepNav) mobileStepNav.innerHTML = renderStepNavMarkup();
      if (railProgressText) railProgressText.textContent = stepIndex + 1 + " / " + STEPS.length;
      if (railProgressFill) railProgressFill.style.width = ((stepIndex + 1) / STEPS.length) * 100 + "%";
      if (mobileStepCount)
        mobileStepCount.textContent =
          STEPS[stepIndex].section + " · 步骤 " + (stepIndex + 1) + " / " + STEPS.length;
      if (mobileStepName) mobileStepName.textContent = STEP_LABELS[STEPS[stepIndex][policyStepKey]];
    }

    function renderMinisMarkup(step, activeT) {
      if (!step.minis) return "";
      const chips = step.minis
        .map(function (item) {
          const active = isMiniItemActive(item, activeT, miniEpsilon, rangeEpsilon);
          const rangeAttr = item.range ? esc(String(item.range[0]) + "," + String(item.range[1])) : "";
          const openLeftAttr = item.openLeft ? "true" : "";
          return (
            '<button class="mini-jump ' +
            (active ? "active" : "") +
            '" type="button" data-mini-t="' +
            esc(String(item.t)) +
            '"' +
            (rangeAttr ? ' data-mini-range="' + rangeAttr + '"' : "") +
            (openLeftAttr ? ' data-mini-open-left="' + openLeftAttr + '"' : "") +
            ">" +
            esc(item.title) +
            "</button>"
          );
        })
        .join("");
      const cards = step.minis
        .map(function (item) {
          const active = isMiniItemActive(item, activeT, miniEpsilon, rangeEpsilon);
          const rangeAttr = item.range ? esc(String(item.range[0]) + "," + String(item.range[1])) : "";
          const openLeftAttr = item.openLeft ? "true" : "";
          return (
            '<div class="mini-card ' +
            (active ? "active" : "") +
            '" role="button" tabindex="0" data-mini-t="' +
            esc(String(item.t)) +
            '" data-mini-card-t="' +
            esc(String(item.t)) +
            '"' +
            (rangeAttr ? ' data-mini-range="' + rangeAttr + '"' : "") +
            (openLeftAttr ? ' data-mini-open-left="' + openLeftAttr + '"' : "") +
            "><h3>" +
            esc(item.title) +
            "</h3>" +
            drawMini(item.t, item, step) +
            "<p>" +
            esc(item.caption) +
            "</p></div>"
          );
        })
        .join("");
      return (
        '<div class="mini-boundaries"><div class="mini-jump-row">' +
        chips +
        '</div><div class="mini-preview-strip">' +
        cards +
        "</div></div>"
      );
    }

    function localVarsForStep(index, step) {
      if (!localVarsByStep[index]) {
        localVarsByStep[index] = Object.assign({}, (step.localControls && step.localControls.values) || {});
      }
      return localVarsByStep[index];
    }

    function controlValue(sourceValue, control) {
      const scale = control.scale == null ? 1 : Number(control.scale);
      return Number(sourceValue || 0) * scale;
    }

    function formatControlValue(v, control) {
      const precision = control.precision == null ? 3 : Number(control.precision);
      return (control.prefix || "") + defaultFmt(v, precision) + (control.suffix || "");
    }

    function renderLocalControlsMarkup(step, index) {
      const cfg = step.localControls;
      if (!cfg || !Array.isArray(cfg.controls) || !cfg.controls.length) return "";
      const vars = localVarsForStep(index, step);
      const rows = cfg.controls
        .map(function (control, controlIndex) {
          const source = Number(vars[control.var] ?? 0);
          const value = controlValue(source, control);
          const stepAttr = control.step == null ? "0.001" : String(control.step);
          const id = "localControl-" + index + "-" + controlIndex;
          return (
            '<div class="step-slider-row step-point-control">' +
            '<label for="' +
            esc(id) +
            '">' +
            esc(control.label) +
            "</label>" +
            '<input id="' +
            esc(id) +
            '" type="range" min="' +
            esc(String(control.min)) +
            '" max="' +
            esc(String(control.max)) +
            '" step="' +
            esc(stepAttr) +
            '" value="' +
            esc(String(value)) +
            '" data-local-control-step="' +
            index +
            '" data-local-control-index="' +
            controlIndex +
            '" data-local-control-var="' +
            esc(control.var) +
            '" data-local-control-scale="' +
            esc(String(control.scale == null ? 1 : control.scale)) +
            '">' +
            '<span class="step-t-value" data-local-control-label="' +
            index +
            "-" +
            controlIndex +
            '">' +
            esc(formatControlValue(value, control)) +
            "</span></div>"
          );
        })
        .join("");
      return (
        '<div class="step-local-tools step-point-tools" data-local-controls="' +
        index +
        '">' +
        rows +
        (cfg.note ? '<div class="step-local-note">' + esc(cfg.note) + "</div>" : "") +
        "</div>"
      );
    }

    function renderDeriveLine(pair) {
      if (!Array.isArray(pair) || pair.length < 2) return "";
      const ref = pair[2];
      const refMarkup =
        ref && ref.refStep
          ? '<button class="derive-ref" type="button" data-step-ref="' +
            esc(String(ref.refStep)) +
            '" title="' +
            esc(ref.title || "跳转到引用步骤") +
            '">' +
            esc(ref.refLabel || "回看") +
            "</button>"
          : "";
      return (
        '<div class="derive-line"><strong>' +
        esc(String(pair[0] != null ? pair[0] : "")) +
        "</strong>" +
        esc(String(pair[1] != null ? pair[1] : "")) +
        refMarkup +
        "</div>"
      );
    }

    function renderAllSteps() {
      if (typeof config.beforeRenderAllSteps === "function") config.beforeRenderAllSteps();
      stepCards.innerHTML = STEPS.map(function (step, index) {
        const sid = step[policyStepKey];
        const policy = POLICIES[sid] || { movable: false, range: [step.t, step.t], reason: "" };
        const activeT = clamp(step.t, policy.range[0], policy.range[1]);
        const localVars = localVarsForStep(index, step);
        const derive = step.derive
          .map(function (pair) {
            return renderDeriveLine(pair);
          })
          .join("");
        const minis = renderMinisMarkup(step, activeT);
        const localControls = renderLocalControlsMarkup(step, index);
        const stepAttr = policy.step != null ? String(policy.step) : String(stepRangeStep);
        const tools = policy.movable
          ? '<div class="step-local-tools" data-step-tools="' +
            index +
            '"><div class="step-slider-row">' +
            '<label for="stepRange-' +
            esc(String(sid)) +
            '">' +
            esc(sliderLabel) +
            "</label>" +
            '<input id="stepRange-' +
            esc(String(sid)) +
            '" type="range" min="' +
            policy.range[0] +
            '" max="' +
            policy.range[1] +
            '" step="' +
            stepAttr +
            '" value="' +
            activeT +
            '" data-step-range="' +
            index +
            '">' +
            '<span class="step-t-value" data-step-t-label="' +
            index +
            '">' +
            esc(paramPrefix + fmt(activeT)) +
            "</span></div>" +
            '<div class="step-local-note">' +
            esc(policy.reason || "") +
            "</div></div>"
          : "";
        return (
          '<article class="card lesson-step-card" id="step-' +
          esc(String(sid)) +
          '" data-step-index="' +
          index +
          '">' +
          '<div class="step-card-head"><div class="step-card-title"><div class="step-section">' +
          esc(step.section) +
          "</div><h2>" +
          esc(step.title) +
          '</h2></div><div class="step-card-index">' +
          (index + 1) +
          "/" +
          STEPS.length +
          '</div></div><div class="step-card-body"><div class="step-card-diagram"><div class="svg-wrap"><svg viewBox="0 0 ' +
          viewBoxW +
          " " +
          viewBoxH +
          '" aria-label="' +
          esc(step.title) +
          '">' +
          diagramMarkupFor(index, activeT, localVars) +
          '</svg></div><div class="legend">' +
          legendHtml +
          "</div>" +
          tools +
          localControls +
          minis +
          '</div><div class="step-card-panel"><div class="derive-list">' +
          derive +
          "</div></div></div></article>"
        );
      }).join("");
      renderStepNav();
      observeSteps();
      if (typeof config.afterRenderAllSteps === "function") config.afterRenderAllSteps();
    }

    function updateProblemToggle() {
      if (!problemToggle || !problemCard) return;
      problemToggle.textContent = problemCard.classList.contains("collapsed") ? "展开完整题目" : "收起完整题目";
    }

    function syncProblemCardForInteraction() {
      if (problemUserPreference !== null) return;
      if (problemCard) problemCard.classList.add("collapsed");
      updateProblemToggle();
    }

    function setProblemVisibility(collapsed, user) {
      if (!problemCard) return;
      problemCard.classList.toggle("collapsed", collapsed);
      if (user) problemUserPreference = collapsed ? "collapsed" : "expanded";
      updateProblemToggle();
    }

    /**
     * 原南开页面默认展示题面答案 chip（样式通过 .answer-chip.show 控制）。
     * 统一运行时后这里补回该行为，避免题面答案被隐藏。
     */
    function showProblemAnswers() {
      if (!problemCard) return;
      problemCard.querySelectorAll(".answer-chip").forEach(function (el) {
        el.classList.add("show");
      });
    }

    function setActiveStep(next, options) {
      options = options || {};
      stepIndex = clamp(next, 0, STEPS.length - 1);
      document.querySelectorAll(".lesson-step-card").forEach(function (card, index) {
        card.classList.toggle("active-step", index === stepIndex);
      });
      renderStepNav();
      if (options.scroll) {
        const el = document.getElementById("step-" + STEPS[stepIndex][policyStepKey]);
        if (el) el.scrollIntoView({ behavior: "smooth", block: "start" });
      }
    }

    function setStep(next) {
      syncProblemCardForInteraction();
      setActiveStep(next, { scroll: true });
    }

    function goToProblem() {
      setProblemVisibility(false, true);
      if (!problemCard) return;
      if (goToProblemMode === "doubleScroll") {
        problemCard.scrollIntoView({ behavior: "auto", block: "start" });
        requestAnimationFrame(function () {
          problemCard.scrollIntoView({ behavior: "smooth", block: "start" });
        });
      } else {
        problemCard.scrollIntoView({ behavior: "smooth", block: "start" });
      }
    }

    function closeMobileStepSheet() {
      if (!mobileStepSheet) return;
      mobileStepSheet.classList.remove("open");
      mobileStepSheet.setAttribute("aria-hidden", "true");
    }

    function openMobileStepSheet() {
      if (!mobileStepSheet) return;
      mobileStepSheet.classList.add("open");
      mobileStepSheet.setAttribute("aria-hidden", "false");
    }

    function syncMiniActiveClasses(card, nextT) {
      if (!card) return;
      card.querySelectorAll("[data-mini-t]").forEach(function (el) {
        const rangeStr = el.dataset.miniRange;
        const openLeft = el.dataset.miniOpenLeft === "true";
        let active = false;
        if (rangeStr) {
          const parts = rangeStr.split(",").map(Number);
          const lo = parts[0];
          const hi = parts[1];
          active = openLeft ? nextT > lo + rangeEpsilon : nextT >= lo - rangeEpsilon;
          active = active && nextT <= hi + rangeEpsilon;
        } else {
          active = Math.abs(Number(el.dataset.miniT) - nextT) < miniEpsilon;
        }
        el.classList.toggle("active", active);
      });
    }

    function updateStepDiagram(index, value) {
      const step = STEPS[index];
      const sid = step[policyStepKey];
      const policy = POLICIES[sid];
      if (!policy || !policy.movable) return;
      const nextT = clamp(Number(value), policy.range[0], policy.range[1]);
      const card = document.querySelector('.lesson-step-card[data-step-index="' + index + '"]');
      const svgEl = card ? card.querySelector("svg") : null;
      const labelEl = card ? card.querySelector('[data-step-t-label="' + index + '"]') : null;
      const rangeEl = card ? card.querySelector('[data-step-range="' + index + '"]') : null;
      if (svgEl) svgEl.innerHTML = diagramMarkupFor(index, nextT, localVarsByStep[index]);
      if (labelEl) labelEl.textContent = paramPrefix + fmt(nextT);
      if (rangeEl && Number(rangeEl.value) !== nextT) rangeEl.value = String(nextT);
      syncMiniActiveClasses(card, nextT);
    }

    function currentStepT(card, index) {
      const rangeEl = card ? card.querySelector('[data-step-range="' + index + '"]') : null;
      if (rangeEl) return Number(rangeEl.value);
      return STEPS[index] ? STEPS[index].t : 0;
    }

    function updateLocalControl(index, controlIndex, value) {
      const step = STEPS[index];
      const cfg = step && step.localControls;
      const control = cfg && cfg.controls && cfg.controls[controlIndex];
      if (!step || !control) return;
      const scale = control.scale == null ? 1 : Number(control.scale);
      const vars = localVarsForStep(index, step);
      vars[control.var] = Number(value) / scale;

      const card = document.querySelector('.lesson-step-card[data-step-index="' + index + '"]');
      if (!card) return;
      (cfg.controls || []).forEach(function (item, i) {
        const v = controlValue(vars[item.var], item);
        const input = card.querySelector('[data-local-control-index="' + i + '"]');
        const label = card.querySelector('[data-local-control-label="' + index + "-" + i + '"]');
        if (input && Number(input.value) !== v) input.value = String(v);
        if (label) label.textContent = formatControlValue(v, item);
      });
      const svgEl = card.querySelector("svg");
      if (svgEl) svgEl.innerHTML = diagramMarkupFor(index, currentStepT(card, index), vars);
    }

    function observeSteps() {
      if (stepObserver) stepObserver.disconnect();
      stepObserver = new IntersectionObserver(
        function (entries) {
          const visible = entries
            .filter(function (entry) {
              return entry.isIntersecting;
            })
            .sort(function (a, b) {
              return b.intersectionRatio - a.intersectionRatio;
            })[0];
          if (!visible) return;
          const next = Number(visible.target.dataset.stepIndex);
          if (Number.isInteger(next) && next !== stepIndex) setActiveStep(next);
        },
        { rootMargin: "-20% 0px -55% 0px", threshold: [0.15, 0.3, 0.55] }
      );
      document.querySelectorAll(".lesson-step-card").forEach(function (card) {
        stepObserver.observe(card);
      });
      setActiveStep(stepIndex);
    }

    stepNav.addEventListener("click", function (event) {
      const problemTarget = event.target.closest("button[data-problem-nav]");
      if (problemTarget) {
        goToProblem();
        return;
      }
      const target = event.target.closest("button[data-step]");
      if (target) setStep(Number(target.dataset.step));
    });
    if (mobileStepNav) {
      mobileStepNav.addEventListener("click", function (event) {
        const problemTarget = event.target.closest("button[data-problem-nav]");
        if (problemTarget) {
          closeMobileStepSheet();
          goToProblem();
          return;
        }
        const target = event.target.closest("button[data-step]");
        if (target) {
          setStep(Number(target.dataset.step));
          closeMobileStepSheet();
        }
      });
    }
    if (mobileStepToggle) mobileStepToggle.addEventListener("click", openMobileStepSheet);
    if (mobileStepClose) mobileStepClose.addEventListener("click", closeMobileStepSheet);
    if (mobileStepSheet) {
      mobileStepSheet.addEventListener("click", function (event) {
        if (event.target === mobileStepSheet) closeMobileStepSheet();
      });
    }
    stepCards.addEventListener("input", function (event) {
      const localTarget = event.target.closest("input[data-local-control-step]");
      if (localTarget) {
        updateLocalControl(Number(localTarget.dataset.localControlStep), Number(localTarget.dataset.localControlIndex), localTarget.value);
        return;
      }
      const target = event.target.closest("input[data-step-range]");
      if (target) updateStepDiagram(Number(target.dataset.stepRange), target.value);
    });
    stepCards.addEventListener("click", function (event) {
      const refTarget = event.target.closest("[data-step-ref]");
      if (refTarget) {
        const targetIndex = STEPS.findIndex(function (step) {
          return String(step[policyStepKey]) === String(refTarget.dataset.stepRef);
        });
        if (targetIndex >= 0) setStep(targetIndex);
        return;
      }
      const target = event.target.closest("[data-mini-t]");
      if (!target) return;
      const card = target.closest(".lesson-step-card");
      updateStepDiagram(Number(card && card.dataset.stepIndex), target.dataset.miniT);
    });
    stepCards.addEventListener("keydown", function (event) {
      if (event.key !== "Enter" && event.key !== " ") return;
      const target = event.target.closest("[data-mini-t]");
      if (!target) return;
      event.preventDefault();
      const card = target.closest(".lesson-step-card");
      updateStepDiagram(Number(card && card.dataset.stepIndex), target.dataset.miniT);
    });
    if (problemToggle && problemCard) {
      problemToggle.addEventListener("click", function () {
        setProblemVisibility(!problemCard.classList.contains("collapsed"), true);
      });
    }
    updateProblemToggle();
    showProblemAnswers();
    renderAllSteps();

    return {
      renderAllSteps,
      renderStepNav,
      updateStepDiagram,
      goToProblem,
      getStepIndex: function () {
        return stepIndex;
      },
      setStepIndex: function (i) {
        stepIndex = i;
      }
    };
  }

  global.LessonPageRuntime = {
    init,
    esc,
    clamp,
    defaultFmt,
    createFmtFromLandmarks,
    isMiniItemActive
  };
})(window);
