/* Shared plain-text + LaTeX renderer. Lesson text is never treated as HTML. */
(() => {
  'use strict';
  window.PracticeMath = {
    render(element, statement) {
      element.textContent = statement;
      renderMathInElement(element, {
        delimiters: [
          {left: '$$', right: '$$', display: true},
          {left: '$', right: '$', display: false},
          {left: '\\[', right: '\\]', display: true},
          {left: '\\(', right: '\\)', display: false}
        ],
        // Auto-render catches each ParseError and preserves that formula's source.
        throwOnError: true,
        errorCallback: () => {},
        trust: false
      });
      // Chinese punctuation must not start a line after a formula.
      for (const katex of element.querySelectorAll('.katex')) {
        const formula = katex.parentElement !== element && !katex.nextSibling ? katex.parentElement : katex;
        const next = formula.nextSibling;
        const mark = next?.nodeType === Node.TEXT_NODE && next.data.match(/^[，。；：、！？）]+/);
        if (!mark) continue;
        const group = document.createElement('span');
        group.className = 'nowrap';
        formula.replaceWith(group);
        group.append(formula, mark[0]);
        next.data = next.data.slice(mark[0].length);
      }
    }
  };
})();
