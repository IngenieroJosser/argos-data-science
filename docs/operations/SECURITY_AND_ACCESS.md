# ARGOS — Security and Access

Use least privilege. Bronze/Silver sensitive fields are not model inputs by default and explicitly forbidden sensitive columns must not appear in scoring outputs or review queues. Registry, model artifacts, manifests and audit logs require restricted write access. Operational users may consume review queues without receiving training labels or sensitive source payloads. Secrets must be supplied by the deployment environment, never committed to the repository.
