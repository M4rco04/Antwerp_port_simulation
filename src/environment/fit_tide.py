"""Fit the tide, surge and weather models (PLAN.md §5.3) to the data from fetch_tide_data.py.

    tide      harmonic analysis (UTide) of each gauge: ~60 constituents including the shallow-water
              overtides (M4, MS4, M6, ...) that shape the asymmetric tide up the Scheldt
    LAT       the lowest astronomical tide of each gauge, from 19 years of predicted tide, so that
              tide heights and chart depths (m below LAT) share one datum
    surge     water level minus tide, explained per gauge by North Sea wind stress over the last
              24 h and air pressure (KNMI Vlissingen); what is left is kept as AR(1) noise
    weather   an hourly Markov chain of wind states (Beaufort class x 8 directions) with, per
              state, the observed hours (wind, pressure, visibility) to draw from

The last VALIDATION_DAYS are held out to measure the fit, then everything is refitted on all
data. The result is data/tides/tide_model.pkl, used by tide.py.

Usage:
    py src/environment/fit_tide.py
"""

from __future__ import annotations

import logging
import pickle
import warnings
from pathlib import Path

import numpy as np
import pandas as pd
import utide

from fetch_tide_data import GAUGES, KNMI_STATION, TIDE_DIR, WEATHER_DIR

MODEL_FILE = TIDE_DIR / "tide_model.pkl"
VALIDATION_DAYS = 90
LAT_YEARS = (2027, 2046)                       # 19 years: a full nodal cycle
SURGE_LAGS_H = (0, 3, 6, 9, 12, 18, 24, 36, 48)   # wind stress builds the North Sea surge over 1-2 days
PRESSURE_LAGS_H = (0, 12)
BEAUFORT_MS = (0.3, 1.6, 3.4, 5.5, 8.0, 10.8, 13.9, 17.2, 20.8, 24.5, 28.5, 32.7)
WIND_CLASSES = ((0, 3), (4, 4), (5, 5), (6, 6), (7, 7), (8, 12))   # Beaufort ranges of the chain's states
SECTORS = 8

log = logging.getLogger("tide")
warnings.filterwarnings("ignore", category=RuntimeWarning)


# ---------------------------------------------------------------------------
# tide


def load_gauge(code):
    s = pd.read_csv(TIDE_DIR / f"{code}.csv.gz", index_col=0, parse_dates=True).iloc[:, 0]
    return s.resample("10min").mean().dropna()


def solve(series, lat):
    return utide.solve(series.index, series.to_numpy(), lat=lat, method="ols", conf_int="none",
                       trend=False, constit="auto", verbose=False)


def predict(coef, times):
    return utide.reconstruct(pd.DatetimeIndex(times), coef, verbose=False).h


def high_waters(series):
    """Times and heights of the high waters (local maxima at least 9 h apart), after a 70-min
    running mean so that wiggles near the top of the tide do not count."""
    v = series.rolling("70min", center=True).mean().to_numpy()
    idx = [i for i in range(1, len(v) - 1) if v[i] >= v[i - 1] and v[i] > v[i + 1]]
    keep, times = [], series.index
    for i in idx:
        if keep and (times[i] - times[keep[-1]]) < pd.Timedelta(hours=9):
            if v[i] > v[keep[-1]]:
                keep[-1] = i
            continue
        keep.append(i)
    return times[keep], v[keep]


def hw_errors(observed, predicted):
    """Timing (min) and height (cm) errors of predicted high waters against the observed ones."""
    to, ho = high_waters(observed)
    tp, hp = high_waters(predicted)
    dt, dh = [], []
    for t, h in zip(tp, hp):
        j = np.argmin(np.abs((to - t).total_seconds()))
        if abs((to[j] - t).total_seconds()) < 3 * 3600:
            dt.append((t - to[j]).total_seconds() / 60)
            dh.append(h - ho[j])
    return np.array(dt), np.array(dh)


