#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
LOCAL_DIR="$ROOT_DIR/.local-mesh-test"
INVENTORY="$LOCAL_DIR/device-inventory.tsv"
MICROPYTHON_IMAGE="$LOCAL_DIR/ESP32_GENERIC_S3-SPIRAM_OCT-v1.29.0.bin"

declare -a PORTS MACS ROLES DEVICE_IDS SERIAL_UIDS ASSIGNMENTS
declare -A USED_ROLES
PLAN_FILE=""
DRY_RUN=0
DO_FLASH=0

die() {
  printf 'Erro: %s\n' "$*" >&2
  exit 1
}

need() {
  command -v "$1" >/dev/null 2>&1 || die "comando obrigatório não encontrado: $1"
}

probe_code=$'import sys\nimport network\nsys.path.append("/lib")\nw = network.WLAN(network.STA_IF)\nw.active(True)\nmac = ":".join("%02x" % b for b in w.config("mac"))\nrole = "unknown"\ndevice_id = ""\ntry:\n from settings import Settings\n s = Settings()\n role = s.role\n device_id = s.node_id\nexcept Exception:\n pass\nprint("MESHOPS_PROBE|%s|%s|%s" % (mac, role, device_id))'

discover() {
  printf '\n== Fase 1: inventário dos ESP32 ==\n'
  mapfile -t PORTS < <(
    mpremote connect list 2>/dev/null |
      awk '$1 ~ /^\/dev\/tty(ACM|USB)/ {print $1}'
  )
  ((${#PORTS[@]})) || die "nenhum ESP32 encontrado em ttyACM/ttyUSB"
  mkdir -p "$LOCAL_DIR"
  printf 'port\tmac\trole\tdevice_id\tserial_uid\n' > "$INVENTORY"

  local port line probe mac role device_id usb_id
  for port in "${PORTS[@]}"; do
    line=$(mpremote connect list 2>/dev/null | awk -v target="$port" '$1 == target {print; exit}')
    usb_id=$(awk '{print $2}' <<<"$line")
    probe=$(mpremote connect "$port" exec "$probe_code" 2>/dev/null || true)
    probe=${probe//$'\r'/}
    if grep -q 'MESHOPS_PROBE|' <<<"$probe"; then
      probe=$(grep 'MESHOPS_PROBE|' <<<"$probe" | tail -1)
      IFS='|' read -r _ mac role device_id <<<"$probe"
      mpremote connect "$port" reset >/dev/null 2>&1 || true
    else
      mac="unavailable"
      role="unknown/native"
      device_id=""
    fi
    MACS+=("$mac")
    ROLES+=("$role")
    DEVICE_IDS+=("$device_id")
    SERIAL_UIDS+=("$usb_id")
    printf '%s\t%s\t%s\t%s\t%s\n' \
      "$port" "$mac" "$role" "$device_id" "$usb_id" >> "$INVENTORY"
    printf '[%d] %-14s MAC=%-17s atual=%s/%s serial=%s\n' \
      "${#MACS[@]}" "$port" "$mac" "$role" "${device_id:--}" "$usb_id"
  done
  printf 'Inventário guardado em %s\n' "$INVENTORY"
}

suggestion_for() {
  case "$1" in
    gateway-01) printf '1' ;;
    sink-01) printf '2' ;;
    implant-a) printf '3' ;;
    implant-b) printf '4' ;;
    *) printf '5' ;;
  esac
}

assign_roles() {
  printf '\n== Fase 2: atribuição de funções ==\n'
  printf '  1) gateway-01   2) lora_sink   3) implant-a\n'
  printf '  4) implant-b    5) ignorar\n'
  local i choice suggested role_key
  for i in "${!PORTS[@]}"; do
    suggested=$(suggestion_for "${DEVICE_IDS[$i]}")
    while true; do
      printf '\n%s  MAC=%s  função atual=%s/%s\n' \
        "${PORTS[$i]}" "${MACS[$i]}" "${ROLES[$i]}" "${DEVICE_IDS[$i]:--}"
      read -r -p "Função [sugestão $suggested]: " choice
      choice=${choice:-$suggested}
      case "$choice" in
        1) role_key="gateway-01" ;;
        2) role_key="lora_sink" ;;
        3) role_key="implant-a" ;;
        4) role_key="implant-b" ;;
        5) role_key="skip" ;;
        *) printf 'Escolha inválida.\n'; continue ;;
      esac
      if [[ "$role_key" != "skip" && -n "${USED_ROLES[$role_key]:-}" ]]; then
        printf '%s já foi atribuído a %s.\n' "$role_key" "${USED_ROLES[$role_key]}"
        continue
      fi
      ASSIGNMENTS[$i]=$role_key
      [[ "$role_key" == "skip" ]] || USED_ROLES[$role_key]=${PORTS[$i]}
      break
    done
  done
}

config_for() {
  if [[ -f "$LOCAL_DIR/$1.json" ]]; then
    printf '%s/%s.json' "$LOCAL_DIR" "$1"
    return
  fi
  case "$1" in
    gateway-01) printf '%s/gateway.connected.json' "$LOCAL_DIR" ;;
    lora_sink) printf '%s/receiver.connected.json' "$LOCAL_DIR" ;;
    implant-a) printf '%s/node-a.json' "$LOCAL_DIR" ;;
    implant-b) printf '%s/node-b.json' "$LOCAL_DIR" ;;
    *) return 1 ;;
  esac
}

