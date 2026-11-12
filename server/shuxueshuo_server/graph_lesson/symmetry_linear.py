"""Exact linear systems shared by opposite-input and general-symmetry certificates."""
import sympy as sp


def solve_linear(rows, columns, rhs):
    """A particular solution of rows·z = rhs, or None; free parameters are set to 0."""
    if columns == 0:
        return [] if all(v == 0 for v in rhs) else None
    if not rows:
        return [sp.S.Zero] * columns
    try:
        solution, params = sp.Matrix(rows).gauss_jordan_solve(sp.Matrix(rhs))
    except ValueError:
        return None
    return list(solution.subs({p: 0 for p in params}))


def certificate(rows, columns, rhs, target, constant):
    witness = solve_linear(rows, columns, rhs)
    if witness is None:
        raise ValueError('symmetry.conditions_inconsistent')
    transposed = sp.Matrix(len(rows), columns, [v for r in rows for v in r]).T.tolist()
    multipliers = solve_linear(transposed, len(rows), target)
    if multipliers is not None:
        return {'status': 'determined', 'value': sum((a*b for a, b in zip(multipliers, rhs)), constant),
                'multipliers': multipliers, 'witnesses': [witness]}
    matrix = sp.Matrix(len(rows), columns, [v for r in rows for v in r])
    direction = next(v for v in matrix.nullspace() if sum(a*b for a, b in zip(target, v)) != 0)
    return {'status': 'underdetermined', 'value': None, 'multipliers': None,
            'witnesses': [witness, [a+b for a, b in zip(witness, direction)]]}


def verify(rows, columns, rhs, target, constant, proof):
    """Check witnesses and row-space coefficients; never invoke the solving routine."""
    if not isinstance(proof, dict) or set(proof) != {'status', 'value', 'multipliers', 'witnesses'}:
        return False
    witnesses = proof['witnesses']
    if (not isinstance(witnesses, list) or not witnesses
            or any(not isinstance(w, list) or len(w) != columns for w in witnesses)):
        return False
    scalars = [v for w in witnesses for v in w]
    if isinstance(proof['multipliers'], list):
        scalars.extend(proof['multipliers'])
    if proof['value'] is not None:
        scalars.append(proof['value'])
    if any(isinstance(v, bool) or not isinstance(v, (int, sp.Rational)) for v in scalars):
        return False
    if any(sum(a*b for a, b in zip(row, w)) != v for w in witnesses for row, v in zip(rows, rhs)):
        return False
    if proof['status'] == 'determined':
        m = proof['multipliers']
        return (len(witnesses) == 1 and isinstance(m, list) and len(m) == len(rows)
                and all(sum(m[i]*rows[i][j] for i in range(len(rows))) == target[j] for j in range(columns))
                and sum((a*b for a, b in zip(m, rhs)), constant) == proof['value'])
    return (proof['status'] == 'underdetermined' and proof['value'] is None and proof['multipliers'] is None
            and len(witnesses) == 2
            and sum(a*(b-c) for a, b, c in zip(target, *witnesses)) != 0)
