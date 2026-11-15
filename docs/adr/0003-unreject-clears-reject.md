# Un-reject clears Reject (Reject is no longer sticky)

Reject used to be sticky after the 20s local undo window so a Mix could never re-enter sequences. Play history / Catalog restore needs a way back, so Reject and Un-reject are now last-write-wins by signed author time (then `(device_id, seq, event.id)`), like Intent upsert/delete. Un-reject does not restore File bytes; Cache fill runs when the Mix is assigned again.
