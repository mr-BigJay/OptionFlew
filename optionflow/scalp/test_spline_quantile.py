from optionflow.scalp.spline_quantile import design_matrix, fit_quantile_bands, solve_quantile_regression


def test_design_matrix_shape() -> None:
    x = design_matrix(20, 3, extrapolation=5)
    assert len(x) == 25
    assert len(x[0]) == 7


def test_quantile_bands_ordered_on_uptrend() -> None:
    closes = [100.0 + i * 0.3 + (i % 5) * 0.1 for i in range(60)]
    bands = fit_quantile_bands(closes, knots=3, iters=20, extrapolation=5)
    assert bands is not None
    assert bands["lower"] <= bands["mid"] <= bands["upper"]
    assert "mid_forecast" in bands


def test_solve_returns_coefficients() -> None:
    n = 15
    x = design_matrix(n, 2, 0)[:n]
    y = [float(i) for i in range(n)]
    beta = solve_quantile_regression(x, y, 0.5, 5)
    assert len(beta) == 6
