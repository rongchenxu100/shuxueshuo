function cloneJson(value) {
  return value == null ? value : JSON.parse(JSON.stringify(value));
}

function applyDecorationPreset(item, stylePresets) {
  if (!item || typeof item !== "object" || Array.isArray(item) || !item.type) return item;
  const preset = stylePresets?.[item.type];
  if (!preset || typeof preset !== "object" || Array.isArray(preset)) return item;
  for (const [key, value] of Object.entries(preset)) {
    if (!(key in item)) item[key] = cloneJson(value);
  }
  return item;
}

function normalizeStepDecorations(stepDecorations, stylePresets) {
  if (!stepDecorations) return stepDecorations;
  const normalized = cloneJson(stepDecorations);
  for (const layer of Object.values(normalized.layers ?? {})) {
    for (const item of layer.elements ?? []) applyDecorationPreset(item, stylePresets);
  }
  for (const step of Object.values(normalized.steps ?? {})) {
    for (const item of step.add ?? []) applyDecorationPreset(item, stylePresets);
  }
  return normalized;
}

function fixedRangeForStep(step) {
  const t = Number(step?.t);
  return Number.isFinite(t) ? [t, t] : [0, 0];
}

function normalizePolicies(lessonData) {
  if (!lessonData) return lessonData;
  const normalized = cloneJson(lessonData);
  normalized.policies = normalized.policies && typeof normalized.policies === "object"
    ? normalized.policies
    : {};

  for (const step of normalized.steps ?? []) {
    if (!step?.id) continue;
    const policy = normalized.policies[step.id];
    if (!policy || typeof policy !== "object" || Array.isArray(policy)) {
      normalized.policies[step.id] = {
        movable: false,
        range: fixedRangeForStep(step)
      };
      continue;
    }
    if (policy.movable !== true && !Array.isArray(policy.range)) {
      policy.range = fixedRangeForStep(step);
    }
  }

  return normalized;
}

export function normalizeLessonSpec({ geometrySpec, stepDecorations, lessonData, stylePresets = {} }) {
  return {
    geometrySpec: cloneJson(geometrySpec),
    stepDecorations: normalizeStepDecorations(stepDecorations, stylePresets),
    lessonData: normalizePolicies(lessonData)
  };
}