def lowest_and_highest(coef):
    """LAT and HAT (cm above NAP) over LAT_YEARS: hourly first, then 10-min around the extremes."""
    hours = pd.date_range(f"{LAT_YEARS[0]}-01-01", f"{LAT_YEARS[1]}-01-01", freq="1h", tz="UTC")
    h = predict(coef, hours)

    def refine(order):
        fine = pd.DatetimeIndex(np.concatenate([pd.date_range(hours[i] - pd.Timedelta("1h"), hours[i] + pd.Timedelta("1h"),
                                                              freq="5min") for i in order]))
        return predict(coef, fine)

    return float(refine(np.argsort(h)[:40]).min()), float(refine(np.argsort(-h)[:40]).max())


# ---------------------------------------------------------------------------
# surge and weather


def load_weather():
    w = pd.read_csv(WEATHER_DIR / f"knmi_{KNMI_STATION}.csv.gz", index_col=0, parse_dates=True)
    w = w[~w.index.duplicated()]          # month boundaries can repeat an hour
    w["speed"] = w.FH / 10.0
    w["pressure"] = w.P / 10.0
    calm = (w.DD == 0) | (w.DD == 990)
    w["direction"] = w.DD.where(~calm).ffill().fillna(0.0)
    return w


def surge_features(w):
    """Wind stress (speed x velocity, towards) components and pressure anomaly at the lags."""
    rad = np.radians(w.direction)
    tx, ty = -w.speed ** 2 * np.sin(rad), -w.speed ** 2 * np.cos(rad)     # blowing towards x (east), y (north)
    cols = {}
    for lag in SURGE_LAGS_H:
        cols[f"tx_{lag}"] = tx.shift(lag)
        cols[f"ty_{lag}"] = ty.shift(lag)
    for lag in PRESSURE_LAGS_H:
        cols[f"p_{lag}"] = (1013.0 - w.pressure).shift(lag)
    return pd.DataFrame(cols)


def fit_surge(residual_hourly, features):
    data = features.join(residual_hourly.rename("surge"), how="inner").dropna()
    X = np.column_stack([np.ones(len(data)), data.drop(columns="surge").to_numpy()])
    beta, *_ = np.linalg.lstsq(X, data.surge.to_numpy(), rcond=None)
    err = data.surge.to_numpy() - X @ beta
    phi = float(np.corrcoef(err[:-1], err[1:])[0, 1])
    sigma = float(np.std(err[1:] - phi * err[:-1]))
    return {"columns": list(data.columns.drop("surge")), "beta": beta, "phi": phi, "sigma_cm": sigma,
            "residual_std_cm": float(data.surge.std()), "error_std_cm": float(err.std())}


def surge_predict(model, features):
    X = features[model["columns"]]
    ok = X.notna().all(axis=1)
    out = pd.Series(np.nan, index=features.index)
    out[ok] = model["beta"][0] + X[ok].to_numpy() @ model["beta"][1:]
    return out


def beaufort(speed):
    return np.searchsorted(BEAUFORT_MS, speed, side="right")


def wind_state(w):
    bft = beaufort(w.speed.to_numpy())
    cls = np.zeros(len(bft), dtype=int)
    for i, (lo, hi) in enumerate(WIND_CLASSES):
        cls[(bft >= lo) & (bft <= hi)] = i
    sector = (np.round(w.direction.to_numpy() / (360 / SECTORS)) % SECTORS).astype(int)
    return cls * SECTORS + sector


def fit_weather_chain(w):
    states = wind_state(w)
    n = len(WIND_CLASSES) * SECTORS
    counts = np.full((n, n), 0.01)                       # a little smoothing for unseen transitions
    for a, b in zip(states[:-1], states[1:]):
        counts[a, b] += 1
    transition = counts / counts.sum(axis=1, keepdims=True)
    samples = {}
    obs = w[["speed", "direction", "pressure", "VV"]].to_numpy()
    for s in range(n):
        rows = obs[states == s]
        samples[s] = rows if len(rows) else None
    return {"transition": transition, "samples": samples, "wind_classes": WIND_CLASSES, "sectors": SECTORS,
            "state_frequency": np.bincount(states, minlength=n) / len(states)}


