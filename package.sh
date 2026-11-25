#!/usr/bin/env bash
# Build the shareable extension zips. Usage: Addons/package.sh [name ...]   (no names = every add-on: digits_assorted_tools, digits_modifiers, digits_processes, digits_vr, render_presets)
# Syncs the shared code, then for each add-on: validates, builds into <name>/dist/ (the manifest's [build] excludes keep
# out tests, backups, caches) and copies the zip to ~/Downloads. Prints each zip's path.
set -euo pipefail
here="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
blender="${BLENDER:-blender}"
downloads="${DOWNLOADS_DIR:-$HOME/Downloads}"

python3 "$here/shared_addon/sync_shared.py" > /dev/null
if [ $# -eq 0 ]; then
    set -- $(cd "$here" && for d in */; do [ -f "$d/blender_manifest.toml" ] && echo "${d%/}"; done)
fi
for name in "$@"; do
    dir="$here/$name"
    [ -f "$dir/blender_manifest.toml" ] || { echo "Not an add-on: $name" >&2; exit 1; }
    id="$(sed -n 's/^id = "\(.*\)"/\1/p' "$dir/blender_manifest.toml")"
    version="$(sed -n 's/^version = "\(.*\)"/\1/p' "$dir/blender_manifest.toml")"
    mkdir -p "$dir/dist" "$downloads"
    "$blender" --command extension validate "$dir"
    "$blender" --command extension build --source-dir "$dir" --output-dir "$dir/dist"
    cp "$dir/dist/$id-$version.zip" "$downloads/$id-$version.zip"
    echo "Built $dir/dist/$id-$version.zip (copied to $downloads/$id-$version.zip)"
done
