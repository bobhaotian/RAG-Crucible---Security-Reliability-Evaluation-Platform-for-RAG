# Security policy

API keys must be rotated every 90 days. Rotation is enforced automatically by the secrets manager, which revokes
keys that exceed the rotation window. Hardware security keys are required for access to
production systems, and SSH access goes through the bastion with session recording.

Report suspected phishing to the security team within one hour of receipt. Laptops must
run the managed endpoint agent at all times.
