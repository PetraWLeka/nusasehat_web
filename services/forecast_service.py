"""
NusaHealth Cloud — LightGBM Forecast Service
Time-series forecasting for illness trends and item demand
using LightGBM with weather features, lag/rolling features,
and TimeSeriesSplit (5 expanding windows) cross-validation.

Saves training performance plots (matplotlib) for monitoring.
"""

import json
import logging
import pickle
import re
from datetime import datetime, timedelta
from pathlib import Path

import numpy as np
import pandas as pd

from django.conf import settings

logger = logging.getLogger("nusahealth")

DATA_DIR = Path(settings.BASE_DIR) / "data"
MODEL_DIR = DATA_DIR / "models"
PLOT_DIR = MODEL_DIR / "plots"


class ForecastService:
    """LightGBM-based demand forecasting for items and illnesses."""

    MIN_DATA_POINTS = 30  # min days of data needed
    N_SPLITS = 5          # TimeSeriesSplit expanding windows
    FORECAST_HORIZON = 14 # days to forecast

    def __init__(self):
        MODEL_DIR.mkdir(parents=True, exist_ok=True)
        PLOT_DIR.mkdir(parents=True, exist_ok=True)

    # ── Data Loading ─────────────────────────────────────────

    def _load_weather(self) -> pd.DataFrame:
        """Load weather history CSV into DataFrame."""
        path = DATA_DIR / "weather_history.csv"
        if not path.exists():
            logger.debug("No weather_history.csv found")
            return pd.DataFrame()
        df = pd.read_csv(path, parse_dates=["date"])
        df = df.sort_values("date").reset_index(drop=True)
        return df

    def _load_series(self, csv_name, group_col, value_col) -> dict:
        """Load CSV and return daily time series per group.

        Returns dict[str, pd.DataFrame] where each DataFrame has
        columns: date, value (daily aggregated).
        """
        filepath = DATA_DIR / csv_name
        if not filepath.exists():
            logger.debug(f"No data file: {filepath}")
            return {}

        df = pd.read_csv(filepath, parse_dates=["date"])
        df[group_col] = df[group_col].astype(str).str.strip().str.lower()
        df = df.dropna(subset=["date"])

        result = {}
        for name, grp in df.groupby(group_col):
            daily = grp.groupby("date")[value_col].sum().reset_index()
            daily.columns = ["date", "value"]
            daily = daily.sort_values("date").reset_index(drop=True)
            if len(daily) >= self.MIN_DATA_POINTS:
                result[name] = daily
        return result

    def _load_illness_series(self) -> dict:
        return self._load_series("illness_tracking.csv", "illness", "count")

    def _load_items_series(self) -> dict:
        return self._load_series("items_needed.csv", "item", "quantity")

    # ── Feature Engineering ──────────────────────────────────

    def _build_features(self, series_df: pd.DataFrame, weather_df: pd.DataFrame) -> pd.DataFrame:
        """Build feature matrix for one series.

        Features:
        - Lag features: value at t-1, t-3, t-7, t-14, t-21
        - Rolling features: mean/std/sum of value over 7, 14 day windows
        - Calendar: day_of_week, month, day_of_month, is_weekend
        - Weather: temp, humidity, precipitation, rain, windspeed
        - Weather lags: precipitation_lag_7, precipitation_lag_14, humidity_lag_7
        - Weather rolling: temp_rolling_7, precip_rolling_7, humidity_rolling_7
        """
        df = series_df.copy()
        df = df.sort_values("date").reset_index(drop=True)

        # Merge weather
        if not weather_df.empty:
            df = pd.merge(df, weather_df, on="date", how="left")
            # Forward-fill any missing weather
            weather_cols = [c for c in weather_df.columns if c != "date"]
            df[weather_cols] = df[weather_cols].ffill().bfill()
        else:
            weather_cols = []

        # ── Value lags ──
        for lag in [1, 3, 7, 14, 21]:
            df[f"lag_{lag}"] = df["value"].shift(lag)

        # ── Value rolling ──
        for window in [7, 14]:
            df[f"rolling_mean_{window}"] = df["value"].rolling(window, min_periods=1).mean()
            df[f"rolling_std_{window}"] = df["value"].rolling(window, min_periods=1).std().fillna(0)
            df[f"rolling_sum_{window}"] = df["value"].rolling(window, min_periods=1).sum()

        # ── Calendar features ──
        df["day_of_week"] = df["date"].dt.dayofweek
        df["month"] = df["date"].dt.month
        df["day_of_month"] = df["date"].dt.day
        df["is_weekend"] = (df["day_of_week"] >= 5).astype(int)

        # ── Weather lags & rolling ──
        if "precipitation" in df.columns:
            for lag in [7, 14, 21]:
                df[f"precip_lag_{lag}"] = df["precipitation"].shift(lag)
            df["precip_rolling_7"] = df["precipitation"].rolling(7, min_periods=1).mean()
            df["precip_rolling_14"] = df["precipitation"].rolling(14, min_periods=1).sum()

        if "humidity" in df.columns:
            df["humidity_lag_7"] = df["humidity"].shift(7)
            df["humidity_rolling_7"] = df["humidity"].rolling(7, min_periods=1).mean()

        if "temp_mean" in df.columns:
            df["temp_rolling_7"] = df["temp_mean"].rolling(7, min_periods=1).mean()

        # Drop rows with NaN from lagging (first 21 days)
        df = df.dropna().reset_index(drop=True)

        return df

    def _get_feature_cols(self, df: pd.DataFrame) -> list:
        """Return feature column names (everything except date and value)."""
        exclude = {"date", "value"}
        return [c for c in df.columns if c not in exclude]

    # ── Training ─────────────────────────────────────────────

    def _train_lightgbm(self, df: pd.DataFrame, name: str, category: str) -> dict:
        """Train LightGBM model with TimeSeriesSplit CV.

        Args:
            df: Feature-engineered DataFrame with 'date', 'value', and features
            name: Series name (e.g., 'malaria', 'paracetamol')
            category: 'illness' or 'item'

        Returns:
            dict with model, eval metrics, feature importance
        """
        import lightgbm as lgb
        from sklearn.model_selection import TimeSeriesSplit
        from sklearn.metrics import mean_squared_error, mean_absolute_error

        feature_cols = self._get_feature_cols(df)
        X = df[feature_cols].values
        y = df["value"].values

        tscv = TimeSeriesSplit(n_splits=self.N_SPLITS)

        fold_results = []
        best_model = None
        best_rmse = float("inf")

        all_y_true = []
        all_y_pred = []
        fold_indices = []

        for fold_idx, (train_idx, val_idx) in enumerate(tscv.split(X)):
            X_train, X_val = X[train_idx], X[val_idx]
            y_train, y_val = y[train_idx], y[val_idx]

            train_data = lgb.Dataset(X_train, label=y_train)
            val_data = lgb.Dataset(X_val, label=y_val, reference=train_data)

            params = {
                "objective": "regression",
                "metric": "rmse",
                "boosting_type": "gbdt",
                "num_leaves": 31,
                "learning_rate": 0.05,
                "feature_fraction": 0.8,
                "bagging_fraction": 0.8,
                "bagging_freq": 5,
                "verbose": -1,
                "n_jobs": -1,
                "seed": 42,
            }

            callbacks = [lgb.log_evaluation(period=0)]  # suppress output
            model = lgb.train(
                params,
                train_data,
                num_boost_round=500,
                valid_sets=[val_data],
                callbacks=[lgb.early_stopping(50), *callbacks],
            )

            y_pred = model.predict(X_val)
            y_pred = np.maximum(y_pred, 0)  # no negative counts

            rmse = np.sqrt(mean_squared_error(y_val, y_pred))
            mae = mean_absolute_error(y_val, y_pred)

            fold_results.append({
                "fold": fold_idx + 1,
                "train_size": len(train_idx),
                "val_size": len(val_idx),
                "rmse": round(rmse, 3),
                "mae": round(mae, 3),
                "best_iteration": model.best_iteration,
            })

            # Track for plotting
            all_y_true.extend(y_val.tolist())
            all_y_pred.extend(y_pred.tolist())
            fold_indices.extend([fold_idx + 1] * len(val_idx))

            if rmse < best_rmse:
                best_rmse = rmse
                best_model = model

            logger.info(
                f"  {name} fold {fold_idx+1}/{self.N_SPLITS}: "
                f"RMSE={rmse:.3f}, MAE={mae:.3f} "
                f"(train={len(train_idx)}, val={len(val_idx)})"
            )

        # Feature importance
        importance = dict(
            zip(feature_cols, best_model.feature_importance(importance_type="gain"))
        )
        top_features = sorted(importance.items(), key=lambda x: x[1], reverse=True)[:10]

        # Save training plots
        self._save_training_plots(
            name, category, df, feature_cols,
            all_y_true, all_y_pred, fold_indices,
            fold_results, top_features
        )

        avg_rmse = np.mean([f["rmse"] for f in fold_results])
        avg_mae = np.mean([f["mae"] for f in fold_results])

        return {
            "model": best_model,
            "feature_cols": feature_cols,
            "fold_results": fold_results,
            "avg_rmse": round(avg_rmse, 3),
            "avg_mae": round(avg_mae, 3),
            "top_features": [(f, round(v, 2)) for f, v in top_features],
            "data_points": len(df),
        }

    # ── Training Plots ───────────────────────────────────────

    def _save_training_plots(
        self, name, category, df, feature_cols,
        all_y_true, all_y_pred, fold_indices,
        fold_results, top_features
    ):
        """Save matplotlib training performance visualizations."""
        import matplotlib
        matplotlib.use("Agg")  # non-interactive backend
        import matplotlib.pyplot as plt
        import matplotlib.dates as mdates

        safe = self._safe_name(name)
        prefix = f"{category}_{safe}"

        # ── Plot 1: Actual vs Predicted (all folds) ──
        fig, ax = plt.subplots(figsize=(12, 5))
        folds_unique = sorted(set(fold_indices))
        colors = plt.cm.tab10(np.linspace(0, 1, len(folds_unique)))

        for fidx, color in zip(folds_unique, colors):
            mask = [i for i, f in enumerate(fold_indices) if f == fidx]
            y_t = [all_y_true[i] for i in mask]
            y_p = [all_y_pred[i] for i in mask]
            ax.scatter(y_t, y_p, alpha=0.5, s=15, color=color, label=f"Fold {fidx}")

        max_val = max(max(all_y_true), max(all_y_pred)) * 1.1
        ax.plot([0, max_val], [0, max_val], "k--", alpha=0.3, label="Perfect")
        ax.set_xlabel("Actual")
        ax.set_ylabel("Predicted")
        ax.set_title(f"{name.title()} — Actual vs Predicted (5-Fold TS CV)")
        ax.legend(fontsize=8)
        fig.tight_layout()
        fig.savefig(PLOT_DIR / f"{prefix}_actual_vs_pred.png", dpi=120)
        plt.close(fig)

        # ── Plot 2: Feature Importance (top 10) ──
        if top_features:
            fig, ax = plt.subplots(figsize=(10, 5))
            names_list = [f[0] for f in reversed(top_features)]
            vals = [f[1] for f in reversed(top_features)]
            bars = ax.barh(names_list, vals, color="#059669", edgecolor="white")
            ax.set_xlabel("Importance (Gain)")
            ax.set_title(f"{name.title()} — Top Feature Importance")
            fig.tight_layout()
            fig.savefig(PLOT_DIR / f"{prefix}_feature_importance.png", dpi=120)
            plt.close(fig)

        # ── Plot 3: CV Metrics across folds ──
        fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(10, 4))
        folds = [f["fold"] for f in fold_results]
        rmses = [f["rmse"] for f in fold_results]
        maes = [f["mae"] for f in fold_results]

        ax1.bar(folds, rmses, color="#3b82f6", edgecolor="white")
        ax1.set_xlabel("Fold")
        ax1.set_ylabel("RMSE")
        ax1.set_title("RMSE per Fold")

        ax2.bar(folds, maes, color="#f59e0b", edgecolor="white")
        ax2.set_xlabel("Fold")
        ax2.set_ylabel("MAE")
        ax2.set_title("MAE per Fold")

        fig.suptitle(f"{name.title()} — Cross-Validation Metrics", fontweight="bold")
        fig.tight_layout()
        fig.savefig(PLOT_DIR / f"{prefix}_cv_metrics.png", dpi=120)
        plt.close(fig)

        # ── Plot 4: Historical time series + value distribution ──
        fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(14, 4))

        ax1.plot(df["date"], df["value"], linewidth=0.8, color="#6366f1", alpha=0.8)
        ax1.set_xlabel("Date")
        ax1.set_ylabel("Count")
        ax1.set_title(f"{name.title()} — Historical Series")
        ax1.tick_params(axis="x", rotation=30)

        ax2.hist(df["value"], bins=30, color="#10b981", edgecolor="white", alpha=0.8)
        ax2.set_xlabel("Count")
        ax2.set_ylabel("Frequency")
        ax2.set_title("Value Distribution")

        fig.tight_layout()
        fig.savefig(PLOT_DIR / f"{prefix}_history.png", dpi=120)
        plt.close(fig)

        logger.info(f"  Saved 4 training plots for {name}")

    # ── Model I/O ────────────────────────────────────────────

    def _safe_name(self, name: str) -> str:
        return re.sub(r"[^a-z0-9]+", "_", name.lower()).strip("_")

    def _save_model(self, name: str, category: str, model, feature_cols: list):
        """Save LightGBM model + metadata as pickle."""
        safe = self._safe_name(name)
        path = MODEL_DIR / f"{category}_{safe}.pkl"
        with open(path, "wb") as f:
            pickle.dump({"model": model, "feature_cols": feature_cols}, f)
        logger.debug(f"Saved model: {path}")

    def _load_model(self, name: str, category: str):
        """Load LightGBM model + metadata from pickle."""
        safe = self._safe_name(name)
        path = MODEL_DIR / f"{category}_{safe}.pkl"
        if not path.exists():
            return None
        with open(path, "rb") as f:
            return pickle.load(f)

    # ── Training Orchestration ───────────────────────────────

    def train_all_models(self, freq="W", date_start=None, date_end=None) -> dict:
        """Train LightGBM models for all illnesses and items.

        Returns summary dict with evaluation metrics.
        """
        weather_df = self._load_weather()
        illness_series = self._load_illness_series()
        items_series = self._load_items_series()

        summary = {
            "trained_at": datetime.now().isoformat(),
            "method": "LightGBM",
            "n_splits": self.N_SPLITS,
            "illnesses": {},
            "items": {},
        }

        # Train illness models
        logger.info(f"Training {len(illness_series)} illness models...")
        for name, series_df in illness_series.items():
            try:
                df = self._build_features(series_df, weather_df)
                if len(df) < self.MIN_DATA_POINTS:
                    logger.warning(f"Skipping {name}: only {len(df)} points after feature engineering")
                    continue

                result = self._train_lightgbm(df, name, "illness")
                self._save_model(name, "illness", result["model"], result["feature_cols"])

                summary["illnesses"][name] = {
                    "avg_rmse": result["avg_rmse"],
                    "avg_mae": result["avg_mae"],
                    "data_points": result["data_points"],
                    "fold_results": result["fold_results"],
                    "top_features": result["top_features"],
                }
                logger.info(f"  {name}: RMSE={result['avg_rmse']}, MAE={result['avg_mae']}")
            except Exception as e:
                logger.error(f"Failed training illness model {name}: {e}", exc_info=True)
                summary["illnesses"][name] = {"error": str(e)}

        # Train item models
        logger.info(f"Training {len(items_series)} item models...")
        for name, series_df in items_series.items():
            try:
                df = self._build_features(series_df, weather_df)
                if len(df) < self.MIN_DATA_POINTS:
                    logger.warning(f"Skipping {name}: only {len(df)} points")
                    continue

                result = self._train_lightgbm(df, name, "item")
                self._save_model(name, "item", result["model"], result["feature_cols"])

                summary["items"][name] = {
                    "avg_rmse": result["avg_rmse"],
                    "avg_mae": result["avg_mae"],
                    "data_points": result["data_points"],
                    "fold_results": result["fold_results"],
                    "top_features": result["top_features"],
                }
                logger.info(f"  {name}: RMSE={result['avg_rmse']}, MAE={result['avg_mae']}")
            except Exception as e:
                logger.error(f"Failed training item model {name}: {e}", exc_info=True)
                summary["items"][name] = {"error": str(e)}

        # Save summary
        summary_path = MODEL_DIR / "training_summary.json"
        with open(summary_path, "w") as f:
            json.dump(summary, f, indent=2, default=str)

        return summary

    # ── Prediction / Forecasting ─────────────────────────────

    def _predict_future(self, name: str, category: str, days: int = None) -> dict | None:
        """Generate future predictions for a series.

        Uses the last known data + weather forecast to predict next N days.
        Returns dict with dates, predictions, historical data for Chart.js.
        """
        if days is None:
            days = self.FORECAST_HORIZON

        model_data = self._load_model(name, category)
        if model_data is None:
            return None

        model = model_data["model"]
        feature_cols = model_data["feature_cols"]

        # Load historical data
        weather_df = self._load_weather()
        csv_name = "illness_tracking.csv" if category == "illness" else "items_needed.csv"
        group_col = "illness" if category == "illness" else "item"
        value_col = "count" if category == "illness" else "quantity"
        all_series = self._load_series(csv_name, group_col, value_col)

        if name not in all_series:
            return None

        series_df = all_series[name]

        # Build features for historical data
        df = self._build_features(series_df, weather_df)
        if df.empty:
            return None

        # For future prediction, we extend the DataFrame day by day
        last_date = df["date"].max()
        last_values = df["value"].tail(30).tolist()  # keep recent history for lags

        # Try to get weather forecast
        future_weather = self._get_future_weather(days)

        predictions = []
        pred_dates = []

        # Create a working copy of recent data for rolling predictions
        working_df = df.copy()

        for i in range(days):
            next_date = last_date + timedelta(days=i + 1)
            pred_dates.append(next_date)

            # Build a single-row feature set
            row = self._build_single_row_features(
                working_df, next_date, future_weather, feature_cols
            )

            if row is not None:
                pred = model.predict(row.reshape(1, -1))[0]
                pred = max(0, round(pred, 1))
            else:
                # Fallback: use recent average
                pred = round(np.mean(last_values[-7:]), 1) if last_values else 0

            predictions.append(pred)

            # Add prediction to working_df for next iteration's lags
            new_row = {"date": next_date, "value": pred}
            # Add weather if available
            date_str = next_date.strftime("%Y-%m-%d")
            if future_weather and date_str in future_weather:
                new_row.update(future_weather[date_str])
            new_entry = pd.DataFrame([new_row])
            working_df = pd.concat([working_df, new_entry], ignore_index=True)

        # Build Chart.js-ready payload
        # Historical: last 60 days
        hist_df = df.tail(60)
        historical_dates = [d.strftime("%Y-%m-%d") for d in hist_df["date"]]
        historical_values = hist_df["value"].tolist()

        forecast_dates = [d.strftime("%Y-%m-%d") for d in pred_dates]

        return {
            "name": name,
            "category": category,
            "historical": {
                "dates": historical_dates,
                "values": historical_values,
            },
            "forecast": {
                "dates": forecast_dates,
                "values": predictions,
            },
        }

    def _build_single_row_features(
        self, working_df, target_date, future_weather, feature_cols
    ) -> np.ndarray | None:
        """Build feature vector for a single future date."""
        try:
            n = len(working_df)
            features = {}

            # Lag features from working_df
            for lag in [1, 3, 7, 14, 21]:
                idx = n - lag
                features[f"lag_{lag}"] = working_df["value"].iloc[idx] if idx >= 0 else 0

            # Rolling features
            for window in [7, 14]:
                recent = working_df["value"].tail(window)
                features[f"rolling_mean_{window}"] = recent.mean()
                features[f"rolling_std_{window}"] = recent.std() if len(recent) > 1 else 0
                features[f"rolling_sum_{window}"] = recent.sum()

            # Calendar
            features["day_of_week"] = target_date.weekday()
            features["month"] = target_date.month
            features["day_of_month"] = target_date.day
            features["is_weekend"] = 1 if target_date.weekday() >= 5 else 0

            # Weather features
            date_str = target_date.strftime("%Y-%m-%d")
            if future_weather and date_str in future_weather:
                w = future_weather[date_str]
                for k, v in w.items():
                    features[k] = v

            # Weather from working_df columns
            weather_cols_in_df = ["temp_max", "temp_min", "temp_mean", "humidity",
                                  "precipitation", "rain", "windspeed"]
            for col in weather_cols_in_df:
                if col not in features and col in working_df.columns:
                    features[col] = working_df[col].iloc[-1]

            # Weather lags and rolling
            if "precipitation" in working_df.columns:
                for lag in [7, 14, 21]:
                    idx = n - lag
                    features[f"precip_lag_{lag}"] = (
                        working_df["precipitation"].iloc[idx] if idx >= 0 else 0
                    )
                features["precip_rolling_7"] = working_df["precipitation"].tail(7).mean()
                features["precip_rolling_14"] = working_df["precipitation"].tail(14).sum()

            if "humidity" in working_df.columns:
                idx7 = n - 7
                features["humidity_lag_7"] = (
                    working_df["humidity"].iloc[idx7] if idx7 >= 0 else 80
                )
                features["humidity_rolling_7"] = working_df["humidity"].tail(7).mean()

            if "temp_mean" in working_df.columns:
                features["temp_rolling_7"] = working_df["temp_mean"].tail(7).mean()

            # Build array in correct column order
            row = np.array([features.get(col, 0) for col in feature_cols], dtype=np.float64)
            return row

        except Exception as e:
            logger.warning(f"Feature build failed for {target_date}: {e}")
            return None

    def _get_future_weather(self, days: int) -> dict | None:
        """Try to fetch weather forecast for future dates."""
        try:
            from core.models import VillageProfile
            vp = VillageProfile.objects.filter(pk=1).first()
            if not vp or not vp.latitude or not vp.longitude:
                return None

            from services.weather_service import get_weather_for_forecast
            data = get_weather_for_forecast(vp.latitude, vp.longitude, days=days)
            if not data or "time" not in data:
                return None

            result = {}
            times = data["time"]
            for i, d in enumerate(times):
                result[d] = {
                    "temp_max": data.get("temperature_2m_max", [30] * len(times))[i] or 30,
                    "temp_min": data.get("temperature_2m_min", [24] * len(times))[i] or 24,
                    "temp_mean": data.get("temperature_2m_mean", [27] * len(times))[i] or 27,
                    "humidity": data.get("relative_humidity_2m_mean", [80] * len(times))[i] or 80,
                    "precipitation": data.get("precipitation_sum", [0] * len(times))[i] or 0,
                    "rain": data.get("rain_sum", [0] * len(times))[i] or 0,
                    "windspeed": data.get("windspeed_10m_max", [5] * len(times))[i] or 5,
                }
            return result
        except Exception as e:
            logger.debug(f"Future weather fetch failed: {e}")
            return None

    # ── Public API ───────────────────────────────────────────

    def has_trained_models(self) -> bool:
        """Check if any trained models exist."""
        return any(MODEL_DIR.glob("*.pkl"))

    def get_training_summary(self) -> dict | None:
        """Load training summary from JSON."""
        path = MODEL_DIR / "training_summary.json"
        if not path.exists():
            return None
        with open(path) as f:
            return json.load(f)

    def get_training_plots(self, name: str = None, category: str = None) -> list:
        """Get list of training plot file paths.

        If name/category given, filter to that model.
        Returns list of dicts with 'path', 'filename', 'type'.
        """
        plots = []
        for p in sorted(PLOT_DIR.glob("*.png")):
            fname = p.name
            plot_info = {
                "path": str(p),
                "filename": fname,
                "url": f"/static/training_plots/{fname}",
            }
            if name and category:
                safe = self._safe_name(name)
                prefix = f"{category}_{safe}_"
                if not fname.startswith(prefix):
                    continue
            plots.append(plot_info)
        return plots

    def get_forecasts(self, category: str = "illness") -> dict:
        """Get forecasts for all trained models of a category.

        Returns Chart.js-ready data structure.
        """
        csv_name = "illness_tracking.csv" if category == "illness" else "items_needed.csv"
        group_col = "illness" if category == "illness" else "item"
        value_col = "count" if category == "illness" else "quantity"

        all_series = self._load_series(csv_name, group_col, value_col)
        results = {}

        for name in all_series:
            forecast = self._predict_future(name, category)
            if forecast:
                results[name] = forecast

        return results

    def get_top_illnesses(self, n: int = 10) -> list:
        """Get top N illnesses by total count from CSV."""
        filepath = DATA_DIR / "illness_tracking.csv"
        if not filepath.exists():
            return []
        df = pd.read_csv(filepath)
        df["illness"] = df["illness"].astype(str).str.strip().str.lower()
        agg = df.groupby("illness")["count"].sum().sort_values(ascending=False).head(n)
        return [{"name": name.title(), "count": int(cnt)} for name, cnt in agg.items()]

    def get_top_items(self, n: int = 5) -> list:
        """Get top N items by total quantity from CSV."""
        filepath = DATA_DIR / "items_needed.csv"
        if not filepath.exists():
            return []
        df = pd.read_csv(filepath)
        df["item"] = df["item"].astype(str).str.strip().str.lower()
        agg = df.groupby("item")["quantity"].sum().sort_values(ascending=False).head(n)
        return [{"name": name.title(), "quantity": int(qty)} for name, qty in agg.items()]

    def get_visualization_data(self) -> dict:
        """Get comprehensive visualization data for the epidemiology page."""
        illness_forecasts = self.get_forecasts("illness")
        item_forecasts = self.get_forecasts("item")
        summary = self.get_training_summary()

        return {
            "illness_forecasts": illness_forecasts,
            "item_forecasts": item_forecasts,
            "training_summary": summary,
            "has_models": self.has_trained_models(),
        }