# ---------------------------------------------------------------------------


def main():
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    weather = load_weather()
    features = surge_features(weather)
    model = {"gauges": {}, "surge": {}, "datum": "NAP (cm) for coef and LAT/HAT"}
    for code, (name, lon, lat) in GAUGES.items():
        s = load_gauge(code)
        cut = s.index.max() - pd.Timedelta(days=VALIDATION_DAYS)
        train, test = s[s.index <= cut], s[s.index > cut]
        coef = solve(train, lat)
        pred = pd.Series(predict(coef, test.index), index=test.index)
        rmse_tide = float(np.sqrt(np.mean((test - pred) ** 2)))
        dt, dh = hw_errors(test, pred)
        # surge on the held-out months, from a surge model fitted on the training months
        resid_train = (train - predict(coef, train.index)).resample("1h").mean()
        resid_test = (test - pred).resample("1h").mean()
        surge_tr = fit_surge(resid_train, features)
        s_hat = surge_predict(surge_tr, features).reindex(resid_test.index)
        ok = s_hat.notna() & resid_test.notna()
        rmse_surge = float(np.sqrt(np.mean((resid_test[ok] - s_hat[ok]) ** 2)))
        both = (test - pred - s_hat.reindex(test.index, method="nearest")).dropna()
        validation = {"days": VALIDATION_DAYS, "rmse_tide_only_cm": round(rmse_tide, 1),
                      "rmse_tide_plus_surge_cm": round(float(np.sqrt(np.mean(both ** 2))), 1),
                      "hw_time_error_min": {"mean": round(float(dt.mean()), 1), "std": round(float(dt.std()), 1)},
                      "hw_height_error_cm": {"mean": round(float(dh.mean()), 1), "std": round(float(dh.std()), 1)},
                      "surge_std_cm": round(float(resid_test.std()), 1), "surge_rmse_after_model_cm": round(rmse_surge, 1)}
        # final model on all data
        coef = solve(s, lat)
        lat_cm, hat_cm = lowest_and_highest(coef)
        resid = (s - predict(coef, s.index)).resample("1h").mean()
        model["surge"][code] = fit_surge(resid, features)
        major = sorted(zip(coef.name, coef.A), key=lambda c: -c[1])[:6]
        model["gauges"][code] = {"name": name, "lon": lon, "lat": lat, "coef": coef, "lat_nap_cm": round(lat_cm, 1),
                                 "hat_nap_cm": round(hat_cm, 1), "mean_nap_cm": round(float(coef.mean), 1),
                                 "major_constituents_cm": {n: round(float(a), 1) for n, a in major},
                                 "n_constituents": len(coef.name), "data": [str(s.index.min()), str(s.index.max())],
                                 "validation": validation}
        log.info("%-22s LAT %6.1f HAT %6.1f cm NAP | test RMSE tide %5.1f -> +surge %5.1f cm | HW time %+5.1f±%4.1f min, "
                 "height %+5.1f±%4.1f cm | M2 %.0f cm, M4 %.0f cm", name, lat_cm, hat_cm, rmse_tide,
                 validation["rmse_tide_plus_surge_cm"], dt.mean(), dt.std(), dh.mean(), dh.std(),
                 dict(zip(coef.name, coef.A)).get("M2", 0), dict(zip(coef.name, coef.A)).get("M4", 0))
    model["weather_chain"] = fit_weather_chain(weather)
    model["surge_lags_h"], model["pressure_lags_h"] = SURGE_LAGS_H, PRESSURE_LAGS_H
    with open(MODEL_FILE, "wb") as f:
        pickle.dump(model, f)
    log.info("Saved %s", MODEL_FILE)


if __name__ == "__main__":
    main()
