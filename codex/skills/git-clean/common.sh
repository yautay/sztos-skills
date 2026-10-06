#!/usr/bin/env bash
# Internal helpers; packaged with each provider's standalone skill.
SEP=$'\x1f'
encode_field() {
  local value="$1"
  value=${value//%/%25}; value=${value//|/%7C}
  value=${value//$'\r'/%0D}; value=${value//$'\n'/%0A}
  printf '%s' "$value"
}
row() {
  local delimiter="" value
  for value in "$@"; do
    printf '%s' "$delimiter"; encode_field "$value"; delimiter='|'
  done
  printf '\n'
}
quote_arg() {
  local value="$1"
  value=${value//\'/\'\"\'\"\'}
  printf "'%s'" "$value"
}
positive_integer() { [[ "$1" =~ ^[0-9]+$ ]] && [ "${#1}" -le 7 ] && [ "$1" -gt 0 ]; }
