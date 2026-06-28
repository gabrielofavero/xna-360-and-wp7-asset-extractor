# XNA Asset Extractor for Xbox 360 and Windows Phone 7 (.xap)

## Overview

I've made this tool to ease the preparation process of Xbox 360 and Windows Phone 7 XNA game assets, so that we can use them with FNA / MonoGame.

In most cases, just extracting the assets is enough, but I've added a conversion stage if you want to handle the raw assets directly. I always recommend converting the xnbs because even if it means messing with the code more to read them raw, you now have assets you can modify directly.

### 1. Extract

Takes a packaged game (`.xap` or Xbox 360 STFS archive) and unpacks it into a plain folder structure. If your game is already extracted, you can point directly to its folder and this step is skipped.

### 2. Convert

Processes the raw XNA assets so they work better with FNA (this is very useful for 360 indies):

- **`.xnb` files** → decompiled back into standard formats (`.png`, `.wav`, `.xml`, etc.)
- **`.wma` audio** → converted to `.ogg` (requires [ffmpeg](https://ffmpeg.org/))

You can ignore specific files (like fonts) if you don't want them converted.

### 3. Output

Assembles the final folder for your project:

- Merges extracted and converted assets together
- Moves folders into a clean `Content/` structure
- Removes leftover `.xnb`/`.wma` originals that already have converted versions
- Optionally deletes intermediate `extracted/`, `decompressed/` and `converted/` folders

---

Built on top of [xnb_parse](https://github.com/fesh0r/xnb_parse) by Andrew McRae and [XBLA-Extract](https://github.com/ryzendew/XBLA-Extract) by ryzendew. Thanks!

## Setup

```bash
# Clone with submodules
git clone --recurse-submodules <repo-url>

# Or if you already cloned without:
git submodule update --init --recursive
```

## Configuration

A JSON config is the recommended approach when you want to embed this tool in a repo alongside your game's source code. It lets contributors or downstream users get a working `Content/` folder with a single command, so no need to hunt down packages, remember CLI flags, or run multiple steps by hand. The config also supports multiple games at once.

Copy `config-example.json` and edit it for your game:

```jsonc
{
    "content": {
        "my-game": {                         // put any game id you wish
            "type": "package",               // "game-dir" | "package" | "content-dir"
            "asset-type": "360",             // "XAP" | "360" (only for type=package)
            "src": "./my-game"               // path relative to where you run the script
        }
    },
    "convert": {
        "enabled": true,
        "content": {                         // you can leave an empty object if you wish the default config
            "my-game": {
                "convert-wma-to-ogg": true,
                "only-decompress": false,     // set true to skip XNB conversion (keep .xnb files)
                "ignore": []
            }
        }
    },
    "output": {
        "enabled": true,
        "delete-extracted-dir": false,
        "delete-decompressed-dir": false,
        "delete-converted-dir": false,
        "content": {                         // you can leave an empty object if you wish the default config
            "my-game": {
                "enabled": true,
                "move-to-Content": [],      // move things from game dir root into Content
                "copy-to-content": [],      // copies things from CWD-relative path into Content
                "keep-only-content": true   // Deletes everything from output/my-game except for Content dir
            }
        }
    }
}
```

## Run

### Full pipeline (config file)

```bash
python asset-extractor.py config my-config.json
```

Output lands in `output/<game-id>/`. The pipeline runs in order:

1. Extract content → `extracted/<game-id>/`
2. Decompress `.xnb` files → `decompressed/<game-id>/`
3. Convert `.xnb` files → `converted/<game-id>/`  (skip via `"only-decompress": true` to keep raw .xnb)
4. Convert `.wma` → `.ogg` (requires [ffmpeg](https://ffmpeg.org/))
5. Assemble final output → `output/<game-id>/`
6. Post-process (`move-to-Content`, `copy-to-content`, `keep-only-content`)

**Post-process options:**

- `move-to-Content` — list of paths inside the game output to move into `Content/`. Use `../` prefix for paths outside the game root (copied instead of moved).
- `copy-to-content` — list of CWD-relative paths to copy into `Content/` (destination keeps the source's basename). Useful for pulling in project files (fonts, manifests) that weren't part of the extracted package.
- `keep-only-content` — when `true`, deletes everything outside `Content/` in the output folder.

### Individual steps (CLI)

You can also run each step on its own without a config file:

```bash
# Extract a package
python asset-extractor.py extract-360 ./game.pirs --output extracted
python asset-extractor.py extract-xap ./game.xap -o extracted

# Decompress .xnb files only (no conversion)
python asset-extractor.py decompress ./Content --output decompressed

# Convert .xnb files (and optionally .wma)
python asset-extractor.py convert ./Content --output converted
python asset-extractor.py convert ./Content -o converted --ignore "Arial.xnb" "Font.xnb" --wma-to-ogg

# Assemble final output folder
python asset-extractor.py assemble ./extracted ./converted --output ./my-game
```

Run with no arguments to see all available commands:

```bash
python asset-extractor.py --help
```

## License

MIT — do whatever you want with this code.
