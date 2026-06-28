# XNA to FNA asset extractor

## Overview

I've created this tool to ease the process of extracting and converting assets from old Xbox 360 Indie games or Windows Phone XAP files. I didn't considered PC ports as we have many good tools already.

I'm using some submodules to get things done. so thank you the original devs for the implementation!

## Setup

```bash
# Clone with submodules
git clone --recurse-submodules <repo-url>

# Or if you already cloned without:
git submodule update --init --recursive
```

## Configuration

Copy `config-example.json` and edit it for your game:

```jsonc
{
    "content": {
        "my-game": {
            "type": "package",        // "game-dir" | "package" | "content-dir"
            "asset-type": "360",      // "XAP" | "360" (only for type=package)
            "src": "./my-game"        // path relative to where you run the script
        }
    },
    "convert": {
        "my-game": {
            "convert-wma-to-ogg": true,
            "ignore": ["SomeFile.xnb"]
        }
    },
    "output": {
        "enabled": true,
        "delete-extracted-dir": false,
        "delete-converted-dir": false,
        "my-game": {
            "enabled": true,
            "move-to-Content": ["chardef/"],
            "keep-only-content": true
        }
    }
}
```

| `type`              | Behavior                                      |
| --------------------- | --------------------------------------------- |
| `game-dir`          | Already extracted — source is used as-is     |
| `content-dir`       | Just a Content folder — no extraction needed |
| `package` + `XAP` | Renames`.xap` → `.zip` and extracts      |
| `package` + `360` | Extracts via STFS (Xbox 360 LIVE/PIRS/CON)    |

## Run

```bash
python asset-extractor.py my-config.json
```

Output lands in `output/<game-id>/`. The pipeline runs in order:

1. Extract content → `extracted/<game-id>/`
2. Convert `.xnb` files → `converted/<game-id>/`
3. Convert `.wma` → `.ogg` (requires [ffmpeg](https://ffmpeg.org/))
4. Assemble final output → `output/<game-id>/`
5. Post-process (`move-to-Content`, `keep-only-content`)
