"""
Generic Config-Driven Asset Extractor for XNA-to-FNA conversion.

Usage:
    python asset-extractor.py config-name.json

Reads a JSON config file that specifies content sources, conversion rules,
and output assembly for one or more games.
"""

from __future__ import print_function

import argparse
import fnmatch
import json
import os
import shutil
import subprocess
import sys
import zipfile

# ---------------------------------------------------------------------------
# Path setup: add sibling directories to sys.path so we can import from them
# ---------------------------------------------------------------------------
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))

XBLA_EXTRACT_DIR = os.path.join(SCRIPT_DIR, "xbla-extract")
XNB_PARSE_DIR = os.path.join(SCRIPT_DIR, "xnb_parse")

if XBLA_EXTRACT_DIR not in sys.path:
    sys.path.insert(0, XBLA_EXTRACT_DIR)

if XNB_PARSE_DIR not in sys.path:
    sys.path.insert(0, XNB_PARSE_DIR)

# Late imports so path setup happens first
from stfs_extract import extract_live_pirs  # noqa: E402
from xnb_parse.read_xnb_dir import read_xnb_dir  # noqa: E402


# ---------------------------------------------------------------------------
# Defaults
# ---------------------------------------------------------------------------
DEFAULT_CONVERT_WMA_TO_OGG = True
DEFAULT_IGNORE_LIST = []


# ---------------------------------------------------------------------------
# Validation helpers
# ---------------------------------------------------------------------------
def die(msg, code=1):
    """Print an error message and exit."""
    print("ERROR:", msg, file=sys.stderr)
    sys.exit(code)


# ---------------------------------------------------------------------------
# Config loading
# ---------------------------------------------------------------------------
def load_config(config_path):
    """Load and validate the JSON config file.  Returns the parsed dict."""
    if not os.path.isfile(config_path):
        die("Config file not found: '{}'".format(config_path))

    with open(config_path, "r", encoding="utf-8") as fh:
        try:
            cfg = json.load(fh)
        except json.JSONDecodeError as ex:
            die("Invalid JSON in config file '{}': {}".format(config_path, ex))

    if "content" not in cfg:
        die("Config file must have a 'content' section.")

    if not cfg["content"]:
        print("Config 'content' section is empty – nothing to process.")
        sys.exit(0)

    # Validate each content entry
    valid_types = {"game-dir", "package", "content-dir"}
    for game_id, entry in cfg["content"].items():
        if "type" not in entry or entry["type"] not in valid_types:
            die("content['{}']: 'type' must be one of {}.".format(
                game_id, sorted(valid_types)))
        if entry["type"] == "package":
            if "asset-type" not in entry or entry["asset-type"] not in ("XAP", "360"):
                die("content['{}']: package entries require 'asset-type' "
                    "to be 'XAP' or '360'.".format(game_id))
        if "src" not in entry:
            die("content['{}']: missing required 'src' field.".format(game_id))

    return cfg


# ---------------------------------------------------------------------------
# Per-game convert settings helper
# ---------------------------------------------------------------------------
def get_convert_settings(cfg, game_id):
    """Return (convert_wma_to_ogg, ignore_list) for a game, applying defaults."""
    game_convert = cfg.get("convert", {}).get("content", {}).get(game_id, {})
    wma = game_convert.get("convert-wma-to-ogg", DEFAULT_CONVERT_WMA_TO_OGG)
    ignore = game_convert.get("ignore", list(DEFAULT_IGNORE_LIST))
    return wma, ignore


