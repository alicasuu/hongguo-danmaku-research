#!/usr/bin/env bash
set -euo pipefail

if [ "$#" -ne 2 ]; then
  echo 'Usage: single_episode_encrypt.sh PRIVATE_DIRECTORY ENCRYPTED_PREFIX' >&2
  exit 2
fi
source_dir="$1"
dest_prefix="$2"
public_key='data/frozen/v1_encryption_public.pem'
test -d "$source_dir"
test -s "$public_key"
mkdir -p "$(dirname "$dest_prefix")"

one_time_secret="$(mktemp)"
trap 'rm -f "$one_time_secret"' EXIT
chmod 600 "$one_time_secret"
openssl rand -hex 32 > "$one_time_secret"
tar -cz -C "$source_dir" . | openssl enc -aes-256-cbc -salt -pbkdf2 \
  -iter 200000 -pass "file:$one_time_secret" \
  -out "${dest_prefix}.tar.gz.enc"
openssl pkeyutl -encrypt -pubin -inkey "$public_key" \
  -pkeyopt rsa_padding_mode:oaep -pkeyopt rsa_oaep_md:sha256 \
  -in "$one_time_secret" -out "${dest_prefix}.key.enc"
sha256sum "${dest_prefix}.tar.gz.enc" > "${dest_prefix}.tar.gz.enc.sha256"
echo 'Single episode evidence encrypted before upload.'
