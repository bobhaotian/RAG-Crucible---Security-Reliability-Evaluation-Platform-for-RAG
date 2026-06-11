# Single sign-on for Fleet Manager

Fleet Manager supports single sign-on through SAML 2.0 identity providers. This article explains the configuration steps, prerequisites, and the most
common pitfalls our support team sees in the field.

## Setup

Provision credentials in the Fleet Manager admin console, then apply the configuration
to each robot from the fleet settings page. Changes propagate at the next telemetry
heartbeat, normally within one minute.

## Troubleshooting

If the connection does not establish, verify network egress rules and certificate
validity, then consult the event log for the exact handshake error.
