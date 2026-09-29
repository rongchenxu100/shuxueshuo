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
    }
  };
})();
