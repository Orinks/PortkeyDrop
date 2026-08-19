#!/usr/bin/env bash
# Stand up a throwaway sshd with one host key of each type, so the host key
# check runs against a real server rather than a fixture.
#
# Reasoning about known_hosts got the answer wrong twice; measuring found two
# real defects in minutes. Run this, then:
#
#   PORTKEYDROP_TEST_SSHD=127.0.0.1:2222 #     cargo test -p portkeydrop-core --test host_key_live --test host_key_journey
#
# Those tests skip themselves when the variable is unset, so CI is unaffected.
set -uo pipefail

sudo DEBIAN_FRONTEND=noninteractive apt-get install -y -qq openssh-server >/dev/null 2>&1

RUN=$HOME/sshd-harness
rm -rf "$RUN"; mkdir -p "$RUN"
cd "$RUN" || exit 1

for type in ed25519 rsa ecdsa; do
	ssh-keygen -q -t "$type" -f "host_$type" -N "" </dev/null
done

cat > sshd_config <<CONF
Port 2222
ListenAddress 127.0.0.1
HostKey $RUN/host_ed25519
HostKey $RUN/host_rsa
HostKey $RUN/host_ecdsa
PidFile $RUN/sshd.pid
LogLevel VERBOSE
UsePAM no
PasswordAuthentication yes
PermitRootLogin no
StrictModes no
Subsystem sftp /usr/lib/openssh/sftp-server
CONF

sudo mkdir -p /run/sshd
sudo /usr/sbin/sshd -f "$RUN/sshd_config" -E "$RUN/sshd.log" 2>&1 | head -3
sleep 1
if ss -lnt 2>/dev/null | grep -q ":2222"; then
	echo "sshd listening on 127.0.0.1:2222"
else
	echo "sshd did not start:"; tail -5 "$RUN/sshd.log" 2>/dev/null
	exit 1
fi

echo
echo "=== what OpenSSH itself records for this server ==="
rm -f "$RUN/openssh_known_hosts"
for type in ssh-ed25519 rsa-sha2-512 ecdsa-sha2-nistp256; do
	ssh-keyscan -p 2222 -t "${type%%-sha2*}" 127.0.0.1 2>/dev/null
done | tee "$RUN/keyscan.txt" | awk '{print "  " $1 "  " $2}'
