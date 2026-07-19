/**
 * Safe expression evaluator for compiled calculus lessons.
 * Supports arithmetic, powers, named variables and a small function whitelist.
 * Exposes window.MathExpressionEngine.
 */
(function (global) {
  "use strict";

  function evaluate(expression, environment) {
    if (expression == null || expression === "") return 0;
    var source = String(expression).replace(/\s+/g, "");
    var env = environment || {};
    var index = 0;

    function peek() {
      return source[index] || "";
    }

    function eat(token) {
      if (source.slice(index, index + token.length) === token) {
        index += token.length;
        return true;
      }
      return false;
    }

    function parseNumber() {
      var match = source.slice(index).match(/^(?:\d+(?:\.\d*)?|\.\d+)(?:e[+-]?\d+)?/i);
      if (!match) throw new Error("expected number at " + index);
      index += match[0].length;
      return Number(match[0]);
    }

    function parseIdentifier() {
      var match = source.slice(index).match(/^[A-Za-z_][A-Za-z0-9_]*/);
      if (!match) throw new Error("expected identifier at " + index);
      index += match[0].length;
      return match[0];
    }

    function callFunction(name, value) {
      if (name === "sqrt") return Math.sqrt(value);
      if (name === "abs") return Math.abs(value);
      if (name === "exp") return Math.exp(value);
      if (name === "ln" || name === "log") return Math.log(value);
      if (name === "sin") return Math.sin(value);
      if (name === "cos") return Math.cos(value);
      if (name === "tan") return Math.tan(value);
      throw new Error("unknown function: " + name);
    }

    function primary() {
      if (eat("(")) {
        var value = addSub();
        if (!eat(")")) throw new Error("missing ')' at " + index);
        return value;
      }
      if (/[0-9.]/.test(peek())) return parseNumber();

      var identifier = parseIdentifier();
      if (eat("(")) {
        var argument = addSub();
        if (!eat(")")) throw new Error("missing ')' after " + identifier);
        return callFunction(identifier, argument);
      }
      if (identifier === "pi") return Math.PI;
      if (identifier === "e") return Math.E;
      if (Object.prototype.hasOwnProperty.call(env, identifier)) {
        var resolved = Number(env[identifier]);
        if (!Number.isNaN(resolved)) return resolved;
      }
      throw new Error("unknown identifier: " + identifier);
    }

    function power() {
      var value = primary();
      if (eat("^")) value = Math.pow(value, unary());
      return value;
    }

    function unary() {
      if (eat("-")) return -unary();
      if (eat("+")) return unary();
      return power();
    }

    function mulDiv() {
      var value = unary();
      for (;;) {
        if (eat("*")) value *= unary();
        else if (eat("/")) value /= unary();
        else break;
      }
      return value;
    }

    function addSub() {
      var value = mulDiv();
      for (;;) {
        if (eat("+")) value += mulDiv();
        else if (eat("-")) value -= mulDiv();
        else break;
      }
      return value;
    }

    var result = addSub();
    if (index !== source.length) throw new Error("trailing expression: " + source.slice(index));
    return result;
  }

  global.MathExpressionEngine = {
    evaluate: evaluate
  };
})(typeof window !== "undefined" ? window : this);
