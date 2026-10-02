import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from app.circuit import generate

if __name__ == "__main__":
    generate(ROOT / "examples")
    print("Created two synthetic .s2p files and examples/model.json")
