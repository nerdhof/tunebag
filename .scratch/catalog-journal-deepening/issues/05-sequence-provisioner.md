# 05: SequenceProvisioner drafts

**What to build:** Extract Sequence rebuild decisioning and Event drafting into SequenceProvisioner. It decides whether an Intent needs a rebuild and returns drafts for Sequence built and Assignment cleared/set. The caller appends those drafts (via CatalogJournal under `hold` when atomicity matters). Pure sequence ordering helpers stay separate. Catalog maintenance keeps Cache fill and prune only.

**Blocked by:** 02 — CatalogJournal for local append, hold, export, and boot replay

**Status:** ready-for-agent

- [ ] SequenceProvisioner exposes need-rebuild and provision → Event drafts (does not append itself)
- [ ] DeviceAgent / Catalog maintenance append drafts under `hold` where Intent upsert + rebuild must stay atomic
- [ ] Explore empty-assignment and under-budget rebuild rules still behave as today
- [ ] Fill and prune remain outside the provisioner
- [ ] Pure tests cover need-rebuild and draft contents; at least one path shows drafts committed to the Event log
