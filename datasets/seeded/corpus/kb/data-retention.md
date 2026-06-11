# Telemetry data retention

Telemetry data is retained in Fleet Manager for 13 months by default. This article explains the configuration steps, prerequisites, and the most
common pitfalls our support team sees in the field.

## Setup

Provision credentials in the Fleet Manager admin console, then apply the configuration
to each robot from the fleet settings page. Changes propagate at the next telemetry
heartbeat, normally within one minute.

## Troubleshooting

If the connection does not establish, verify network egress rules and certificate
validity, then consult the event log for the exact handshake error.