render_plan() {
  [[ -f "$PLAN_FILE" ]] || die "plano não encontrado: $PLAN_FILE"
  python3 "$ROOT_DIR/lib/network_plan.py" --plan "$PLAN_FILE" --output "$LOCAL_DIR" \
    $([[ "$DRY_RUN" -eq 1 ]] && printf '%s' '--print')
  printf 'Plano validado e configurações renderizadas em %s\n' "$LOCAL_DIR"
}

assign_from_plan() {
  local manifest="$LOCAL_DIR/device-manifest.tsv"
  [[ -f "$manifest" ]] || die "manifesto renderizado não encontrado"
  local i normalized device_id
  for i in "${!PORTS[@]}"; do
    normalized=${MACS[$i],,}
    device_id=$(awk -F '\t' -v mac="$normalized" 'NR > 1 && tolower($2) == mac {print $1; exit}' "$manifest")
    if [[ -z "$device_id" ]]; then
      ASSIGNMENTS[$i]="skip"
    else
      ASSIGNMENTS[$i]=$device_id
    fi
  done
  while IFS=$'\t' read -r device_id mac _role; do
    [[ "$device_id" == "device_id" ]] && continue
    normalized=${mac,,}
    local found=0
    for i in "${!MACS[@]}"; do
      [[ "${MACS[$i],,}" == "$normalized" ]] && found=1
    done
    [[ "$found" -eq 1 ]] || die "dispositivo do plano não ligado: $device_id ($mac)"
  done < "$manifest"
}

ensure_micropython() {
  local port=$1
  if mpremote connect "$port" exec pass >/dev/null 2>&1; then
    return
  fi
  [[ -f "$MICROPYTHON_IMAGE" ]] || die "$port não tem MicroPython e falta $MICROPYTHON_IMAGE"
  python3 -m esptool version >/dev/null 2>&1 || \
    die "$port não tem MicroPython; instale esptool para usar a imagem local"
  printf 'A instalar MicroPython base em %s...\n' "$port"
  python3 -m esptool --chip esp32s3 --port "$port" erase_flash
  python3 -m esptool --chip esp32s3 --port "$port" write_flash -z 0 "$MICROPYTHON_IMAGE"
  sleep 4
}

flash_one() {
  local port=$1 role=$2 config
  printf '\n-- %s -> %s --\n' "$port" "$role"
  config=$(config_for "$role") || die "função sem configuração: $role"
  [[ -f "$config" ]] || die "configuração local não encontrada: $config"
  ensure_micropython "$port"
  python3 "$ROOT_DIR/flasher.py" --port "$port" --settings "$config"
}

confirm_and_flash() {
  printf '\n== Plano de gravação ==\n'
  local i answer
  for i in "${!PORTS[@]}"; do
    printf '%-14s %-17s -> %s\n' "${PORTS[$i]}" "${MACS[$i]}" "${ASSIGNMENTS[$i]}"
  done
  printf '\nA gravação substitui o firmware/configuração das placas selecionadas.\n'
  read -r -p 'Escreva FLASH para continuar: ' answer
  [[ "$answer" == "FLASH" ]] || die "operação cancelada"
  for i in "${!PORTS[@]}"; do
    [[ "${ASSIGNMENTS[$i]}" == "skip" ]] && continue
    flash_one "${PORTS[$i]}" "${ASSIGNMENTS[$i]}"
  done
}

main() {
  if [[ "${1:-}" == "--help" ]]; then
    printf 'Uso: %s [--inventory-only] [--plan FILE] [--dry-run] [--flash]\n' "$0"
    printf '  --inventory-only  deteta placas e guarda MAC/role sem gravar\n'
    printf '  --plan FILE        valida e renderiza o plano completo da rede\n'
    printf '  --dry-run          mostra configurações renderizadas; nunca grava\n'
    printf '  --flash            grava todos os dispositivos do plano após confirmação\n'
    return
  fi
  local inventory_only=0
  while [[ $# -gt 0 ]]; do
    case "$1" in
      --inventory-only) inventory_only=1 ;;
      --plan) shift; [[ $# -gt 0 ]] || die "--plan requer um ficheiro"; PLAN_FILE=$1 ;;
      --dry-run) DRY_RUN=1 ;;
      --flash) DO_FLASH=1 ;;
      *) die "argumento desconhecido: $1" ;;
    esac
    shift
  done
  need python3
  cd "$ROOT_DIR"
  if [[ -n "$PLAN_FILE" ]]; then
    render_plan
    if [[ "$DRY_RUN" -eq 1 || "$DO_FLASH" -eq 0 ]]; then
      printf 'Validação concluída; nenhuma placa foi gravada.\n'
      return
    fi
  fi
  need mpremote
  discover
  if [[ "$inventory_only" -eq 1 ]]; then
    return
  fi
  if [[ -n "$PLAN_FILE" ]]; then
    assign_from_plan
  else
    [[ "$DRY_RUN" -eq 0 && "$DO_FLASH" -eq 0 ]] || \
      die "--dry-run/--flash requer --plan"
    assign_roles
  fi
  confirm_and_flash
  printf '\nInstalação concluída. Inventário: %s\n' "$INVENTORY"
}

main "$@"
