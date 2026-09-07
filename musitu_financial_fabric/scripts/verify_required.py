from pathlib import Path
import json

manifest = json.loads((Path(__file__).resolve().parents[1] / "stack" / "required-components.json").read_text())
assert manifest["all_required"] is True
assert len(manifest["components"]) == 39
assert all(component["required"] is True for component in manifest["components"])
print("PASS: 39 mandatory MUSITU Financial Fabric components are declared required")
