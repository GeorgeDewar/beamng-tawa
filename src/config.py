
from pathlib import Path
import yaml

ROOT = Path(__file__).resolve().parent.parent

class Config:
    def __init__(self, config_path: Path = ROOT / "config.yaml"):
        with config_path.open(encoding="utf-8") as file:
            self._config_data = yaml.safe_load(file)

    @property
    def data(self) -> dict:
        return self._config_data

    def get_area_center(self) -> tuple[float, float]:
        center = self._config_data["area"]["center"]
        return float(center["lat"]), float(center["lng"])

    def get_area_size(self) -> tuple[float, float]:
        size = self._config_data["area"]["size"]
        return float(size["width"]), float(size["height"])


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

def get_config_raw() -> dict:
    with (ROOT / "config.yaml").open(encoding="utf-8") as file:
        config = yaml.safe_load(file)
    return config
