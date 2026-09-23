from __future__ import annotations

import math
from typing import Sequence


def _dot(a: Sequence[float], b: Sequence[float]) -> float:
    return sum(x * y for x, y in zip(a, b))


def _mat_transpose(m: list[list[float]]) -> list[list[float]]:
    if not m:
        return []
    return [list(col) for col in zip(*m)]


def _mat_mult(a: list[list[float]], b: list[list[float]]) -> list[list[float]]:
    rows, cols = len(a), len(b[0])
    inner = len(b)
    out = [[0.0] * cols for _ in range(rows)]
    for i in range(rows):
        for k in range(inner):
            aik = a[i][k]
            if aik == 0:
                continue
            for j in range(cols):
                out[i][j] += aik * b[k][j]
    return out


def _mat_vec(m: list[list[float]], v: list[float]) -> list[float]:
    return [_dot(row, v) for row in m]


def _mat_inv(a: list[list[float]]) -> list[list[float]] | None:
    n = len(a)
    aug = [row[:] + [1.0 if i == j else 0.0 for j in range(n)] for i, row in enumerate(a)]
    for col in range(n):
        pivot = col
        for r in range(col + 1, n):
            if abs(aug[r][col]) > abs(aug[pivot][col]):
                pivot = r
        if abs(aug[pivot][col]) < 1e-12:
            return None
        if pivot != col:
            aug[col], aug[pivot] = aug[pivot], aug[col]
        div = aug[col][col]
        for j in range(2 * n):
            aug[col][j] /= div
        for r in range(n):
            if r == col:
                continue
            factor = aug[r][col]
            if factor == 0:
                continue
            for j in range(2 * n):
                aug[r][j] -= factor * aug[col][j]
    return [row[n:] for row in aug]


def design_matrix(n: int, k_count: int, extrapolation: int = 0) -> list[list[float]]:
    total_rows = n + extrapolation
    cols = 4 + k_count
    knots = [float(i) / (k_count + 1) for i in range(1, k_count + 1)]
    denom = max(1, n - 1)
    x: list[list[float]] = [[0.0] * cols for _ in range(total_rows)]
    for i in range(total_rows):
        xi = float(i) / denom
        x[i][0] = 1.0
        x[i][1] = xi
        x[i][2] = xi * xi
        x[i][3] = xi * xi * xi
        for j, knot in enumerate(knots):
            d = max(0.0, xi - knot)
            x[i][4 + j] = d * d * d
    return x


def solve_quantile_regression(
    x_train: list[list[float]],
    y: list[float],
    tau: float,
    iters: int,
) -> list[float]:
    n = len(x_train)
    p = len(x_train[0]) if x_train else 0
    if n == 0 or p == 0:
        return []

    xt = _mat_transpose(x_train)
    xtx = _mat_mult(xt, x_train)
    for i in range(p):
        xtx[i][i] += 1e-4
    xtx_inv = _mat_inv(xtx)
    y_avg = sum(y) / len(y) if y else 0.0
    if xtx_inv is None:
        beta = [0.0] * p
        beta[0] = y_avg
    else:
        beta = _mat_vec(_mat_mult(xtx_inv, xt), y)

    for _ in range(max(0, iters - 1)):
        y_pred = _mat_vec(x_train, beta)
        xtwx = [[0.0] * p for _ in range(p)]
        xtwy = [0.0] * p
        for i in range(n):
            res = y[i] - y_pred[i]
            w = (tau if res > 0 else (1.0 - tau)) / max(abs(res), 1e-6)
            for j in range(p):
                x_ij = x_train[i][j]
                xw = x_ij * w
                xtwy[j] += xw * y[i]
                for k in range(p):
                    xtwx[j][k] += xw * x_train[i][k]
        for j in range(p):
            xtwx[j][j] += 1e-4
        xtwx_inv = _mat_inv(xtwx)
        if xtwx_inv is None:
            break
        beta = _mat_vec(xtwx_inv, xtwy)
    return beta


def _fitted_at_row(
    x_row: list[float],
    beta: list[float],
    mu: float,
    sigma: float,
) -> float:
    return _dot(x_row, beta) * sigma + mu


def fit_quantile_bands(
    closes: list[float],
    *,
    knots: int = 3,
    iters: int = 50,
    upper_q: float = 0.95,
    mid_q: float = 0.5,
    lower_q: float = 0.05,
    extrapolation: int = 0,
) -> dict[str, float] | None:
    """closes: oldest → newest (n bars). Returns band prices at last bar (+ optional forecast)."""
    n = len(closes)
    if n < 10:
        return None
    mu_y = sum(closes) / n
    var = sum((c - mu_y) ** 2 for c in closes) / n
    stdev_y = max(math.sqrt(var), 1e-6)
    y_std = [(c - mu_y) / stdev_y for c in closes]

    x_all = design_matrix(n, knots, extrapolation)
    x_train = x_all[:n]

    b_up = solve_quantile_regression(x_train, y_std, upper_q, iters)
    b_mid = solve_quantile_regression(x_train, y_std, mid_q, iters)
    b_lo = solve_quantile_regression(x_train, y_std, lower_q, iters)
    if not b_mid:
        return None

    last = n - 1
    out = {
        "upper": _fitted_at_row(x_train[last], b_up, mu_y, stdev_y),
        "mid": _fitted_at_row(x_train[last], b_mid, mu_y, stdev_y),
        "lower": _fitted_at_row(x_train[last], b_lo, mu_y, stdev_y),
        "mu": mu_y,
        "sigma": stdev_y,
    }
    if extrapolation > 0 and len(x_all) > n:
        fut_row = x_all[n + extrapolation - 1]
        out["upper_forecast"] = _fitted_at_row(fut_row, b_up, mu_y, stdev_y)
        out["mid_forecast"] = _fitted_at_row(fut_row, b_mid, mu_y, stdev_y)
        out["lower_forecast"] = _fitted_at_row(fut_row, b_lo, mu_y, stdev_y)
    return out
