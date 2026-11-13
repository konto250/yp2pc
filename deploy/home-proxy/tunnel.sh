#!/bin/sh
set -eu
# 個人用の鍵ではなく、この逆方向転送だけを許可した専用鍵を使用します。
exec ssh -F /dev/null -NT \
    -i /run/secrets/tunnel-key \
    -o UserKnownHostsFile=/run/secrets/known-hosts \
    -o StrictHostKeyChecking=yes -o BatchMode=yes -o IdentitiesOnly=yes \
    -o ExitOnForwardFailure=yes -o ServerAliveInterval=20 -o ServerAliveCountMax=3 \
    -o ConnectTimeout=10 \
    -R 127.0.0.1:18888:proxy:3128 \
    "${OCI_SSH_USER:?接続ユーザーが必要です}@${OCI_SSH_HOST:?接続先が必要です}"
