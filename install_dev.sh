#!/usr/bin/env bash
# Dev install for this machine: a plain copy of add-ons into the user_default extensions folder,
# replacing the old copy. Usage: Addons/install_dev.sh [name ...]   (no names = every add-on: digits_assorted_tools, digits_modifiers, digits_processes, digits_vr, render_presets)
# Run again after edits. Blender needs a restart / re-enable to reload it.
set -euo pipefail
here="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
dest="${EXTENSIONS_DIR:-$HOME/.config/blender/5.3/extensions/user_default}"

python3 "$here/shared_addon/sync_shared.py" > /dev/null
if [ $# -eq 0 ]; then
    set -- $(cd "$here" && for d in */; do [ -f "$d/blender_manifest.toml" ] && echo "${d%/}"; done)
fi
for name in "$@"; do
    [ -f "$here/$name/blender_manifest.toml" ] || { echo "Not an add-on: $name" >&2; exit 1; }
    mkdir -p "$dest/$name"
    rsync -a --delete --exclude '__pycache__/' --exclude '/tests/' --exclude '/dist/' --exclude '/package.sh' \
        --exclude '/install_dev.sh' --exclude '/assets/Previews/' --exclude '*.blend1' --exclude '*.bak' --exclude '*.bak.*' \
        "$here/$name/" "$dest/$name/"
    echo "Installed $dest/$name"
done
