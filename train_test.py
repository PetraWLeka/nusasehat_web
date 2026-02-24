"""Quick script to train LightGBM forecast models and show results."""
import os
os.environ['DJANGO_SETTINGS_MODULE'] = 'nusahealth_cloud.settings'
import django
django.setup()

from services.forecast_service import ForecastService

fs = ForecastService()

print("=" * 60)
print("TRAINING LIGHTGBM MODELS")
print("=" * 60)
results = fs.train_all_models()

print(f"\nItems trained: {len([k for k, v in results['items'].items() if 'avg_rmse' in v])}")
print(f"Illnesses trained: {len([k for k, v in results['illnesses'].items() if 'avg_rmse' in v])}")

print("\n--- Illnesses ---")
for k, v in results['illnesses'].items():
    print(f"  {k}: pts={v.get('data_points',0)}, RMSE={v.get('avg_rmse','N/A')}, MAE={v.get('avg_mae','N/A')}")

print("\n--- Items ---")
for k, v in results['items'].items():
    print(f"  {k}: pts={v.get('data_points',0)}, RMSE={v.get('avg_rmse','N/A')}, MAE={v.get('avg_mae','N/A')}")

print("\n" + "=" * 60)
print("GENERATING FORECASTS (next 14 days)")
print("=" * 60)
illness_fc = fs.get_forecasts("illness")
item_fc = fs.get_forecasts("item")

print(f"\nIllnesses with forecasts: {len(illness_fc)}")
for name, data in list(illness_fc.items())[:3]:
    vals = data.get("forecast", {}).get("values", [])[:4]
    print(f"  {name}: next 4 days → {vals}")

print(f"\nItems with forecasts: {len(item_fc)}")
for name, data in list(item_fc.items())[:3]:
    vals = data.get("forecast", {}).get("values", [])[:4]
    print(f"  {name}: next 4 days → {vals}")

print("\n" + "=" * 60)
print("TOP ILLNESSES & ITEMS")
print("=" * 60)
print("\nTop illnesses:")
for t in fs.get_top_illnesses(n=5):
    print(f"  {t['name']}: {t['count']} cases")
print("\nTop items:")
for t in fs.get_top_items(n=5):
    print(f"  {t['name']}: {t['quantity']} units")

print("\nDone!")
