#!/bin/sh
set -eu

: "${MQTT_GATEWAY_PASSWORD:?set MQTT_GATEWAY_PASSWORD}"
: "${MQTT_INGEST_PASSWORD:?set MQTT_INGEST_PASSWORD}"
: "${MQTT_CHIRPSTACK_PASSWORD:?set MQTT_CHIRPSTACK_PASSWORD}"
: "${MQTT_FORWARDER_PASSWORD:?set MQTT_FORWARDER_PASSWORD}"
if [ "$MQTT_GATEWAY_PASSWORD" = "$MQTT_INGEST_PASSWORD" ] || \
    [ "$MQTT_GATEWAY_PASSWORD" = "$MQTT_CHIRPSTACK_PASSWORD" ] || \
    [ "$MQTT_GATEWAY_PASSWORD" = "$MQTT_FORWARDER_PASSWORD" ] || \
    [ "$MQTT_INGEST_PASSWORD" = "$MQTT_CHIRPSTACK_PASSWORD" ] || \
    [ "$MQTT_INGEST_PASSWORD" = "$MQTT_FORWARDER_PASSWORD" ] || \
    [ "$MQTT_CHIRPSTACK_PASSWORD" = "$MQTT_FORWARDER_PASSWORD" ]; then
    echo "MQTT client passwords must be different." >&2
    exit 1
fi

umask 077
mkdir -p /mosquitto/data /mosquitto/log
# Mosquitto 2.1+ refuses -c when the destination exists. Build fresh files
# in a private directory, then replace them atomically before starting.
auth_dir=$(mktemp -d /mosquitto/data/auth.XXXXXX)
trap 'rm -f "$auth_dir/passwd" "$auth_dir/acl"; rmdir "$auth_dir"' EXIT
cp /mosquitto/config/acl "$auth_dir/acl"
mosquitto_passwd -b -c "$auth_dir/passwd" sensorhub-gateway "$MQTT_GATEWAY_PASSWORD"
mosquitto_passwd -b "$auth_dir/passwd" sensorhub-ingest "$MQTT_INGEST_PASSWORD"
mosquitto_passwd -b "$auth_dir/passwd" sensorhub-chirpstack "$MQTT_CHIRPSTACK_PASSWORD"
mosquitto_passwd -b "$auth_dir/passwd" sensorhub-ug65-forwarder "$MQTT_FORWARDER_PASSWORD"
chown mosquitto:mosquitto /mosquitto/data /mosquitto/log "$auth_dir/passwd" "$auth_dir/acl"
chmod 0600 "$auth_dir/passwd" "$auth_dir/acl"
mv -f "$auth_dir/passwd" /mosquitto/data/passwd
mv -f "$auth_dir/acl" /mosquitto/data/acl
rmdir "$auth_dir"
trap - EXIT
unset MQTT_GATEWAY_PASSWORD MQTT_INGEST_PASSWORD MQTT_CHIRPSTACK_PASSWORD MQTT_FORWARDER_PASSWORD
exec mosquitto -c /mosquitto/config/mosquitto.conf
