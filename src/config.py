
from pathlib import Path
import yaml

ROOT = Path(__file__).resolve().parent

def get_config() -> tuple[float, float, float, float, float]:
    with (ROOT / "config.yaml").open(encoding="utf-8") as file:
        config = yaml.safe_load(file)
    try:
        centre = config["area"]["center"]
        size = config["area"]["size"]
        return (
            float(centre["lat"]),
            float(centre["lng"]),
            float(size["width"]),
            float(size["height"]),
            float(config["heightmap"]["resolution"]),
        )
    except (KeyError, TypeError, ValueError) as error:
        raise ValueError("config.yaml must define area.center, area.size, and heightmap.resolution") from error