# ---------------------------------------------------------------------------
# Pre-flight check: ffmpeg
# ---------------------------------------------------------------------------
def check_ffmpeg():
    """Check that ffmpeg is available.  Exit if not."""
    try:
        subprocess.check_call(
            ["ffmpeg", "-version"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
    except Exception:
        die("ffmpeg is required for WMA-to-OGG conversion but was not found "
            "on PATH. Install ffmpeg or set 'convert-wma-to-ogg': false for "
            "all games.")


# ---------------------------------------------------------------------------
# 2. Content Extraction
# ---------------------------------------------------------------------------
def extract_content(cfg):
    """
    For every game-id in the config, populate extracted/<game-id>/.

    Returns a dict: game_id -> content_type.
    """
    content_types = {}

    for game_id, entry in cfg["content"].items():
        ctype = entry["type"]
        content_types[game_id] = ctype
        dest = os.path.join("extracted", game_id)

        if ctype in ("game-dir", "content-dir"):
            src = entry["src"]
            if not os.path.isdir(src):
                die("content['{}']: source directory not found: '{}'".format(
                    game_id, src))
            print("[{}] Using existing directory: {}".format(game_id, src))
            # No extraction needed – the source *is* the extracted content.
            # We work with src directly later, but for consistency we can also
            # copy/symlink.  The plan says "Already extracted. Source = src path.
            # No extraction needed." so we just remember the src path.
            # However, the output assembly step copies from extracted/<game-id>/,
            # so for game-dir / content-dir we need to make sure extracted/ has
            # a copy (or we adjust the assembly logic).  To keep things uniform,
            # we copy the source into extracted/ dir.
            if os.path.abspath(src) != os.path.abspath(dest):
                print("[{}] Copying {} -> {}".format(game_id, src, dest))
                if os.path.exists(dest):
                    shutil.rmtree(dest)
                if ctype == "game-dir":
                    shutil.copytree(src, dest)
                else:
                    # content-dir: we copy the Content dir into dest/Content/
                    dest_content = os.path.join(dest, "Content")
                    os.makedirs(dest_content, exist_ok=True)
                    shutil.copytree(src, dest_content, dirs_exist_ok=True)

        elif ctype == "package":
            os.makedirs(dest, exist_ok=True)
            src = entry["src"]
            asset_type = entry["asset-type"]

            # src may be a glob.  Resolve to the first matching file.
            import glob
            matches = glob.glob(src)
            if not matches:
                die("content['{}']: no files matched glob '{}'.".format(
                    game_id, src))
            pkg_path = matches[0]

            if asset_type == "XAP":
                print("[{}] Extracting XAP package: {}".format(game_id, pkg_path))
                _extract_xap(pkg_path, dest)
            elif asset_type == "360":
                print("[{}] Extracting 360 STFS package: {}".format(game_id, pkg_path))
                extract_live_pirs(pkg_path, dest)

    return content_types


def _extract_xap(xap_path, dest_dir):
    """Copy .xap → rename to .zip → extract → delete temp .zip."""
    temp_zip = os.path.join(dest_dir, "_temp.zip")
    shutil.copy2(xap_path, temp_zip)
    try:
        with zipfile.ZipFile(temp_zip, "r") as zf:
            zf.extractall(dest_dir)
        print("    Extracted {} file(s) from XAP.".format(
            len(zf.namelist())))
    finally:
        if os.path.isfile(temp_zip):
            os.remove(temp_zip)


# ---------------------------------------------------------------------------
# Helper: find files by extension
# ---------------------------------------------------------------------------
def find_files_by_ext(root_dir, ext):
    """Yield relative paths (from root_dir) of files ending with *ext*."""
    if not os.path.isdir(root_dir):
        return
    for dirpath, _, filenames in os.walk(root_dir):
        for fname in filenames:
            if fname.lower().endswith(ext.lower()):
                full = os.path.join(dirpath, fname)
                yield os.path.relpath(full, root_dir)


def _is_ignored(rel_path, ignore_list):
    """Check whether a relative path matches any ignore pattern."""
    # Normalize to forward slashes for matching
    normalized = rel_path.replace(os.sep, "/")
    for pattern in ignore_list:
        p = pattern.replace(os.sep, "/")
        if fnmatch.fnmatch(normalized, p) or fnmatch.fnmatch(
                os.path.basename(normalized), p):
            return True
    return False


# ---------------------------------------------------------------------------
# 4. XNB Conversion
# ---------------------------------------------------------------------------
def convert_xnb(cfg):
    """
    For each game listed in config['convert'], scan extracted/<game>/Content/
    for .xnb files, skip ignored, and call read_xnb_dir.
    """
    convert_section = cfg.get("convert", {})
    if not convert_section.get("enabled", True):
        print("XNB conversion disabled. Skipping.")
        return

    for game_id in convert_section.get("content", {}):
        content_dir = os.path.join("extracted", game_id, "Content")
        if not os.path.isdir(content_dir):
            print("[{}] WARNING: Content dir not found: '{}'. Skipping XNB "
                  "conversion.".format(game_id, content_dir))
            continue

        _, ignore_list = get_convert_settings(cfg, game_id)

        # Check if all .xnb files are ignored
        xnb_files = list(find_files_by_ext(content_dir, ".xnb"))
        active_xnbs = [f for f in xnb_files if not _is_ignored(f, ignore_list)]

        if not active_xnbs:
            print("[{}] No .xnb files to convert (all ignored or none found)."
                  .format(game_id))
            continue

        print("[{}] Converting {} .xnb file(s)...".format(game_id, len(active_xnbs)))

        export_dir = os.path.join("converted", game_id)
        read_xnb_dir(content_dir, export_dir)

        # Delete converted outputs for ignored .xnb files
        ignored_xnbs = [f for f in xnb_files if _is_ignored(f, ignore_list)]
        if ignored_xnbs and os.path.isdir(export_dir):
            print("[{}] Cleaning up {} ignored .xnb(s) from converted..."
                  .format(game_id, len(ignored_xnbs)))
            for xnb_rel in ignored_xnbs:
                base = os.path.splitext(xnb_rel)[0]
                base_name = os.path.basename(base)
                # Remove any converted file(s) in export_dir with same basename
                for dirpath, _, filenames in os.walk(export_dir):
                    for fname in list(filenames):
                        fbase = os.path.splitext(fname)[0]
                        if fbase == base_name:
                            fpath = os.path.join(dirpath, fname)
                            print("    Removing ignored converted: {}".format(
                                os.path.relpath(fpath, export_dir)))
                            os.remove(fpath)


# ---------------------------------------------------------------------------
# 5. WMA → OGG Conversion
# ---------------------------------------------------------------------------
def convert_wma_to_ogg(cfg):
    """
    Scan extracted/<game>/Content/ AND converted/<game>/ for .wma files,
    skip ignored, and convert to .ogg with ffmpeg.
    """
    convert_section = cfg.get("convert", {})
    if not convert_section.get("enabled", True):
        print("WMA conversion disabled. Skipping.")
        return

    for game_id in convert_section.get("content", {}):
        wma_enabled, ignore_list = get_convert_settings(cfg, game_id)
        if not wma_enabled:
            continue

        wma_files = []
        # Scan extracted Content
        ext_content = os.path.join("extracted", game_id, "Content")
        if os.path.isdir(ext_content):
            for rel in find_files_by_ext(ext_content, ".wma"):
                wma_files.append(("extracted", os.path.join(ext_content, rel), rel))

        # Scan converted
        conv_dir = os.path.join("converted", game_id)
        if os.path.isdir(conv_dir):
            for rel in find_files_by_ext(conv_dir, ".wma"):
                wma_files.append(("converted", os.path.join(conv_dir, rel), rel))

        # Filter ignored
        active = [(src_root, full, rel) for src_root, full, rel in wma_files
                  if not _is_ignored(rel, ignore_list)]

        if not active:
            continue

        print("[{}] Converting {} .wma file(s) to .ogg...".format(
            game_id, len(active)))

        for src_root, full_path, rel in active:
            # Output goes to converted/<game>/ with .ogg extension
            ogg_rel = os.path.splitext(rel)[0] + ".ogg"
            ogg_path = os.path.join("converted", game_id, ogg_rel)
            ogg_dir = os.path.dirname(ogg_path)
            if ogg_dir:
                os.makedirs(ogg_dir, exist_ok=True)

            print("    {} -> {}".format(rel, ogg_rel))
            subprocess.check_call([
                "ffmpeg", "-y",
                "-i", full_path,
                "-c:a", "libvorbis",
                "-q:a", "6",
                ogg_path,
            ], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


# ---------------------------------------------------------------------------
# 6. Output Assembly
# ---------------------------------------------------------------------------
def assemble_output(cfg, content_types):
    """
    For each game-id that has output enabled, build output/<game-id>/.
    """
    output_cfg = cfg.get("output", {})
    if not output_cfg.get("enabled", True):
        print("Output assembly disabled globally. Skipping.")
        return

    for game_id, ctype in content_types.items():
        game_output = output_cfg.get("content", {}).get(game_id, {})
        if not game_output.get("enabled", True):
            print("[{}] Output disabled. Skipping.".format(game_id))
            continue

        out_dir = os.path.join("output", game_id)
        ext_dir = os.path.join("extracted", game_id)
        conv_dir = os.path.join("converted", game_id)

        # Clean output dir
        if os.path.exists(out_dir):
            shutil.rmtree(out_dir)
        os.makedirs(out_dir)

        # Copy extracted content
        if ctype in ("package", "game-dir"):
            print("[{}] Copying extracted content -> output...".format(game_id))
            _copytree_merge(ext_dir, out_dir)
        elif ctype == "content-dir":
            # Only copy contents into output/<game>/Content/
            out_content = os.path.join(out_dir, "Content")
            os.makedirs(out_content, exist_ok=True)
            src_content = os.path.join(ext_dir, "Content")
            if os.path.isdir(src_content):
                print("[{}] Copying Content dir -> output...".format(game_id))
                _copytree_merge(src_content, out_content)

        # Copy converted files over the top (overwriting)
        if os.path.isdir(conv_dir):
            out_content = os.path.join(out_dir, "Content")
            print("[{}] Merging converted assets -> output...".format(game_id))
            _copytree_merge(conv_dir, out_content)

        # Clean up .xnb and .wma that have converted counterparts
        _cleanup_converted_originals(out_dir, game_id, cfg)


def _copytree_merge(src, dst):
    """Copy src tree into dst, merging directories and overwriting files."""
    for dirpath, _, filenames in os.walk(src):
        rel = os.path.relpath(dirpath, src)
        target_dir = os.path.join(dst, rel) if rel != "." else dst
        os.makedirs(target_dir, exist_ok=True)
        for fname in filenames:
            shutil.copy2(os.path.join(dirpath, fname),
                         os.path.join(target_dir, fname))


def _cleanup_converted_originals(out_dir, game_id, cfg):
    """
    Delete .xnb and .wma files from output/<game>/Content/ that have a
    converted counterpart (e.g., asset.xnb deleted if asset.wav/asset.png
    exists).  Ignored files are kept.
    """
    _, ignore_list = get_convert_settings(cfg, game_id)
    out_content = os.path.join(out_dir, "Content")
    if not os.path.isdir(out_content):
        return

    # Build set of converted output extensions (what .xnb becomes after export)
    # Common XNB conversions: .png, .wav, .ogg, .wma, .xml, .fxb, .spritefont, etc.
    converted_extensions = {
        ".png", ".wav", ".ogg", ".wma", ".xml", ".fxb", ".spritefont",
        ".bmp", ".jpg", ".jpeg", ".tga", ".dds",
    }

    # Walk the output Content and find .xnb/.wma files
    for dirpath, _, filenames in os.walk(out_content):
        for fname in filenames:
            full = os.path.join(dirpath, fname)
            rel = os.path.relpath(full, out_content)

            if _is_ignored(rel, ignore_list):
                continue

            base, ext = os.path.splitext(fname)
            ext_lower = ext.lower()

            if ext_lower not in (".xnb", ".wma"):
                continue

            # Check if any converted counterpart exists (same name, different ext)
            has_counterpart = False
            for other in filenames:
                other_base, other_ext = os.path.splitext(other)
                if other_base == base and other_ext.lower() in converted_extensions:
                    has_counterpart = True
                    break

            if has_counterpart:
                print("    Removing original: {}".format(rel))
                os.remove(full)


# ---------------------------------------------------------------------------
# 7. Post-Output Adjustments
# ---------------------------------------------------------------------------
def post_output_adjustments(cfg):
    """
    Per game-id:
      - move-to-Content[]: move/copy paths into Content/
      - copy-to-content[]: copy external files (CWD-relative) into Content/
      - keep-only-content: delete everything outside Content/
    """
    output_cfg = cfg.get("output", {})

    for game_id, game_output in output_cfg.get("content", {}).items():
        out_dir = os.path.join("output", game_id)
        out_content = os.path.join(out_dir, "Content")

        if not os.path.isdir(out_dir):
            continue

        # move-to-Content
        move_list = game_output.get("move-to-Content", [])
        for item in move_list:
            item = item.replace("\\", "/").rstrip("/")
            if item.startswith("../"):
                # Outside game root – copy into Content
                src_path = os.path.normpath(os.path.join(out_dir, item))
                dest_name = os.path.basename(item)
                dest_path = os.path.join(out_content, dest_name)
                if os.path.isdir(src_path):
                    print("[{}] Copying (outside root) {} -> Content/{}".format(
                        game_id, item, dest_name))
                    if os.path.exists(dest_path):
                        shutil.rmtree(dest_path)
                    shutil.copytree(src_path, dest_path)
                elif os.path.isfile(src_path):
                    print("[{}] Copying (outside root) {} -> Content/{}".format(
                        game_id, item, dest_name))
                    os.makedirs(out_content, exist_ok=True)
                    shutil.copy2(src_path, dest_path)
            else:
                # Inside game root – move into Content
                src_path = os.path.join(out_dir, item)
                dest_path = os.path.join(out_content, item)
                if os.path.isdir(src_path):
                    print("[{}] Merging {} -> Content/{}".format(
                        game_id, item, item))
                    _copytree_merge(src_path, dest_path)
                    shutil.rmtree(src_path)
                elif os.path.isfile(src_path):
                    print("[{}] Moving {} -> Content/{}".format(
                        game_id, item, item))
                    os.makedirs(os.path.dirname(dest_path), exist_ok=True)
                    shutil.move(src_path, dest_path)
                else:
                    print("[{}] WARNING: move-to-Content path not found: '{}'"
                          .format(game_id, item))

        # copy-to-content
        copy_list = game_output.get("copy-to-content", [])
        for src_rel in copy_list:
            src_rel = src_rel.replace("\\", "/").rstrip("/")
            src_path = os.path.normpath(
                os.path.join(os.getcwd(), src_rel)
            )
            dest_name = os.path.basename(src_rel)
            dest_path = os.path.join(out_content, dest_name)
            if os.path.isfile(src_path):
                print("[{}] Copying {} -> Content/{}".format(
                    game_id, src_rel, dest_name))
                os.makedirs(out_content, exist_ok=True)
                shutil.copy2(src_path, dest_path)
            elif os.path.isdir(src_path):
                print("[{}] Copying {} -> Content/{}".format(
                    game_id, src_rel, dest_name))
                if os.path.exists(dest_path):
                    shutil.rmtree(dest_path)
                shutil.copytree(src_path, dest_path)
            else:
                print("[{}] WARNING: copy-to-content source not found: '{}'"
                      .format(game_id, src_rel))

        # keep-only-content
        if game_output.get("keep-only-content", True):
            print("[{}] Removing everything outside Content/...".format(game_id))
            for entry in os.listdir(out_dir):
                if entry.lower() != "content":
                    entry_path = os.path.join(out_dir, entry)
                    if os.path.isdir(entry_path):
                        shutil.rmtree(entry_path)
                    else:
                        os.remove(entry_path)


# ---------------------------------------------------------------------------
# 8. Cleanup
# ---------------------------------------------------------------------------
def cleanup(cfg):
    """Optionally delete extracted/ and converted/ directories."""
    output_cfg = cfg.get("output", {})

    if output_cfg.get("delete-extracted-dir", False):
        extracted_dir = "extracted"
        if os.path.isdir(extracted_dir):
            print("Deleting extracted directory: '{}'".format(extracted_dir))
            shutil.rmtree(extracted_dir)

    if output_cfg.get("delete-converted-dir", False):
        converted_dir = "converted"
        if os.path.isdir(converted_dir):
            print("Deleting converted directory: '{}'".format(converted_dir))
            shutil.rmtree(converted_dir)


# ---------------------------------------------------------------------------
# Standalone CLI command handlers
# ---------------------------------------------------------------------------
def cmd_config(args):
    """Run the full pipeline from a JSON config file."""
    cfg = load_config(args.config)

    # Pre-flight: check ffmpeg if any game wants WMA-to-OGG conversion
    convert_section = cfg.get("convert", {})
    needs_ffmpeg = any(
        get_convert_settings(cfg, gid)[0]
        for gid in convert_section.get("content", {})
    )
    if needs_ffmpeg:
        check_ffmpeg()

    content_types = extract_content(cfg)
    convert_xnb(cfg)
    convert_wma_to_ogg(cfg)
    assemble_output(cfg, content_types)
    post_output_adjustments(cfg)
    cleanup(cfg)

    print("\nDone! All assets processed successfully.")


def cmd_extract_360(args):
    """Extract an Xbox 360 STFS package."""
    pkg_path = args.path
    if not os.path.isfile(pkg_path):
        die("Package not found: '{}'".format(pkg_path))
    dest = args.output or "extracted"
    os.makedirs(dest, exist_ok=True)
    print("Extracting 360 STFS package: {} -> {}".format(pkg_path, dest))
    extract_live_pirs(pkg_path, dest)
    print("Done.")


def cmd_extract_xap(args):
    """Extract a Windows Phone XAP package."""
    pkg_path = args.path
    if not os.path.isfile(pkg_path):
        die("Package not found: '{}'".format(pkg_path))
    dest = args.output or "extracted"
    os.makedirs(dest, exist_ok=True)
    print("Extracting XAP package: {} -> {}".format(pkg_path, dest))
    _extract_xap(pkg_path, dest)
    print("Done.")


def cmd_convert(args):
    """Convert .xnb files (and optionally .wma) from a content directory."""
    content_dir = args.content_dir
    if not os.path.isdir(content_dir):
        die("Content directory not found: '{}'".format(content_dir))

    ignore_list = args.ignore or []
    export_dir = args.output or "converted"

    # Convert .xnb files
    xnb_files = list(find_files_by_ext(content_dir, ".xnb"))
    active_xnbs = [f for f in xnb_files if not _is_ignored(f, ignore_list)]

    if active_xnbs:
        print("Converting {} .xnb file(s)...".format(len(active_xnbs)))
        os.makedirs(export_dir, exist_ok=True)
        read_xnb_dir(content_dir, export_dir)
    else:
        print("No .xnb files to convert.")

    # Optionally convert .wma files
    if args.wma_to_ogg:
        check_ffmpeg()
        wma_files = list(find_files_by_ext(content_dir, ".wma"))
        active_wmas = [f for f in wma_files if not _is_ignored(f, ignore_list)]

        if active_wmas:
            print("Converting {} .wma file(s) to .ogg...".format(len(active_wmas)))
            os.makedirs(export_dir, exist_ok=True)
            for rel in active_wmas:
                full_path = os.path.join(content_dir, rel)
                ogg_rel = os.path.splitext(rel)[0] + ".ogg"
                ogg_path = os.path.join(export_dir, ogg_rel)
                ogg_dir = os.path.dirname(ogg_path)
                if ogg_dir:
                    os.makedirs(ogg_dir, exist_ok=True)
                print("    {} -> {}".format(rel, ogg_rel))
                subprocess.check_call([
                    "ffmpeg", "-y",
                    "-i", full_path,
                    "-c:a", "libvorbis",
                    "-q:a", "6",
                    ogg_path,
                ], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        else:
            print("No .wma files to convert.")

    print("Done.")


def cmd_assemble(args):
    """Assemble extracted and converted assets into a final output directory."""
    ext_dir = args.extracted_dir
    conv_dir = args.converted_dir
    out_dir = args.output

    if not os.path.isdir(ext_dir):
        die("Extracted directory not found: '{}'".format(ext_dir))

    # Clean output dir
    if os.path.exists(out_dir):
        shutil.rmtree(out_dir)
    os.makedirs(out_dir)

    # Copy extracted content
    print("Copying extracted content -> output...")
    _copytree_merge(ext_dir, out_dir)

    # Merge converted content
    if os.path.isdir(conv_dir):
        out_content = os.path.join(out_dir, "Content")
        print("Merging converted assets -> output...")
        _copytree_merge(conv_dir, out_content)

    # Clean up .xnb / .wma originals that have converted counterparts
    _cleanup_converted_originals_standalone(out_dir)

    print("Done.")


def _cleanup_converted_originals_standalone(out_dir):
    """Delete .xnb/.wma files that have a converted counterpart (no ignore list)."""
    out_content = os.path.join(out_dir, "Content")
    if not os.path.isdir(out_content):
        return

    converted_extensions = {
        ".png", ".wav", ".ogg", ".wma", ".xml", ".fxb", ".spritefont",
        ".bmp", ".jpg", ".jpeg", ".tga", ".dds",
    }

    for dirpath, _, filenames in os.walk(out_content):
        for fname in filenames:
            full = os.path.join(dirpath, fname)
            rel = os.path.relpath(full, out_content)

            base, ext = os.path.splitext(fname)
            ext_lower = ext.lower()

            if ext_lower not in (".xnb", ".wma"):
                continue

            has_counterpart = False
            for other in filenames:
                other_base, other_ext = os.path.splitext(other)
                if other_base == base and other_ext.lower() in converted_extensions:
                    has_counterpart = True
                    break

            if has_counterpart:
                print("    Removing original: {}".format(rel))
                os.remove(full)


# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------
def main():
    parser = argparse.ArgumentParser(
        description="XNA-to-FNA asset extractor. Use a JSON config or run "
                    "individual steps from the command line.")
    sub = parser.add_subparsers(dest="command", help="Available commands")

    # config <file>
    p_config = sub.add_parser("config", help="Run the full pipeline from a JSON config file")
    p_config.add_argument("config", help="Path to the JSON configuration file")
    p_config.set_defaults(func=cmd_config)

    # extract-360 <path> [--output <dir>]
    p_e360 = sub.add_parser("extract-360", help="Extract an Xbox 360 STFS package")
    p_e360.add_argument("path", help="Path to the 360 package file")
    p_e360.add_argument("--output", "-o", default="extracted",
                        help="Output directory (default: extracted)")
    p_e360.set_defaults(func=cmd_extract_360)

    # extract-xap <path> [--output <dir>]
    p_exap = sub.add_parser("extract-xap", help="Extract a Windows Phone XAP package")
    p_exap.add_argument("path", help="Path to the .xap file")
    p_exap.add_argument("--output", "-o", default="extracted",
                        help="Output directory (default: extracted)")
    p_exap.set_defaults(func=cmd_extract_xap)

    # convert <content-dir> [--output <dir>] [--ignore ...] [--wma-to-ogg]
    p_conv = sub.add_parser("convert", help="Convert .xnb (and optionally .wma) files")
    p_conv.add_argument("content_dir", help="Path to the Content directory with .xnb files")
    p_conv.add_argument("--output", "-o", default="converted",
                        help="Output directory (default: converted)")
    p_conv.add_argument("--ignore", "-i", nargs="*", default=[],
                        help="File patterns to ignore (e.g. 'Arial.xnb')")
    p_conv.add_argument("--wma-to-ogg", action="store_true",
                        help="Also convert .wma files to .ogg (requires ffmpeg)")
    p_conv.set_defaults(func=cmd_convert)

    # assemble <extracted-dir> <converted-dir> --output <dir>
    p_asm = sub.add_parser("assemble", help="Assemble final output from extracted and converted dirs")
    p_asm.add_argument("extracted_dir", help="Path to the extracted assets directory")
    p_asm.add_argument("converted_dir", help="Path to the converted assets directory")
    p_asm.add_argument("--output", "-o", required=True,
                       help="Output directory for the assembled result")
    p_asm.set_defaults(func=cmd_assemble)

    args = parser.parse_args()

    if args.command is None:
        parser.print_help()
        sys.exit(1)

    args.func(args)


if __name__ == "__main__":
    main()
