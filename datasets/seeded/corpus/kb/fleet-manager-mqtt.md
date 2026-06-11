# Connecting robots to Fleet Manager over MQTT

All Helios robots publish telemetry to Fleet Manager over MQTT with TLS 1.3. This article explains the configuration steps, prerequisites, and the most
common pitfalls our support team sees in the field.

## Setup

Provision credentials in the Fleet Manager admin console, then apply the configuration
to each robot from the fleet settings page. Changes propagate at the next telemetry
heartbeat, normally within one minute.

## Troubleshooting

If the connection does not establish, verify network egress rules and certificate
validity, then consult the event log for the exact handshake error.
