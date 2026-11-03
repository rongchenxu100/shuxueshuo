import {projectFigures, mountQuestionFigures} from './question-figures.mjs?v=20261102-g1-actions';

export function choiceFigures(manifest, decision, context = {}) {
  const view = projectFigures(manifest, context);
  const ids = decision.figure_choices;
  const choices = decision.interaction?.options;
  if (!Array.isArray(ids) || ids.length < 2 || new Set(ids).size !== ids.length ||
      choices?.length !== ids.length || choices.some((c, i) => c.value !== ids[i])) throw new Error('原图与选项不匹配，请重新打开题目。');
  return ids.map((id, i) => {
    const rows = view.rows.filter(row => row.role === 'option' && row.option_id === id);
    if (rows.length !== 1 || rows[0].label !== choices[i].label) throw new Error('原图与选项不匹配，请重新打开题目。');
    return rows[0];
  });
}
export function mountFigureChoices(host, manifest, decision, context = {}) {
  const rows = choiceFigures(manifest, decision, context);
  const chosen = context.selected;
  const shown = context.readOnly ? rows.filter(row => row.option_id === chosen) : rows;
  const filtered = {...manifest, figures: [...manifest.figures.filter(row => row.role === 'source'), ...shown]};
  const dispose = mountQuestionFigures(host, filtered, {...context,
    selection: context.readOnly ? null : {field: decision.interaction.field, selected: chosen}});
  if (!context.readOnly) return dispose;
  for (const figure of host.querySelectorAll('[data-option-id]')) {
    const id = figure.dataset.optionId, label = rows.find(row => row.option_id === id).label;
    const node = host.ownerDocument.createElement('p');
    node.textContent = `已选 ${label}`;
    figure.append(node);
  }
  return dispose;
}
