#!/usr/bin/env bash
set -u

STAMP="$(date +%Y%m%d_%H%M%S)"
LOG="$HOME/grantbot_v17_${STAMP}.log"
INSTALLER=""

for candidate in \
  "$HOME/grantbot_installers/grantbot_v17_staging_writer.sh" \
  "$HOME/Downloads/grantbot_v17_staging_writer.sh" \
  "/mnt/chromeos/MyFiles/Downloads/grantbot_v17_staging_writer.sh"
do
  if [[ -f "$candidate" ]]; then
    INSTALLER="$candidate"
    break
  fi
done

if [[ -z "$INSTALLER" ]]; then
  INSTALLER="$(find \
    "$HOME/Downloads" \
    "/mnt/chromeos/MyFiles/Downloads" \
    -maxdepth 1 -type f \
    -name 'grantbot_v17_staging_writer*.sh' \
    -print -quit 2>/dev/null || true)"
fi

printf '\n============================================================\n'
printf ' GRANTBOT PRO V17 — SAFE TERMINAL LAUNCHER\n'
printf '============================================================\n'
printf 'Log: %s\n' "$LOG"

if [[ -z "$INSTALLER" || ! -f "$INSTALLER" ]]; then
  printf '\nERROR: Could not find grantbot_v17_staging_writer.sh\n' | tee -a "$LOG"
  printf 'Expected it in ChromeOS Downloads, ~/Downloads, or ~/grantbot_installers.\n' | tee -a "$LOG"
  printf '\nTerminal is staying open so the error can be read.\n'
  exec "${SHELL:-/bin/bash}" -i
fi

mkdir -p "$HOME/grantbot_installers"
CANONICAL="$HOME/grantbot_installers/grantbot_v17_staging_writer.sh"

if [[ "$INSTALLER" != "$CANONICAL" ]]; then
  cp "$INSTALLER" "$CANONICAL"
fi
chmod +x "$CANONICAL"

if ! bash -n "$CANONICAL"; then
  printf '\nERROR: Installer failed Bash syntax validation.\n' | tee -a "$LOG"
  printf 'Installer: %s\n' "$CANONICAL" | tee -a "$LOG"
  printf '\nTerminal is staying open.\n'
  exec "${SHELL:-/bin/bash}" -i
fi

printf 'Installer: %s\n\n' "$CANONICAL" | tee -a "$LOG"

set +e
bash "$CANONICAL" 2>&1 | tee -a "$LOG"
RC=${PIPESTATUS[0]}
set -e

printf '\n============================================================\n' | tee -a "$LOG"
if [[ "$RC" -eq 0 ]]; then
  printf ' V17 INSTALL RESULT: SUCCESS\n' | tee -a "$LOG"
else
  printf ' V17 INSTALL RESULT: FAILED (exit code %s)\n' "$RC" | tee -a "$LOG"
  printf ' Full failure log: %s\n' "$LOG" | tee -a "$LOG"
fi
printf '============================================================\n' | tee -a "$LOG"
printf '\nTerminal will remain open. Type exit only when you want to close it.\n\n'

cd "$HOME/grantbot_pro" 2>/dev/null || cd "$HOME"
exec "${SHELL:-/bin/bash}" -i
