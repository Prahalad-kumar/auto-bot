"""Import the repository strategy configuration into the local database."""
import json
from pathlib import Path

from app.db.session import SessionLocal
from app.models import Strategy


config_path = Path("/config/strategy.json")
if not config_path.exists():
    config_path = Path(__file__).resolve().parents[2] / "config" / "strategy.json"
config = json.loads(config_path.read_text())
db = SessionLocal()
try:
    strategy = db.query(Strategy).filter(Strategy.name == config["name"]).first()
    if strategy:
        strategy.config = config
        strategy.enabled = False
        print(f"Updated paper strategy: {strategy.name}")
    else:
        db.add(Strategy(name=config["name"], config=config, enabled=False))
        print(f"Imported paper strategy: {config['name']}")
    db.commit()
finally:
    db.close()
